# -*- coding: utf-8 -*-
"""
UserProfileService — Phase D.3 用户画像读写服务。

提供:
1. get_or_create_profile(account_id) — 读取（或自动创建空）画像
2. update_profile(account_id, **fields) — 更新画像字段
3. get_profile_for_context(account_id) — 返回注入 agent context 的精简 dict
4. inject_profile_into_context(context, account_id) — 就地写入 context["user_profile"]
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from src.models.user_profile import UserProfile, _safe_json_list
from src.storage import DatabaseManager

logger = logging.getLogger(__name__)


class UserProfileService:
    """用户画像 CRUD + context 注入。"""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or DatabaseManager.get_instance().session_scope

    def get_or_create_profile(self, account_id: int) -> UserProfile:
        """读取用户画像；不存在则创建空画像。"""
        with self._session_factory() as session:
            profile = (
                session.query(UserProfile)
                .filter(UserProfile.account_id == account_id)
                .first()
            )
            if profile is None:
                profile = UserProfile(account_id=account_id)
                session.add(profile)
                session.commit()
                session.refresh(profile)
            session.expunge(profile)
            return profile

    def update_profile(
        self,
        account_id: int,
        risk_tolerance: Optional[str] = None,
        holding_horizon: Optional[str] = None,
        preferred_markets: Optional[list] = None,
        preferred_sectors: Optional[list] = None,
        excluded_stocks: Optional[list] = None,
        notes: Optional[str] = None,
    ) -> UserProfile:
        """更新画像字段（仅更新非 None 字段）。返回更新后的 profile。"""
        with self._session_factory() as session:
            profile = (
                session.query(UserProfile)
                .filter(UserProfile.account_id == account_id)
                .first()
            )
            if profile is None:
                profile = UserProfile(account_id=account_id)
                session.add(profile)

            if risk_tolerance is not None:
                profile.risk_tolerance = risk_tolerance
            if holding_horizon is not None:
                profile.holding_horizon = holding_horizon
            if preferred_markets is not None:
                profile.preferred_markets = json.dumps(preferred_markets, ensure_ascii=False)
            if preferred_sectors is not None:
                profile.preferred_sectors = json.dumps(preferred_sectors, ensure_ascii=False)
            if excluded_stocks is not None:
                profile.excluded_stocks = json.dumps(excluded_stocks, ensure_ascii=False)
            if notes is not None:
                profile.notes = notes[:2000] if notes else ""

            session.commit()
            session.refresh(profile)
            session.expunge(profile)
            return profile

    def get_profile_for_context(self, account_id: int) -> Optional[Dict[str, Any]]:
        """返回注入 agent context 的精简 dict；无画像返回 None。"""
        try:
            profile = self.get_or_create_profile(account_id)
            return {
                "account_id": account_id,
                "risk_tolerance": profile.risk_tolerance or "moderate",
                "holding_horizon": profile.holding_horizon or "mid_term",
                "preferred_markets": _safe_json_list(profile.preferred_markets),
                "preferred_sectors": _safe_json_list(profile.preferred_sectors),
                "excluded_stocks": _safe_json_list(profile.excluded_stocks),
                "notes": profile.notes or "",
            }
        except Exception as exc:
            logger.warning("[UserProfile] failed to load profile for account %s: %s", account_id, exc)
            return None

    def inject_profile_into_context(
        self,
        context: Optional[Dict[str, Any]],
        account_id: Optional[int],
    ) -> Dict[str, Any]:
        """就地向 context 注入 account_id 与 user_profile。返回（可能新建的）context。"""
        ctx = dict(context) if context else {}
        if account_id is not None:
            ctx["account_id"] = account_id
            profile = self.get_profile_for_context(account_id)
            if profile:
                ctx["user_profile"] = profile
        return ctx


# ==================== 单例 ====================

_instance: Optional[UserProfileService] = None


def get_user_profile_service() -> UserProfileService:
    global _instance
    if _instance is None:
        _instance = UserProfileService()
    return _instance
