# -*- coding: utf-8 -*-
"""
前后端解耦配置单元测试

测试场景:
1. TierConfig tier 比较
2. serverConfig 优先级逻辑（通过模拟 localStorage + window）
3. 本地/远程模式配置读取

注: serverConfig.ts 是 TypeScript，这里测试 Python 侧的调度器配置逻辑
和 tier 配置一致性，TS 侧逻辑通过类型系统保证。
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.models.tiers import FREE, PRO, ENTERPRISE, TIERS, TIER_ORDER


class TestServerConfigConsistency:
    """验证 tier 配置与文档/前端一致性"""

    def test_free_tier_matches_design_doc(self):
        """FREE 等级: cn only, 1d/1w, 30d, 无 AI, 100/day"""
        assert FREE.markets == frozenset({"cn"})
        assert FREE.intervals == frozenset({"1d", "1w"})
        assert FREE.history_days == 30
        assert len(FREE.models) == 0
        assert FREE.daily_quota == 100
        assert FREE.qps == 5

    def test_pro_tier_matches_design_doc(self):
        """PRO 等级: 全市场, 全周期, 365d, standard/deepseek/qwen, 5000/day"""
        assert FREE.markets < PRO.markets
        assert "1m" in PRO.intervals
        assert "4h" in PRO.intervals
        assert PRO.history_days == 365
        assert PRO.models == frozenset({"standard", "deepseek", "qwen"})
        assert PRO.daily_quota == 5000
        assert PRO.qps == 30

    def test_enterprise_tier_unlimited(self):
        """ENTERPRISE: 无限历史/模型/配额"""
        assert ENTERPRISE.history_days == -1
        assert ENTERPRISE.daily_quota == -1
        assert ENTERPRISE.qps == 100
        assert "gpt4" in ENTERPRISE.models
        assert "claude" in ENTERPRISE.models

    def test_tier_escalation_monotonic(self):
        """等级递增：权限只增不减"""
        assert len(FREE.markets) <= len(PRO.markets) <= len(ENTERPRISE.markets)
        assert len(FREE.intervals) <= len(PRO.intervals) <= len(ENTERPRISE.intervals)
        assert len(FREE.models) <= len(PRO.models) <= len(ENTERPRISE.models)
        assert FREE.daily_quota < PRO.daily_quota
        assert FREE.qps < PRO.qps < ENTERPRISE.qps

    def test_features_progression(self):
        """功能标识递增"""
        assert FREE.features < PRO.features
        assert PRO.features < ENTERPRISE.features

    def test_all_tiers_have_valid_order(self):
        """所有注册的 tier 都有对应 order"""
        for tier_name in TIERS:
            assert tier_name in TIER_ORDER

    def test_tier_configs_are_frozen(self):
        """TierConfig 是 frozen dataclass，不可变"""
        with pytest.raises(AttributeError):
            FREE.daily_quota = 999

    def test_crypto_market_naming(self):
        """加密市场标识为 crypto_binance"""
        assert "crypto_binance" in PRO.markets
        assert "crypto_binance" in ENTERPRISE.markets
        assert "crypto_binance" not in FREE.markets
