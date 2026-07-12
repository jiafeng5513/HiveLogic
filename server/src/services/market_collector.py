# -*- coding: utf-8 -*-
"""
===================================
全市场行情快照采集器 (L0)
===================================

职责：
1. 低频（盘中数十秒~分钟级）采集全市场最新价/涨跌幅快照
2. 持久化到 market_cache.db 的 market_snapshot 表（全量替换）
3. 供标的浏览器/市场行情列表秒级读取

设计原则：
- 每个市场一次 bulk API 调用，杜绝逐标的循环
- 全量替换：每次采集用最新数据覆盖该市场全部行
- 采集与读取分离：采集写 DB，读取走 DB，互不阻塞
"""

import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)
DEFAULT_CACHE_DB = os.path.join(DEFAULT_CACHE_DIR, "market_cache.db")


class MarketCollector:
    """全市场行情快照采集器（L0）"""

    def __init__(self, db_path: str = DEFAULT_CACHE_DB):
        self._db_path = db_path
        self._write_lock = threading.Lock()
        self._init_db()
        self._last_collect: Dict[str, float] = {}

    # ==================== DB 初始化 ====================

    def _init_db(self):
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_snapshot (
                    market          TEXT    NOT NULL,
                    symbol          TEXT    NOT NULL,
                    name            TEXT    DEFAULT '',
                    price           REAL,
                    change_percent  REAL,
                    change_amount   REAL,
                    volume          REAL,
                    amount          REAL,
                    high            REAL,
                    low             REAL,
                    open            REAL,
                    prev_close      REAL,
                    updated_at      INTEGER NOT NULL,
                    PRIMARY KEY (market, symbol)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_snapshot_market ON market_snapshot(market)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_snapshot_meta (
                    market           TEXT PRIMARY KEY,
                    last_collected   INTEGER,
                    count            INTEGER DEFAULT 0,
                    last_error       TEXT
                )
                """
            )

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ==================== 采集：A股 ====================

    def collect_cn_stock(self) -> int:
        return self._collect_cn_spot(
            market="cn_stock",
            ak_func_name="stock_zh_a_spot_em",
            code_col="代码",
            symbol_transform=lambda c: c,
        )

    def collect_cn_etf(self) -> int:
        return self._collect_cn_spot(
            market="cn_etf",
            ak_func_name="fund_etf_spot_em",
            code_col="代码",
            symbol_transform=lambda c: c,
        )

    def collect_hk_stock(self) -> int:
        return self._collect_cn_spot(
            market="hk_stock",
            ak_func_name="stock_hk_spot_em",
            code_col="代码",
            symbol_transform=lambda c: f"HK{str(c).zfill(5)}",
        )

    def collect_us_stock(self) -> int:
        # 东财美股 `代码` 形如 "105.AAPL"，取 "." 后的纯 ticker
        return self._collect_cn_spot(
            market="us_stock",
            ak_func_name="stock_us_spot_em",
            code_col="代码",
            symbol_transform=lambda c: str(c).split(".")[-1].strip().upper(),
        )

    def _collect_cn_spot(
        self,
        market: str,
        ak_func_name: str,
        code_col: str,
        symbol_transform,
    ) -> int:
        import akshare as ak

        ak_func = getattr(ak, ak_func_name, None)
        if ak_func is None:
            logger.error("[MarketCollector] akshare 无 %s", ak_func_name)
            return 0

        try:
            t0 = time.time()
            df = ak_func()
            if df is None or df.empty:
                logger.warning("[MarketCollector] %s 返回空", ak_func_name)
                self._record_meta(market, 0, "empty response")
                return 0

            rows = []
            now_ms = int(time.time() * 1000)
            for _, row in df.iterrows():
                code = str(row.get(code_col, "")).strip()
                if not code:
                    continue
                symbol = symbol_transform(code)
                rows.append(
                    (
                        market,
                        symbol,
                        str(row.get("名称", "")),
                        _safe_float(row.get("最新价")),
                        _safe_float(row.get("涨跌幅")),
                        _safe_float(row.get("涨跌额")),
                        _safe_float(row.get("成交量")),
                        _safe_float(row.get("成交额")),
                        # 列名别名：A股用 最高/最低/今开/昨收，东财美股用 最高价/最低价/开盘价/昨收价
                        _safe_float(_pick(row, "最高", "最高价")),
                        _safe_float(_pick(row, "最低", "最低价")),
                        _safe_float(_pick(row, "今开", "开盘价")),
                        _safe_float(_pick(row, "昨收", "昨收价")),
                        now_ms,
                    )
                )

            count = self._persist(market, rows)
            elapsed = time.time() - t0
            self._record_meta(market, count, None)
            logger.info(
                "[MarketCollector] %s: %d symbols in %.1fs", market, count, elapsed
            )
            return count

        except Exception as e:
            logger.error("[MarketCollector] %s 失败: %s", market, e, exc_info=True)
            self._record_meta(market, 0, str(e))
            return 0

    # ==================== 采集：Crypto ====================

    def collect_crypto(self) -> int:
        import requests

        try:
            t0 = time.time()
            resp = requests.get(
                "https://api.binance.com/api/v3/ticker/24hr", timeout=20
            )
            resp.raise_for_status()
            tickers = resp.json()

            rows = []
            now_ms = int(time.time() * 1000)
            for t in tickers:
                raw_sym = t.get("symbol", "")
                if not raw_sym.endswith("USDT") and not raw_sym.endswith("BUSD"):
                    continue
                if "/" in raw_sym:
                    continue
                parts = [raw_sym[:-4], "USDT"] if raw_sym.endswith("USDT") else [raw_sym[:-4], "BUSD"]
                symbol = "/".join(parts)
                rows.append(
                    (
                        "crypto",
                        symbol,
                        symbol,
                        _safe_float(t.get("lastPrice")),
                        _safe_float(t.get("priceChangePercent")),
                        _safe_float(t.get("priceChange")),
                        _safe_float(t.get("volume")),
                        _safe_float(t.get("quoteVolume")),
                        _safe_float(t.get("highPrice")),
                        _safe_float(t.get("lowPrice")),
                        _safe_float(t.get("openPrice")),
                        _safe_float(t.get("prevClosePrice")),
                        now_ms,
                    )
                )

            count = self._persist("crypto", rows)
            elapsed = time.time() - t0
            self._record_meta("crypto", count, None)
            logger.info(
                "[MarketCollector] crypto: %d symbols in %.1fs", count, elapsed
            )
            return count

        except Exception as e:
            logger.error("[MarketCollector] crypto 失败: %s", e, exc_info=True)
            self._record_meta("crypto", 0, str(e))
            return 0

    # ==================== 采集：全部 ====================

    def collect_all(self) -> Dict[str, int]:
        results = {}
        results["cn_stock"] = self.collect_cn_stock()
        results["cn_etf"] = self.collect_cn_etf()
        results["hk_stock"] = self.collect_hk_stock()
        results["us_stock"] = self.collect_us_stock()
        results["crypto"] = self.collect_crypto()
        return results

    # ==================== 持久化 ====================

    def _persist(self, market: str, rows: List[tuple]) -> int:
        if not rows:
            return 0
        with self._write_lock:
            with self._get_conn() as conn:
                conn.execute(
                    "DELETE FROM market_snapshot WHERE market = ?", (market,)
                )
                conn.executemany(
                    """
                    INSERT INTO market_snapshot
                        (market, symbol, name, price, change_percent, change_amount,
                         volume, amount, high, low, open, prev_close, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                return len(rows)

    def _record_meta(self, market: str, count: int, error: Optional[str]):
        now_ms = int(time.time() * 1000)
        self._last_collect[market] = now_ms
        with self._write_lock:
            with self._get_conn() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO market_snapshot_meta
                        (market, last_collected, count, last_error)
                    VALUES (?, ?, ?, ?)
                    """,
                    (market, now_ms, count, error),
                )

    # ==================== L1: 快照 → 日线归档 ====================

    _SNAPSHOT_TO_KLINE_MARKET = {
        "cn_stock": "cn",
        "cn_etf": "cn",
        "hk_stock": "hk",
        "us_stock": "us",
        "crypto": "crypto_binance",
    }

    def archive_daily_from_snapshot(self, snapshot_market: str) -> int:
        if snapshot_market not in self._SNAPSHOT_TO_KLINE_MARKET:
            logger.warning("[MarketCollector] 不支持归档的市场: %s", snapshot_market)
            return 0

        rows = self.get_market_snapshots(snapshot_market)
        if not rows:
            logger.warning("[MarketCollector] %s 无快照可归档", snapshot_market)
            return 0

        from src.services.kline_cache_manager import get_kline_cache_manager

        manager = get_kline_cache_manager()
        kline_market = self._SNAPSHOT_TO_KLINE_MARKET[snapshot_market]
        today_ms = int(
            datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        ) * 1000

        symbol_groups: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            price = row.get("price")
            if price is None or price <= 0:
                continue
            sym = row["symbol"]
            symbol_groups.setdefault(sym, []).append(
                {
                    "timestamp": today_ms,
                    "open": row.get("open") or price,
                    "high": row.get("high") or price,
                    "low": row.get("low") or price,
                    "close": price,
                    "volume": row.get("volume") or 0,
                    "amount": row.get("amount") or 0,
                    "is_complete": True,
                }
            )

        total = 0
        for sym, klines in symbol_groups.items():
            try:
                total += manager.upsert_klines(
                    kline_market, sym, "1d", klines, "snapshot_archive"
                )
            except Exception as e:
                logger.warning("[MarketCollector] 归档 %s 日线失败: %s", sym, e)

        logger.info(
            "[MarketCollector] %s 归档日线: %d symbols", snapshot_market, total
        )
        return total

    def archive_all_daily(self) -> Dict[str, int]:
        results = {}
        for market in self._SNAPSHOT_TO_KLINE_MARKET:
            results[market] = self.archive_daily_from_snapshot(market)
        return results

    # ==================== 读取 ====================

    def get_market_snapshots(self, market: str) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT * FROM market_snapshot WHERE market = ? ORDER BY symbol",
                (market,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_snapshot(self, market: str, symbol: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT * FROM market_snapshot WHERE market = ? AND symbol = ?",
                (market, symbol),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def get_status(self) -> Dict[str, Any]:
        with self._get_conn() as conn:
            cur = conn.execute("SELECT * FROM market_snapshot_meta")
            metas = {r["market"]: dict(r) for r in cur.fetchall()}
            cur2 = conn.execute(
                "SELECT market, COUNT(*) as cnt FROM market_snapshot GROUP BY market"
            )
            counts = {r["market"]: r["cnt"] for r in cur2.fetchall()}
        return {
            market: {
                "count": counts.get(market, 0),
                "last_collected": meta.get("last_collected"),
                "last_error": meta.get("last_error"),
            }
            for market, meta in metas.items()
        }


_collector: Optional[MarketCollector] = None
_collector_lock = threading.Lock()


def get_market_collector(db_path: str = DEFAULT_CACHE_DB) -> MarketCollector:
    global _collector
    if _collector is None or _collector._db_path != db_path:
        with _collector_lock:
            if _collector is None or _collector._db_path != db_path:
                _collector = MarketCollector(db_path)
    return _collector


def _safe_float(val) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        f = float(val)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _pick(row, *names):
    """从行中按列名别名顺序取第一个存在的值（兼容不同市场的列名差异）。"""
    for name in names:
        try:
            if name in row and row[name] is not None:
                return row[name]
        except (TypeError, KeyError):
            continue
    return None
