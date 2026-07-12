# -*- coding: utf-8 -*-
"""
Entitlement + Tier 权限矩阵单元测试

测试场景:
1. TierConfig: 等级定义/市场/周期/模型/配额
2. tier_meets_minimum: 等级比较
3. get_effective_tier: 降级处理
4. EntitlementService: 403/402 抛出逻辑（mock repo）
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.models.tiers import (
    FREE,
    PRO,
    ENTERPRISE,
    TIERS,
    TIER_ORDER,
    get_tier_config,
    get_effective_tier,
    tier_meets_minimum,
)


class TestTierConfigs:
    """等级配置定义正确性"""

    def test_free_tier_restrictions(self):
        assert "cn" in FREE.markets
        assert "hk" not in FREE.markets
        assert "us" not in FREE.markets
        assert FREE.history_days == 30
        assert len(FREE.models) == 0
        assert FREE.daily_quota == 100

    def test_pro_tier_permissions(self):
        assert "cn" in PRO.markets
        assert "hk" in PRO.markets
        assert "us" in PRO.markets
        assert "crypto_binance" in PRO.markets
        assert PRO.history_days == 365
        assert "standard" in PRO.models
        assert "deepseek" in PRO.models
        assert PRO.daily_quota == 5000

    def test_enterprise_tier_unlimited(self):
        assert ENTERPRISE.history_days == -1
        assert ENTERPRISE.daily_quota == -1
        assert "gpt4" in ENTERPRISE.models
        assert "claude" in ENTERPRISE.models

    def test_interval_progression(self):
        assert len(FREE.intervals) < len(PRO.intervals)
        assert FREE.intervals == frozenset({"1d", "1w"})
        assert "1m" not in FREE.intervals
        assert "1m" in PRO.intervals

    def test_allows_market(self):
        assert FREE.allows_market("cn") is True
        assert FREE.allows_market("hk") is False
        assert PRO.allows_market("us") is True

    def test_allows_interval(self):
        assert FREE.allows_interval("1d") is True
        assert FREE.allows_interval("1m") is False
        assert PRO.allows_interval("1m") is True

    def test_allows_model(self):
        assert FREE.allows_model("standard") is False
        assert PRO.allows_model("standard") is True
        assert PRO.allows_model("gpt4") is False
        assert ENTERPRISE.allows_model("gpt4") is True

    def test_has_feature(self):
        assert FREE.has_feature("basic_chart") is True
        assert FREE.has_feature("ai_analysis") is False
        assert PRO.has_feature("ai_analysis") is True
        assert ENTERPRISE.has_feature("api_access") is True

    def test_tiers_registry_complete(self):
        assert set(TIERS.keys()) == {"free", "pro", "enterprise"}

    def test_tier_order_monotonic(self):
        assert TIER_ORDER["free"] < TIER_ORDER["pro"]
        assert TIER_ORDER["pro"] < TIER_ORDER["enterprise"]


class TestTierComparison:
    """tier_meets_minimum 等级比较"""

    def test_meets_exact(self):
        assert tier_meets_minimum("free", "free") is True
        assert tier_meets_minimum("pro", "pro") is True

    def test_meets_higher(self):
        assert tier_meets_minimum("pro", "free") is True
        assert tier_meets_minimum("enterprise", "free") is True
        assert tier_meets_minimum("enterprise", "pro") is True

    def test_does_not_meet_lower(self):
        assert tier_meets_minimum("free", "pro") is False
        assert tier_meets_minimum("free", "enterprise") is False
        assert tier_meets_minimum("pro", "enterprise") is False

    def test_unknown_tier(self):
        assert tier_meets_minimum("unknown", "free") is False
        assert tier_meets_minimum("free", "unknown") is True  # -1 >= -1


class TestGetEffectiveTier:
    """get_effective_tier 降级处理"""

    def test_known_tier(self):
        assert get_effective_tier("pro") is PRO
        assert get_effective_tier("enterprise") is ENTERPRISE

    def test_none_tier_falls_back_to_free(self):
        assert get_effective_tier(None) is FREE

    def test_unknown_tier_falls_back_to_free(self):
        assert get_effective_tier("nonexistent") is FREE

    def test_get_tier_config_returns_none_for_unknown(self):
        assert get_tier_config("nonexistent") is None


class TestEntitlementService:
    """EntitlementService 权限检查（mock repo）"""

    @pytest.fixture
    def mock_service(self):
        """构造 EntitlementService 但替换 repo 为 mock。"""
        with patch("src.services.entitlement.get_account_repository") as mock_get_repo:
            mock_repo = MagicMock()
            mock_get_repo.return_value = mock_repo
            from src.services.entitlement import EntitlementService
            svc = EntitlementService()
            return svc, mock_repo

    def test_check_market_access_allowed(self, mock_service):
        svc, mock_repo = mock_service
        mock_repo.get_account_tier.return_value = "pro"
        svc.check_market_access(1, "hk")

    def test_check_market_access_denied(self, mock_service):
        svc, mock_repo = mock_service
        mock_repo.get_account_tier.return_value = "free"
        with pytest.raises(HTTPException) as exc_info:
            svc.check_market_access(1, "hk")
        assert exc_info.value.status_code == 403
        assert "market_not_allowed" in str(exc_info.value.detail)

    def test_check_interval_access_denied(self, mock_service):
        svc, mock_repo = mock_service
        mock_repo.get_account_tier.return_value = "free"
        with pytest.raises(HTTPException) as exc_info:
            svc.check_interval_access(1, "1m")
        assert exc_info.value.status_code == 403

    def test_check_history_depth_exceeded(self, mock_service):
        svc, mock_repo = mock_service
        mock_repo.get_account_tier.return_value = "free"
        with pytest.raises(HTTPException) as exc_info:
            svc.check_history_depth(1, 60)
        assert exc_info.value.status_code == 403
        assert "history_depth_exceeded" in str(exc_info.value.detail)

    def test_check_history_depth_unlimited(self, mock_service):
        svc, mock_repo = mock_service
        mock_repo.get_account_tier.return_value = "enterprise"
        svc.check_history_depth(1, 9999)

    def test_check_model_access_denied_for_free(self, mock_service):
        svc, mock_repo = mock_service
        mock_repo.get_account_tier.return_value = "free"
        with pytest.raises(HTTPException) as exc_info:
            svc.check_model_access(1, "standard")
        assert exc_info.value.status_code == 403

    def test_check_model_access_gpt4_enterprise_only(self, mock_service):
        svc, mock_repo = mock_service
        mock_repo.get_account_tier.return_value = "pro"
        with pytest.raises(HTTPException) as exc_info:
            svc.check_model_access(1, "gpt4")
        assert exc_info.value.status_code == 403

        mock_repo.get_account_tier.return_value = "enterprise"
        svc.check_model_access(1, "gpt4")

    def test_check_daily_quota_exceeded(self, mock_service):
        svc, mock_repo = mock_service
        mock_repo.get_account_tier.return_value = "free"
        mock_repo.get_usage_summary.return_value = {"today_requests": 100}
        with pytest.raises(HTTPException) as exc_info:
            svc.check_daily_quota(1)
        assert exc_info.value.status_code == 402
        assert "quota_exceeded" in str(exc_info.value.detail)

    def test_check_daily_quota_unlimited(self, mock_service):
        svc, mock_repo = mock_service
        mock_repo.get_account_tier.return_value = "enterprise"
        mock_repo.get_usage_summary.return_value = {"today_requests": 99999}
        svc.check_daily_quota(1)

    def test_check_feature_allowed(self, mock_service):
        svc, mock_repo = mock_service
        mock_repo.get_account_tier.return_value = "pro"
        svc.check_feature(1, "ai_analysis")

    def test_check_feature_denied(self, mock_service):
        svc, mock_repo = mock_service
        mock_repo.get_account_tier.return_value = "free"
        with pytest.raises(HTTPException) as exc_info:
            svc.check_feature(1, "ai_analysis")
        assert exc_info.value.status_code == 403

    def test_get_entitlements(self, mock_service):
        svc, mock_repo = mock_service
        mock_repo.get_account_tier.return_value = "pro"
        result = svc.get_entitlements(1)
        assert result["tier"] == "pro"
        assert "hk" in result["markets"]
        assert result["daily_quota"] == 5000
        assert "ai_analysis" in result["features"]
