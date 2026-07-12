# -*- coding: utf-8 -*-
"""
Subscription tier definitions — permission matrix per tier.

Each tier defines: allowed markets, data intervals, history depth (days),
allowed AI models, and QPS / quota limits.

Tiers: free < pro < enterprise
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Optional


@dataclass(frozen=True)
class TierConfig:
    """一个订阅等级的权限矩阵。"""

    tier: str
    label: str
    markets: FrozenSet[str]  # cn, hk, us, crypto_binance
    intervals: FrozenSet[str]  # 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w
    history_days: int  # 最大历史深度（天），-1 = 无限
    models: FrozenSet[str]  # 允许使用的 AI 模型标识
    qps: int  # 每秒最大请求数
    daily_quota: int  # 每日请求配额，-1 = 无限
    features: FrozenSet[str] = field(default_factory=frozenset)  # 额外功能标识
    code_execution_daily_quota: int = 0  # 每日代码执行配额，0 = 不允许，-1 = 无限

    def allows_market(self, market: str) -> bool:
        return market in self.markets

    def allows_interval(self, interval: str) -> bool:
        return interval in self.intervals

    def allows_model(self, model: str) -> bool:
        return model in self.models

    def has_feature(self, feature: str) -> bool:
        return feature in self.features


# ==================== 等级定义 ====================

FREE = TierConfig(
    tier="free",
    label="免费版",
    markets=frozenset({"cn"}),
    intervals=frozenset({"1d", "1w"}),
    history_days=30,
    models=frozenset(),  # 免费版不可使用 AI 模型
    qps=5,
    daily_quota=100,
    features=frozenset({"basic_chart"}),
)

PRO = TierConfig(
    tier="pro",
    label="专业版",
    markets=frozenset({"cn", "hk", "us", "crypto_binance"}),
    intervals=frozenset({"1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"}),
    history_days=365,
    models=frozenset({"standard", "deepseek", "qwen"}),
    qps=30,
    daily_quota=5000,
    features=frozenset({"basic_chart", "ai_analysis", "backtest", "code_execution"}),
    code_execution_daily_quota=50,  # Phase B: 每日代码执行 50 次
)

ENTERPRISE = TierConfig(
    tier="enterprise",
    label="企业版",
    markets=frozenset({"cn", "hk", "us", "crypto_binance"}),
    intervals=frozenset({"1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"}),
    history_days=-1,  # 无限
    models=frozenset({"standard", "deepseek", "qwen", "gpt4", "claude"}),
    qps=100,
    daily_quota=-1,  # 无限
    features=frozenset({"basic_chart", "ai_analysis", "backtest", "multi_portfolio", "api_access", "priority_support", "code_execution"}),
    code_execution_daily_quota=-1,  # Phase B: 无限
)

# ==================== 等级注册表 ====================

TIERS: dict[str, TierConfig] = {
    "free": FREE,
    "pro": PRO,
    "enterprise": ENTERPRISE,
}

# 等级排序（用于比较）
TIER_ORDER: dict[str, int] = {
    "free": 0,
    "pro": 1,
    "enterprise": 2,
}


def get_tier_config(tier: str) -> Optional[TierConfig]:
    """获取等级配置，未知等级返回 None。"""
    return TIERS.get(tier)


def tier_meets_minimum(actual: str, required: str) -> bool:
    """判断 actual 等级是否 >= required 等级。"""
    return TIER_ORDER.get(actual, -1) >= TIER_ORDER.get(required, -1)


def get_effective_tier(tier: Optional[str]) -> TierConfig:
    """
    获取生效的等级配置。
    无订阅或未知等级按 free 处理。
    """
    if tier and tier in TIERS:
        return TIERS[tier]
    return FREE
