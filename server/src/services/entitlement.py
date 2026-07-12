# -*- coding: utf-8 -*-
"""
Entitlement service — tier-based permission enforcement.

Provides:
1. EntitlementService: check_market_access, check_interval_access, check_model_access, check_quota
2. FastAPI dependencies: require_market, require_interval, require_model
3. Usage recording helper

Enforcement points:
- Data API endpoints (market, kline) → check market + interval + history depth
- Agent/AI endpoints → check model access
- All client-authenticated requests → check daily quota
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, Request

from src.models.tiers import TierConfig, get_effective_tier, get_tier_config, tier_meets_minimum
from src.repositories.account_repository import get_account_repository

logger = logging.getLogger(__name__)


class EntitlementService:
    """根据账号订阅等级判定请求是否被允许。"""

    def __init__(self):
        self._repo = get_account_repository()

    def _get_tier_for_account(self, account_id: int) -> TierConfig:
        tier_name = self._repo.get_account_tier(account_id)
        return get_effective_tier(tier_name)

    def check_market_access(self, account_id: int, market: str) -> None:
        """检查账号是否有权访问指定市场。无权抛 403。"""
        tier = self._get_tier_for_account(account_id)
        if not tier.allows_market(market):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "market_not_allowed",
                    "message": f"当前订阅等级 ({tier.label}) 不支持市场: {market}",
                    "tier": tier.tier,
                    "required_markets": list(tier.markets),
                },
            )

    def check_interval_access(self, account_id: int, interval: str) -> None:
        """检查账号是否有权访问指定 K 线周期。无权抛 403。"""
        tier = self._get_tier_for_account(account_id)
        if not tier.allows_interval(interval):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "interval_not_allowed",
                    "message": f"当前订阅等级 ({tier.label}) 不支持周期: {interval}",
                    "tier": tier.tier,
                },
            )

    def check_history_depth(self, account_id: int, days: int) -> None:
        """检查请求的历史深度是否在等级允许范围内。超限抛 403。"""
        tier = self._get_tier_for_account(account_id)
        if tier.history_days >= 0 and days > tier.history_days:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "history_depth_exceeded",
                    "message": f"当前订阅等级 ({tier.label}) 最多查看 {tier.history_days} 天历史数据",
                    "tier": tier.tier,
                    "max_days": tier.history_days,
                },
            )

    def check_model_access(self, account_id: int, model: str) -> None:
        """检查账号是否有权使用指定 AI 模型。无权抛 403。"""
        tier = self._get_tier_for_account(account_id)
        if not tier.allows_model(model):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "model_not_allowed",
                    "message": f"当前订阅等级 ({tier.label}) 不支持模型: {model}",
                    "tier": tier.tier,
                    "allowed_models": list(tier.models),
                },
            )

    def check_daily_quota(self, account_id: int) -> None:
        """检查账号今日请求是否超过配额。超限抛 402。"""
        tier = self._get_tier_for_account(account_id)
        if tier.daily_quota < 0:
            return
        usage = self._repo.get_usage_summary(account_id, days=1)
        if usage["today_requests"] >= tier.daily_quota:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "quota_exceeded",
                    "message": f"今日请求配额 ({tier.daily_quota}) 已用尽",
                    "tier": tier.tier,
                    "daily_quota": tier.daily_quota,
                    "used": usage["today_requests"],
                },
            )

    def check_feature(self, account_id: int, feature: str) -> None:
        """检查账号是否拥有指定功能标识。无权抛 403。"""
        tier = self._get_tier_for_account(account_id)
        if not tier.has_feature(feature):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "feature_not_allowed",
                    "message": f"当前订阅等级 ({tier.label}) 不支持功能: {feature}",
                    "tier": tier.tier,
                },
            )

    def check_code_execution_access(self, account_id: int, today_usage: int = 0) -> None:
        """检查账号是否有权执行代码（Phase B 沙箱）。

        依次校验:
        1. 功能标识 ``code_execution`` — FREE 版无此功能
        2. 每日代码执行配额 ``code_execution_daily_quota`` — PRO 50次/天，ENTERPRISE 无限

        Args:
            account_id: 客户端账号 ID
            today_usage: 今日已执行次数（由调用方从 code_execution_log 表统计）

        Raises:
            HTTPException: 403 (功能不可用) 或 402 (配额用尽)
        """
        tier = self._get_tier_for_account(account_id)

        # 1. 功能检查 — FREE 版没有 code_execution feature
        if not tier.has_feature("code_execution"):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "feature_not_allowed",
                    "message": f"当前订阅等级 ({tier.label}) 不支持代码执行功能，请升级至专业版或企业版",
                    "tier": tier.tier,
                    "required_feature": "code_execution",
                },
            )

        # 2. 配额检查 (-1 = 无限)
        if tier.code_execution_daily_quota >= 0 and today_usage >= tier.code_execution_daily_quota:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "code_execution_quota_exceeded",
                    "message": f"今日代码执行配额 ({tier.code_execution_daily_quota}) 已用尽",
                    "tier": tier.tier,
                    "daily_quota": tier.code_execution_daily_quota,
                    "used": today_usage,
                },
            )

    def get_entitlements(self, account_id: int) -> dict:
        """返回账号当前权限矩阵。"""
        tier = self._get_tier_for_account(account_id)
        return {
            "tier": tier.tier,
            "label": tier.label,
            "markets": sorted(tier.markets),
            "intervals": sorted(tier.intervals),
            "history_days": tier.history_days,
            "models": sorted(tier.models),
            "qps": tier.qps,
            "daily_quota": tier.daily_quota,
            "features": sorted(tier.features),
            "code_execution_daily_quota": tier.code_execution_daily_quota,
        }


# ==================== 单例 ====================

_entitlement_instance: Optional[EntitlementService] = None


def get_entitlement_service() -> EntitlementService:
    global _entitlement_instance
    if _entitlement_instance is None:
        _entitlement_instance = EntitlementService()
    return _entitlement_instance


# ==================== FastAPI 依赖 ====================

def _get_client_account_id(request: Request) -> Optional[int]:
    """从 request.state 获取客户端账号 ID（由 AuthMiddleware 设置）。"""
    account = getattr(request.state, "client_account", None)
    if account is None:
        return None
    return account.id


def require_market(market: str):
    """
    FastAPI 依赖：检查客户端是否有权访问指定市场。

    用法:
        @router.get("/kline/{market}")
        async def get_kline(market: str, request: Request, _=Depends(require_market("cn"))):
            ...
    """
    def _check(request: Request):
        account_id = _get_client_account_id(request)
        if account_id is None:
            return  # 客户端鉴权未启用，跳过
        svc = get_entitlement_service()
        svc.check_market_access(account_id, market)
    return _check


def require_interval(interval: str):
    """FastAPI 依赖：检查客户端是否有权访问指定 K 线周期。"""
    def _check(request: Request):
        account_id = _get_client_account_id(request)
        if account_id is None:
            return
        svc = get_entitlement_service()
        svc.check_interval_access(account_id, interval)
    return _check


def require_model(model: str):
    """FastAPI 依赖：检查客户端是否有权使用指定 AI 模型。"""
    def _check(request: Request):
        account_id = _get_client_account_id(request)
        if account_id is None:
            return
        svc = get_entitlement_service()
        svc.check_model_access(account_id, model)
    return _check


def require_feature(feature: str):
    """FastAPI 依赖：检查客户端是否拥有指定功能。"""
    def _check(request: Request):
        account_id = _get_client_account_id(request)
        if account_id is None:
            return
        svc = get_entitlement_service()
        svc.check_feature(account_id, feature)
    return _check


def require_code_execution():
    """FastAPI 依赖：检查客户端是否有权执行代码（Phase B 沙箱）。

    校验: 功能标识 code_execution + 每日配额（基于 code_execution_log 表统计）。
    客户端鉴权未启用时自动跳过（内网免登录模式零影响）。
    """
    def _check(request: Request):
        account_id = _get_client_account_id(request)
        if account_id is None:
            return  # 客户端鉴权未启用，跳过

        # 统计今日代码执行次数
        today_usage = 0
        try:
            import sqlite3
            from datetime import datetime, timezone
            from src.services.kline_cache_manager import DEFAULT_CACHE_DB
            today_start = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            conn = sqlite3.connect(DEFAULT_CACHE_DB, timeout=3)
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM code_execution_log WHERE executed_at >= ?",
                    (today_start,),
                ).fetchone()
                today_usage = row[0] if row else 0
            finally:
                conn.close()
        except Exception:
            # 表不存在或 DB 不可用 — 当作 0 次（保守放行，首次调用时表尚未创建）
            today_usage = 0

        svc = get_entitlement_service()
        svc.check_code_execution_access(account_id, today_usage=today_usage)
    return _check


def check_client_quota(request: Request) -> None:
    """
    通用配额检查依赖 —— 在数据 API 端点调用。
    如果客户端鉴权启用且有账号，检查配额；否则跳过。
    """
    account_id = _get_client_account_id(request)
    if account_id is None:
        return
    svc = get_entitlement_service()
    svc.check_daily_quota(account_id)


# ==================== 端点标识 → tier 标识 归一化 ====================
#
# 数据端点对外使用 cn_stock / hk_stock / us_stock / crypto 等市场标识，
# 以及 1/5/60/daily 等周期标识；而 TierConfig 使用 cn/hk/us/crypto_binance
# 和 1m/5m/1h/1d 等标识。下列映射负责将端点入参归一化到 tier 标识，
# 以便 EntitlementService 正确判定权限。

_MARKET_TYPE_TO_TIER_KEY = {
    "cn_stock": "cn",
    "cn_etf": "cn",
    "cn_index": "cn",
    "cn_futures": "cn",
    "hk_stock": "hk",
    "us_stock": "us",
    "us_index": "us",
    "crypto": "crypto_binance",
    # 已是 tier 标识则原样透传
    "cn": "cn",
    "hk": "hk",
    "us": "us",
    "crypto_binance": "crypto_binance",
}

_PERIOD_TO_TIER_INTERVAL = {
    "1": "1m", "5": "5m", "15": "15m", "30": "30m", "60": "1h",
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w",
    "daily": "1d", "weekly": "1w",
}

_ALL_TIER_INTERVALS = frozenset({"1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"})


def normalize_market_key(market_type: Optional[str]) -> Optional[str]:
    """端点市场标识 → tier 市场标识。未知或空返回 None（不拦截）。"""
    if not market_type:
        return None
    return _MARKET_TYPE_TO_TIER_KEY.get(market_type)


def normalize_interval_key(period: Optional[str]) -> Optional[str]:
    """端点周期标识 → tier 周期标识。未知（如月线 1M）返回 None（不拦截）。"""
    if not period:
        return None
    return _PERIOD_TO_TIER_INTERVAL.get(str(period))


def enforce_data_request(
    request: Request,
    *,
    market_type: Optional[str] = None,
    period: Optional[str] = None,
    history_days: Optional[int] = None,
    check_quota: bool = True,
) -> None:
    """
    统一的数据端点准入检查（在端点函数体内调用，支持运行时推断出的市场/周期）。

    依次校验：每日配额（402）→ 市场访问（403）→ 周期访问（403）→ 历史深度（403）。
    客户端鉴权未启用或请求无客户端账号时**自动跳过**，因此内网免登录模式零影响。
    映射不到 tier 标识的市场/周期不拦截（保守放行，避免误伤）。
    """
    account_id = _get_client_account_id(request)
    if account_id is None:
        return
    svc = get_entitlement_service()
    if check_quota:
        svc.check_daily_quota(account_id)
    market_key = normalize_market_key(market_type)
    if market_key:
        svc.check_market_access(account_id, market_key)
    interval_key = normalize_interval_key(period)
    if interval_key and interval_key in _ALL_TIER_INTERVALS:
        svc.check_interval_access(account_id, interval_key)
    if history_days is not None and history_days > 0:
        svc.check_history_depth(account_id, history_days)


def record_api_usage(
    request: Request,
    endpoint: str,
    method: str,
    market: Optional[str] = None,
    model_used: Optional[str] = None,
    tokens_consumed: int = 0,
) -> None:
    """记录 API 用量（fire-and-forget）。仅对客户端账号生效。"""
    account_id = _get_client_account_id(request)
    if account_id is None:
        return
    try:
        repo = get_account_repository()
        repo.record_usage(
            account_id=account_id,
            endpoint=endpoint,
            method=method,
            market=market,
            model_used=model_used,
            tokens_consumed=tokens_consumed,
        )
    except Exception as e:
        logger.warning("[Entitlement] Failed to record usage: %s", e)
