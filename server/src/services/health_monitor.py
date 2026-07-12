# -*- coding: utf-8 -*-
"""
Health monitoring service.

Aggregates health signals from across the system into a single snapshot:
- Scheduler task catch-up status (last_success lag, failures)
- Collector staleness (snapshot freshness per market)
- Write queue health (failure rate, depth)
- Disk usage thresholds
- Data source failure tracking (in-memory ring buffer)

Exposes a single ``get_health_snapshot()`` method consumed by the
``GET /api/v1/admin/health`` endpoint and structured JSON logs.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================================
# Thresholds (overridable via env for different deployments)
# ============================================================

_DEFAULT_LAG_CRITICAL_HOURS = 26
_DEFAULT_LAG_WARNING_HOURS = 2
_DEFAULT_DISK_CRITICAL_PCT = 90
_DEFAULT_DISK_WARNING_PCT = 80
_DEFAULT_QUEUE_FAILURE_RATE_CRITICAL = 0.1
_DEFAULT_DATA_SOURCE_MEMORY = 200


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


LAG_CRITICAL_HOURS = _env_int("HEALTH_LAG_CRITICAL_HOURS", _DEFAULT_LAG_CRITICAL_HOURS)
LAG_WARNING_HOURS = _env_int("HEALTH_LAG_WARNING_HOURS", _DEFAULT_LAG_WARNING_HOURS)
DISK_CRITICAL_PCT = _env_int("HEALTH_DISK_CRITICAL_PCT", _DEFAULT_DISK_CRITICAL_PCT)
DISK_WARNING_PCT = _env_int("HEALTH_DISK_WARNING_PCT", _DEFAULT_DISK_WARNING_PCT)
QUEUE_FAILURE_RATE_CRITICAL = float(
    os.getenv("HEALTH_QUEUE_FAILURE_RATE_CRITICAL", str(_DEFAULT_QUEUE_FAILURE_RATE_CRITICAL))
)
DATA_SOURCE_MEMORY = _env_int("HEALTH_DATA_SOURCE_MEMORY", _DEFAULT_DATA_SOURCE_MEMORY)

# Known scheduler tasks and their expected daily trigger times (CST).
# Used to compute "expected by now" for lag detection.
_EXPECTED_TASK_TIMES: Dict[str, str] = {
    "cn_stock_daily": "15:30",
    "hk_stock_daily": "16:30",
    "crypto_daily": "08:10",
    "symbol_list_refresh": "07:00",
    "db_maintenance": "03:30",
}


@dataclass
class DataSourceFailure:
    """Single data source failure record."""

    source: str
    error: str
    timestamp: float
    market: Optional[str] = None


@dataclass
class _HealthState:
    """In-memory state for health monitoring."""

    data_source_failures: deque = field(
        default_factory=lambda: deque(maxlen=DATA_SOURCE_MEMORY)
    )
    _lock: threading.Lock = field(default_factory=threading.Lock)


_state = _HealthState()


def record_data_source_failure(source: str, error: str, market: Optional[str] = None) -> None:
    """Record a data source failure (called from collectors/fetchers)."""
    entry = DataSourceFailure(
        source=source,
        error=str(error)[:500],
        timestamp=time.time(),
        market=market,
    )
    with _state._lock:
        _state.data_source_failures.append(entry)
    logger.warning(
        "[HealthMonitor] Data source failure recorded: source=%s market=%s error=%s",
        source,
        market,
        error,
    )


def get_recent_data_source_failures(limit: int = 50) -> List[Dict[str, Any]]:
    """Return recent data source failures (newest first)."""
    with _state._lock:
        items = list(_state.data_source_failures)
    items.reverse()
    return [
        {
            "source": f.source,
            "error": f.error,
            "market": f.market,
            "timestamp": datetime.fromtimestamp(f.timestamp).isoformat(),
        }
        for f in items[:limit]
    ]


# ============================================================
# Health check helpers
# ============================================================


def _classify_lag(last_success_ts: Optional[float], expected_time_str: str) -> Dict[str, Any]:
    """Classify scheduler task lag based on last success vs expected daily time."""
    now = time.time()

    if last_success_ts is None:
        return {
            "status": "critical",
            "message": "从未成功运行",
            "lag_hours": None,
        }

    lag_seconds = now - last_success_ts
    lag_hours = lag_seconds / 3600

    # Compute today's expected trigger timestamp
    today = datetime.now().strftime("%Y-%m-%d")
    expected_dt_str = f"{today} {expected_time_str}"
    try:
        expected_ts = datetime.strptime(expected_dt_str, "%Y-%m-%d %H:%M").timestamp()
    except ValueError:
        expected_ts = now

    # If expected time hasn't arrived today yet, and last_success was yesterday or earlier,
    # that's normal (task hasn't been due yet today).
    if now < expected_ts and last_success_ts < expected_ts - 86400:
        # Last success was before yesterday's trigger — stale
        pass

    if lag_hours >= LAG_CRITICAL_HOURS:
        return {
            "status": "critical",
            "message": f"上次成功于 {lag_hours:.1f} 小时前，超过 {LAG_CRITICAL_HOURS}h 阈值",
            "lag_hours": round(lag_hours, 1),
        }
    if lag_hours >= LAG_WARNING_HOURS:
        return {
            "status": "warning",
            "message": f"上次成功于 {lag_hours:.1f} 小时前",
            "lag_hours": round(lag_hours, 1),
        }
    return {
        "status": "healthy",
        "message": f"上次成功于 {lag_hours:.1f} 小时前",
        "lag_hours": round(lag_hours, 1),
    }


def _check_scheduler_tasks(scheduler) -> Dict[str, Any]:
    """Check scheduler task health (catch-up lag + failures)."""
    if scheduler is None:
        return {"status": "unknown", "message": "调度器未启动", "tasks": []}

    try:
        tasks = scheduler.get_task_status()
    except Exception as e:
        return {"status": "critical", "message": f"读取任务状态失败: {e}", "tasks": []}

    task_results: List[Dict[str, Any]] = []
    worst_status = "healthy"

    for t in tasks:
        name = t.get("task_name", "?")
        last_success = t.get("last_success_at")
        last_error = t.get("last_error")
        expected_time = _EXPECTED_TASK_TIMES.get(name, "12:00")

        lag_info = _classify_lag(last_success, expected_time)

        # If last_error present and last_run > last_success, task is failing
        if last_error and last_success is not None and t.get("last_run_at", 0) > last_success:
            lag_info = {
                **lag_info,
                "status": "critical",
                "message": f"最近一次运行失败: {last_error[:200]}",
            }

        status = lag_info["status"]
        if status == "critical":
            worst_status = "critical"
        elif status == "warning" and worst_status != "critical":
            worst_status = "warning"

        task_results.append(
            {
                "name": name,
                "status": status,
                "message": lag_info["message"],
                "last_success_at": (
                    datetime.fromtimestamp(last_success).isoformat() if last_success else None
                ),
                "last_error": last_error,
                "last_duration": t.get("last_duration"),
                "last_count": t.get("last_count"),
            }
        )

    return {
        "status": worst_status,
        "message": f"{len(task_results)} 个任务，状态: {worst_status}",
        "tasks": task_results,
    }


def _check_collector_freshness() -> Dict[str, Any]:
    """Check market snapshot collector freshness."""
    try:
        from src.services.market_collector import get_market_collector

        status = get_market_collector().get_status()
    except Exception as e:
        return {"status": "unknown", "message": f"采集器状态不可用: {e}", "markets": []}

    if not status:
        return {"status": "unknown", "message": "无采集数据", "markets": []}

    market_results: List[Dict[str, Any]] = []
    worst_status = "healthy"
    now = time.time()

    for market, info in status.items():
        last_collected = info.get("last_collected")
        last_error = info.get("last_error")
        count = info.get("count", 0)

        if last_error and not last_collected:
            mkt_status = "critical"
            msg = f"采集失败: {last_error[:150]}"
        elif not last_collected:
            mkt_status = "unknown"
            msg = "从未采集"
        else:
            try:
                ts = datetime.fromisoformat(last_collected).timestamp()
                age_hours = (now - ts) / 3600
                if age_hours >= LAG_CRITICAL_HOURS:
                    mkt_status = "critical"
                    msg = f"数据陈旧: {age_hours:.1f}h 前采集"
                elif age_hours >= LAG_WARNING_HOURS:
                    mkt_status = "warning"
                    msg = f"数据较旧: {age_hours:.1f}h 前采集"
                else:
                    mkt_status = "healthy"
                    msg = f"{age_hours:.1f}h 前采集，{count} 条"
            except (ValueError, TypeError):
                mkt_status = "unknown"
                msg = f"时间格式异常: {last_collected}"

        if mkt_status == "critical":
            worst_status = "critical"
        elif mkt_status == "warning" and worst_status != "critical":
            worst_status = "warning"

        market_results.append(
            {
                "market": market,
                "status": mkt_status,
                "message": msg,
                "count": count,
                "last_collected": last_collected,
                "last_error": last_error,
            }
        )

    return {
        "status": worst_status,
        "message": f"{len(market_results)} 个市场，状态: {worst_status}",
        "markets": market_results,
    }


def _check_write_queue() -> Dict[str, Any]:
    """Check DB write queue health."""
    try:
        from src.services.db_write_queue import get_db_write_queue

        q = get_db_write_queue()
        m = q.metrics
    except Exception as e:
        return {"status": "unknown", "message": f"写队列状态不可用: {e}"}

    total = m.total_enqueued or 0
    failed = m.total_failed or 0
    depth = m.current_depth or 0

    if total == 0:
        return {"status": "healthy", "message": "无写入活动", "metrics": _queue_metrics_dict(m)}

    failure_rate = failed / total if total > 0 else 0

    if failure_rate >= QUEUE_FAILURE_RATE_CRITICAL and failed > 0:
        status = "critical"
        msg = f"失败率 {failure_rate:.1%} 超阈值 {QUEUE_FAILURE_RATE_CRITICAL:.0%}"
    elif depth > 100:
        status = "warning"
        msg = f"队列积压 {depth} 条"
    elif m.last_error and failed > 0:
        status = "warning"
        msg = f"最近有失败: {m.last_error[:100]}"
    else:
        status = "healthy"
        msg = f"正常 (入队 {total}, 完成 {m.total_completed}, 失败 {failed})"

    return {
        "status": status,
        "message": msg,
        "metrics": _queue_metrics_dict(m),
    }


def _queue_metrics_dict(m) -> Dict[str, Any]:
    return {
        "total_enqueued": m.total_enqueued,
        "total_completed": m.total_completed,
        "total_failed": m.total_failed,
        "total_retries": m.total_retries,
        "current_depth": m.current_depth,
        "last_error": m.last_error,
    }


def _check_disk_usage() -> Dict[str, Any]:
    """Check disk usage against thresholds."""
    try:
        from src.services.cache_maintenance import get_cache_maintenance

        usage = get_cache_maintenance().get_disk_usage()
    except Exception as e:
        return {"status": "unknown", "message": f"磁盘状态不可用: {e}"}

    pct = usage.get("usage_percent", 0)
    if isinstance(pct, str):
        try:
            pct = float(pct.rstrip("%"))
        except ValueError:
            pct = 0

    if pct >= DISK_CRITICAL_PCT:
        status = "critical"
        msg = f"磁盘使用 {pct:.1f}% 超临界值 {DISK_CRITICAL_PCT}%"
    elif pct >= DISK_WARNING_PCT:
        status = "warning"
        msg = f"磁盘使用 {pct:.1f}% 超警告值 {DISK_WARNING_PCT}%"
    else:
        status = "healthy"
        msg = f"磁盘使用 {pct:.1f}%"

    return {"status": status, "message": msg, "usage": usage}


def _check_data_source_failures() -> Dict[str, Any]:
    """Summarize recent data source failures."""
    with _state._lock:
        total = len(_state.data_source_failures)

    # Count failures in last hour
    one_hour_ago = time.time() - 3600
    with _state._lock:
        recent_count = sum(1 for f in _state.data_source_failures if f.timestamp > one_hour_ago)

    if recent_count >= 10:
        status = "critical"
        msg = f"过去1小时 {recent_count} 次数据源失败"
    elif recent_count >= 3:
        status = "warning"
        msg = f"过去1小时 {recent_count} 次数据源失败"
    elif total > 0:
        status = "healthy"
        msg = f"累计记录 {total} 次失败，过去1小时 {recent_count} 次"
    else:
        status = "healthy"
        msg = "无数据源失败记录"

    return {
        "status": status,
        "message": msg,
        "recent_failures": get_recent_data_source_failures(limit=10),
    }


# ============================================================
# Aggregate snapshot
# ============================================================


def get_health_snapshot(scheduler=None) -> Dict[str, Any]:
    """
    Build a complete health snapshot.

    Args:
        scheduler: Optional Scheduler instance (for task lag checks).

    Returns:
        Dict with overall status + per-component details.
    """
    components = {
        "scheduler": _check_scheduler_tasks(scheduler),
        "collector": _check_collector_freshness(),
        "write_queue": _check_write_queue(),
        "disk": _check_disk_usage(),
        "data_sources": _check_data_source_failures(),
    }

    # Aggregate overall status
    statuses = [c["status"] for c in components.values()]
    if "critical" in statuses:
        overall = "critical"
    elif "warning" in statuses:
        overall = "warning"
    elif "unknown" in statuses:
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "status": overall,
        "timestamp": datetime.now().isoformat(),
        "components": components,
    }
