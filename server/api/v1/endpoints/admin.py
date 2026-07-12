# -*- coding: utf-8 -*-
"""
Admin management endpoints.
Provides service status, client monitoring, and manual task triggers.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger(__name__)
router = APIRouter()

_PROCESS_START_TIME = time.time()


@router.get(
    "/status",
    summary="Get full service status",
    description="Process info, datasource health, collector/scheduler/WS relay status, cache metrics.",
)
async def get_admin_status(request: Request):
    uptime_seconds = int(time.time() - _PROCESS_START_TIME)

    ws_status: Dict[str, Any] = {}
    try:
        ws_relay = getattr(request.app.state, "ws_relay", None)
        if ws_relay:
            ws_status = ws_relay.get_status()
    except Exception as e:
        ws_status = {"error": str(e)}

    scheduler_status: Dict[str, Any] = {}
    try:
        scheduler = getattr(request.app.state, "scheduler", None)
        if scheduler:
            scheduler_status = {"tasks": scheduler.get_task_status()}
        else:
            scheduler_status = {"tasks": [], "note": "scheduler not started"}
    except Exception as e:
        scheduler_status = {"error": str(e)}

    collector_status: Dict[str, Any] = {}
    try:
        from src.services.market_collector import get_market_collector
        collector_status = get_market_collector().get_status()
    except Exception as e:
        collector_status = {"error": str(e)}

    cache_metrics: Dict[str, Any] = {}
    try:
        from src.services.market_gateway import MarketGateway
        cache_metrics = MarketGateway().get_cache_metrics()
    except Exception as e:
        cache_metrics = {"error": str(e)}

    disk_usage: Dict[str, Any] = {}
    try:
        from src.services.cache_maintenance import get_cache_maintenance
        disk_usage = get_cache_maintenance().get_disk_usage()
    except Exception as e:
        disk_usage = {"error": str(e)}

    write_queue_metrics: Dict[str, Any] = {}
    try:
        from src.services.db_write_queue import get_db_write_queue
        q = get_db_write_queue()
        m = q.metrics
        write_queue_metrics = {
            "total_enqueued": m.total_enqueued,
            "total_completed": m.total_completed,
            "total_failed": m.total_failed,
            "total_retries": m.total_retries,
            "current_depth": m.current_depth,
            "last_error": m.last_error,
        }
    except Exception as e:
        write_queue_metrics = {"error": str(e)}

    version = "1.0.0"
    try:
        import importlib.metadata
        version = importlib.metadata.version("dsa-server") or "1.0.0"
    except Exception:
        pass

    return {
        "process": {
            "uptime_seconds": uptime_seconds,
            "started_at": datetime.fromtimestamp(_PROCESS_START_TIME).isoformat(),
            "python_version": sys.version.split()[0],
            "pid": os.getpid(),
            "version": version,
        },
        "ws_relay": ws_status,
        "scheduler": scheduler_status,
        "collector": collector_status,
        "cache_metrics": cache_metrics,
        "disk_usage": disk_usage,
        "write_queue": write_queue_metrics,
    }


@router.get(
    "/clients",
    summary="List active client connections",
    description="Active WebSocket connections and recent REST API callers.",
)
async def get_admin_clients(request: Request):
    ws_clients: List[Dict[str, Any]] = []
    try:
        ws_relay = getattr(request.app.state, "ws_relay", None)
        if ws_relay:
            ws_clients = _extract_ws_clients(ws_relay)
    except Exception as e:
        logger.warning("[AdminAPI] WS client extraction failed: %s", e)

    recent_rest: List[Dict[str, Any]] = []
    try:
        recent_rest = _get_recent_rest_clients(request)
    except Exception as e:
        logger.warning("[AdminAPI] REST client extraction failed: %s", e)

    return {
        "ws_clients": ws_clients,
        "ws_client_count": len(ws_clients),
        "recent_rest_clients": recent_rest,
    }


def _extract_ws_clients(ws_relay) -> List[Dict[str, Any]]:
    clients = []
    for ws in list(getattr(ws_relay, "_clients", set())):
        info: Dict[str, Any] = {"state": getattr(ws, "state", "unknown")}
        try:
            client = getattr(ws, "client", None)
            if client:
                info["ip"] = client.host or "unknown"
            else:
                info["ip"] = "unknown"
        except Exception:
            info["ip"] = "unknown"

        subs = getattr(ws_relay, "_subscriptions", {}).get(ws, {})
        info["subscribed_quotes"] = len(subs.get("quotes", set()))
        info["subscribed_depth"] = len(subs.get("depth", set()))
        info["subscribed_symbols"] = sorted(
            list(subs.get("quotes", set()))[:20]
        )
        clients.append(info)
    return clients


def _get_recent_rest_clients(request: Request) -> List[Dict[str, Any]]:
    tracker = getattr(request.app.state, "rest_client_tracker", None)
    if tracker is None:
        return []
    return tracker.get_recent()


@router.post(
    "/scheduler/trigger/{task_name}",
    summary="Manually trigger a scheduler task",
    description="Run a named scheduler task immediately (async, returns immediately).",
)
async def trigger_scheduler_task(
    task_name: str,
    request: Request,
):
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not started")

    named_jobs = getattr(scheduler, "_named_jobs", {})
    entry = named_jobs.get(task_name)
    if entry is None:
        available = list(named_jobs.keys())
        raise HTTPException(
            status_code=404,
            detail=f"Task '{task_name}' not found. Available: {available}",
        )

    import asyncio
    task_fn = entry["task"]

    async def _run():
        try:
            result = task_fn()
            if asyncio.iscoroutine(result):
                await result
            logger.info("[AdminAPI] Manual trigger '%s' completed", task_name)
        except Exception as e:
            logger.error("[AdminAPI] Manual trigger '%s' failed: %s", task_name, e, exc_info=True)

    asyncio.ensure_future(_run())
    return {"task": task_name, "status": "triggered"}


@router.post(
    "/collector/collect/{market}",
    summary="Manually trigger market snapshot collection",
    description="Collect a single market's snapshot immediately.",
)
async def trigger_collection(market: str):
    from src.services.market_collector import get_market_collector
    collector = get_market_collector()

    methods = {
        "cn_stock": collector.collect_cn_stock,
        "cn_etf": collector.collect_cn_etf,
        "hk_stock": collector.collect_hk_stock,
        "us_stock": collector.collect_us_stock,
        "crypto": collector.collect_crypto,
        "all": collector.collect_all,
    }
    fn = methods.get(market)
    if fn is None:
        raise HTTPException(
            status_code=404,
            detail=f"Market '{market}' not supported. Available: {list(methods.keys())}",
        )
    result = fn()
    return {"market": market, "collected": result}


@router.post(
    "/collector/archive/{market}",
    summary="Archive daily klines from snapshot",
    description="Convert latest snapshot to 1d klines and upsert to kline_data.",
)
async def trigger_archive(market: str):
    from src.services.market_collector import get_market_collector
    collector = get_market_collector()
    count = collector.archive_daily_from_snapshot(market)
    return {"market": market, "archived": count}


@router.post(
    "/maintenance/run",
    summary="Run cache maintenance",
    description="Clean expired klines, purge old task logs, VACUUM.",
)
async def trigger_maintenance():
    from src.services.cache_maintenance import get_cache_maintenance
    return get_cache_maintenance().run_full_cleanup()


# ==================== 账号管理 (Phase 5) ====================

from pydantic import BaseModel, Field as PydField


class CreateAccountRequest(BaseModel):
    model_config = {"populate_by_name": True}
    email: str
    password: str
    role: str = PydField(default="user")
    display_name: str | None = PydField(default=None, alias="displayName")


class UpdateAccountRequest(BaseModel):
    model_config = {"populate_by_name": True}
    password: str | None = None
    role: str | None = None
    status: str | None = None
    display_name: str | None = PydField(default=None, alias="displayName")


class GrantSubscriptionRequest(BaseModel):
    model_config = {"populate_by_name": True}
    tier: str
    duration_days: int | None = PydField(default=None, alias="durationDays")


@router.get("/accounts", summary="List all accounts")
async def list_accounts(offset: int = 0, limit: int = Query(default=100, le=500)):
    from src.repositories.account_repository import get_account_repository
    repo = get_account_repository()
    accounts = repo.list_accounts(offset=offset, limit=limit)
    result = []
    for acc in accounts:
        d = acc.to_dict()
        d["tier"] = repo.get_account_tier(acc.id)
        result.append(d)
    return {"accounts": result, "count": len(result)}


@router.post("/accounts", summary="Create account")
async def create_account(body: CreateAccountRequest):
    from src.repositories.account_repository import get_account_repository
    repo = get_account_repository()
    try:
        account = repo.create_account(
            email=body.email,
            password=body.password,
            role=body.role,
            display_name=body.display_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return account.to_dict()


@router.put("/accounts/{account_id}", summary="Update account")
async def update_account(account_id: int, body: UpdateAccountRequest):
    from src.repositories.account_repository import get_account_repository
    repo = get_account_repository()
    kwargs = {}
    if body.password:
        kwargs["password"] = body.password
    if body.role:
        kwargs["role"] = body.role
    if body.status:
        kwargs["status"] = body.status
    if body.display_name is not None:
        kwargs["display_name"] = body.display_name
    account = repo.update_account(account_id, **kwargs)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account.to_dict()


@router.delete("/accounts/{account_id}", summary="Delete account")
async def delete_account(account_id: int):
    from src.repositories.account_repository import get_account_repository
    repo = get_account_repository()
    if not repo.delete_account(account_id):
        raise HTTPException(status_code=404, detail="Account not found")
    return {"ok": True}


@router.get("/accounts/{account_id}/subscriptions", summary="List account subscriptions")
async def list_subscriptions(account_id: int):
    from src.repositories.account_repository import get_account_repository
    repo = get_account_repository()
    subs = repo.list_subscriptions(account_id)
    return {"subscriptions": [s.to_dict() for s in subs]}


@router.post("/accounts/{account_id}/subscriptions", summary="Grant subscription")
async def grant_subscription(account_id: int, body: GrantSubscriptionRequest):
    from src.repositories.account_repository import get_account_repository
    repo = get_account_repository()
    try:
        sub = repo.grant_subscription(
            account_id=account_id,
            tier=body.tier,
            duration_days=body.duration_days,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return sub.to_dict()


@router.get("/accounts/{account_id}/tokens", summary="List account tokens")
async def list_tokens(account_id: int):
    from src.repositories.account_repository import get_account_repository
    repo = get_account_repository()
    tokens = repo.list_tokens(account_id, include_revoked=True)
    return {"tokens": [t.to_dict() for t in tokens]}


@router.post("/accounts/{account_id}/tokens/revoke-all", summary="Revoke all tokens")
async def revoke_all_tokens(account_id: int):
    from src.repositories.account_repository import get_account_repository
    repo = get_account_repository()
    count = repo.revoke_all_tokens(account_id)
    return {"revoked": count}


@router.delete("/tokens/{token_id}", summary="Revoke single token")
async def revoke_token(token_id: int):
    from src.repositories.account_repository import get_account_repository
    repo = get_account_repository()
    if not repo.revoke_token(token_id):
        raise HTTPException(status_code=404, detail="Token not found")
    return {"ok": True}


@router.get("/accounts/{account_id}/usage", summary="Get account usage summary")
async def get_account_usage(account_id: int, days: int = Query(default=30, le=365)):
    from src.repositories.account_repository import get_account_repository
    repo = get_account_repository()
    return repo.get_usage_summary(account_id, days=days)


@router.get("/accounts/{account_id}/entitlements", summary="Get account entitlements")
async def get_account_entitlements(account_id: int):
    from src.services.entitlement import get_entitlement_service
    svc = get_entitlement_service()
    return svc.get_entitlements(account_id)


# ==================== 决策复盘 (Phase D.5) ====================


@router.get(
    "/decisions",
    summary="List recent decision logs for review",
    description="决策复盘卡片：展示决策历史 + 自动验证结果，支持按账户/股票过滤。",
)
async def list_decision_logs(
    account_id: Optional[int] = Query(default=None),
    stock_code: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    from src.storage import get_db

    db = get_db()
    items = db.list_recent_decision_logs(
        account_id=account_id,
        stock_code=stock_code,
        limit=limit,
        offset=offset,
    )
    total = db.count_decision_logs(account_id=account_id, stock_code=stock_code)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get(
    "/decisions/{decision_id}/feedback",
    summary="List feedback for a decision",
    description="展示某条决策收到的所有用户/管理员反馈。",
)
async def list_decision_feedback(decision_id: int):
    from src.storage import get_db

    return {"items": get_db().get_decision_feedback(decision_id)}


@router.post(
    "/decisions/{decision_id}/feedback",
    summary="Admin annotates a decision's outcome",
    description="管理员为决策补充执行情况与实际结果反馈。",
)
async def admin_annotate_decision(
    decision_id: int,
    execution_status: str = Query(..., description="executed / not_executed / partial"),
    user_outcome: Optional[str] = Query(default=None, description="profit / loss / breakeven / pending"),
    user_return_pct: Optional[float] = Query(default=None),
    notes: Optional[str] = Query(default=None),
):
    from src.storage import get_db

    fb_id = get_db().add_decision_feedback(
        decision_log_id=decision_id,
        execution_status=execution_status,
        user_outcome=user_outcome,
        user_return_pct=user_return_pct,
        notes=notes,
        source="admin",
    )
    return {"success": True, "feedback_id": fb_id}


@router.get(
    "/skill-stats",
    summary="Skill win-rate statistics",
    description="各策略的历史胜率与收益统计（用于策略权重学习复盘）。",
)
async def get_skill_stats_summary(lookback_days: int = Query(default=90, le=365)):
    from src.agent.reflection.service import ReflectionService
    from src.agent.reflection.repository import ReflectionRepository
    from src.storage import DatabaseManager
    from src.agent.skills.base import SkillRegistry

    db = DatabaseManager.get_instance()
    repo = ReflectionRepository(db.session_scope)
    service = ReflectionService(repo)

    registry = SkillRegistry()
    try:
        registry.load_builtin_skills()
    except Exception:
        pass

    stats: List[Dict[str, Any]] = []
    for skill in registry.list_skills():
        s = service.get_skill_stats(skill.name, lookback_days=lookback_days)
        s["skill_name"] = skill.display_name or skill.name
        s["enabled"] = skill.enabled
        stats.append(s)

    # 按 total_calls 降序，便于先看到高频策略
    stats.sort(key=lambda x: x.get("total_calls", 0), reverse=True)
    return {"items": stats, "lookback_days": lookback_days}


# ==================== 健康监控 (Phase 6.2) ====================


@router.get(
    "/health",
    summary="Get aggregated health snapshot",
    description="Collection lag, data source failures, scheduler health, disk/write-queue status.",
)
async def get_admin_health(request: Request):
    from src.services.health_monitor import get_health_snapshot

    scheduler = getattr(request.app.state, "scheduler", None)
    return get_health_snapshot(scheduler=scheduler)
