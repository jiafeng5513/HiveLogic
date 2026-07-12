# -*- coding: utf-8 -*-
"""
===================================
缓存维护：清理/保留/VACUUM
===================================

职责：
1. 按保留窗口清理过期的分钟级K线数据
2. 清理过期的调度任务日志
3. VACUUM 回收磁盘空间
4. 报告磁盘使用统计

保留策略：
- 1m: 30 天
- 5m/10m/15m/30m: 90 天
- 1h/4h: 365 天
- 1d: 永久保留
- scheduler_task_log: 90 天
"""

import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, List

from src.services.kline_cache_manager import DEFAULT_CACHE_DB

logger = logging.getLogger(__name__)

RETENTION_DAYS = {
    "1m": 30,
    "5m": 90,
    "10m": 90,
    "15m": 90,
    "30m": 90,
    "60m": 365,
    "1h": 365,
    "4h": 365,
}

TASK_LOG_RETENTION_DAYS = 90


class CacheMaintenance:
    """缓存维护与清理"""

    def __init__(self, db_path: str = DEFAULT_CACHE_DB):
        self._db_path = db_path
        self._lock = threading.Lock()

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ==================== 清理 ====================

    def cleanup_expired_klines(self) -> Dict[str, int]:
        deleted_by_interval: Dict[str, int] = {}
        now_ms = int(time.time() * 1000)
        with self._lock:
            with self._get_conn() as conn:
                for interval, days in RETENTION_DAYS.items():
                    cutoff_ms = now_ms - days * 86400 * 1000
                    cur = conn.execute(
                        """DELETE FROM kline_data
                           WHERE interval = ? AND timestamp < ?
                           AND interval != '1d'""",
                        (interval, cutoff_ms),
                    )
                    deleted_by_interval[interval] = cur.rowcount or 0

                conn.execute(
                    """DELETE FROM kline_cache_meta
                       WHERE end_time < ?""",
                    (now_ms - max(RETENTION_DAYS.values()) * 86400 * 1000,),
                )

        total = sum(deleted_by_interval.values())
        logger.info(
            "[CacheMaintenance] 清理过期K线: %d rows (by interval: %s)",
            total,
            deleted_by_interval,
        )
        return deleted_by_interval

    def cleanup_task_log(self) -> int:
        cutoff_ms = int(
            (datetime.now() - timedelta(days=TASK_LOG_RETENTION_DAYS)).timestamp()
        ) * 1000
        with self._lock:
            with self._get_conn() as conn:
                cur = conn.execute(
                    "DELETE FROM scheduler_task_log WHERE last_run_at < ?",
                    (cutoff_ms,),
                )
                deleted = cur.rowcount or 0
        logger.info("[CacheMaintenance] 清理调度日志: %d rows", deleted)
        return deleted

    def vacuum(self) -> bool:
        with self._lock:
            with self._get_conn() as conn:
                try:
                    conn.execute("VACUUM")
                    logger.info("[CacheMaintenance] VACUUM 完成")
                    return True
                except Exception as e:
                    logger.warning("[CacheMaintenance] VACUUM 失败: %s", e)
                    return False

    def run_full_cleanup(self) -> Dict[str, Any]:
        t0 = time.time()
        klines = self.cleanup_expired_klines()
        task_log = self.cleanup_task_log()
        vacuum_ok = self.vacuum()
        elapsed = time.time() - t0
        result = {
            "klines_deleted": klines,
            "task_log_deleted": task_log,
            "vacuum_ok": vacuum_ok,
            "elapsed_seconds": round(elapsed, 2),
        }
        logger.info("[CacheMaintenance] 完整清理完成: %s", result)
        return result

    # ==================== 统计 ====================

    def get_disk_usage(self) -> Dict[str, Any]:
        db_size = os.path.getsize(self._db_path) if os.path.exists(self._db_path) else 0
        wal_path = self._db_path + "-wal"
        wal_size = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
        shm_path = self._db_path + "-shm"
        shm_size = os.path.getsize(shm_path) if os.path.exists(shm_path) else 0

        table_stats: Dict[str, int] = {}
        with self._get_conn() as conn:
            for table in (
                "kline_data",
                "kline_cache_meta",
                "symbol_list",
                "symbol_list_meta",
                "market_snapshot",
                "market_snapshot_meta",
                "scheduler_task_log",
                "watchlist",
            ):
                try:
                    cur = conn.execute(f"SELECT COUNT(*) as c FROM {table}")
                    row = cur.fetchone()
                    table_stats[table] = row["c"] if row else 0
                except sqlite3.OperationalError:
                    pass

        interval_stats: Dict[str, int] = {}
        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT interval, COUNT(*) as c FROM kline_data GROUP BY interval"
            )
            interval_stats = {r["interval"]: r["c"] for r in cur.fetchall()}

        return {
            "db_size_bytes": db_size,
            "wal_size_bytes": wal_size,
            "shm_size_bytes": shm_size,
            "total_size_bytes": db_size + wal_size + shm_size,
            "db_size_mb": round(db_size / 1024 / 1024, 2),
            "table_counts": table_stats,
            "kline_by_interval": interval_stats,
        }

    def get_daily_freshness(self) -> Dict[str, Any]:
        """
        各市场日线（1d）数据新鲜度统计，供夜间缺口对账观测使用。
        返回 {market: {symbols, latest_ts, stale_days}}。
        """
        now_ms = int(time.time() * 1000)
        result: Dict[str, Any] = {}
        try:
            with self._get_conn() as conn:
                cur = conn.execute(
                    """SELECT market,
                              COUNT(DISTINCT symbol) AS symbols,
                              MAX(timestamp) AS latest_ts
                       FROM kline_data
                       WHERE interval = '1d'
                       GROUP BY market"""
                )
                for r in cur.fetchall():
                    latest_ts = r["latest_ts"] or 0
                    stale_days = round((now_ms - latest_ts) / 86400000, 1) if latest_ts else None
                    result[r["market"]] = {
                        "symbols": r["symbols"],
                        "latest_ts": latest_ts,
                        "stale_days": stale_days,
                    }
        except sqlite3.OperationalError as e:
            logger.warning("[CacheMaintenance] 日线新鲜度统计失败: %s", e)
        return result


_maintenance: CacheMaintenance | None = None
_maintenance_lock = threading.Lock()


def get_cache_maintenance(db_path: str = DEFAULT_CACHE_DB) -> CacheMaintenance:
    global _maintenance
    if _maintenance is None or _maintenance._db_path != db_path:
        with _maintenance_lock:
            if _maintenance is None or _maintenance._db_path != db_path:
                _maintenance = CacheMaintenance(db_path)
    return _maintenance
