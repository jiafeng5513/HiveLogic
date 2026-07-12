# -*- coding: utf-8 -*-
"""
SkillRouter — rule-based skill selection.

Selects which trading skills to apply based on:
1. User-explicit request (highest priority)
2. Market regime detection from technical data in ``AgentContext``
3. Centralised default fallback
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from src.agent.protocols import AgentContext
from src.agent.skills.defaults import (
    get_default_router_skill_ids,
    get_regime_skill_ids,
)

logger = logging.getLogger(__name__)

# Phase D: 低胜率 skill 处理阈值
_LOW_WIN_RATE_THRESHOLD = 0.40  # 胜率低于 40% 触发降权/跳过
_DOWNWEIGHT_FACTOR = 0.5  # 低胜率 skill 权重乘数（仅标注降权，不直接禁用）


class SkillRouter:
    """Select applicable skills for a given analysis context."""

    def select_skills(
        self,
        ctx: AgentContext,
        max_count: int = 3,
    ) -> List[str]:
        requested_skills = ctx.meta.get("skills_requested") or ctx.meta.get("strategies_requested", [])
        if requested_skills:
            logger.info("[SkillRouter] user-requested skills: %s", requested_skills)
            return requested_skills[:max_count]

        routing_mode = self._get_routing_mode()
        if routing_mode == "manual":
            selected = self._get_manual_skills(max_count=max_count)
            logger.info("[SkillRouter] manual mode — using skills: %s", selected)
            return selected

        available_skills = self._get_available_skills()
        skill_catalog = available_skills or None
        available_ids = {skill.name for skill in available_skills}
        regime = self._detect_regime(ctx)
        if regime:
            selected = get_regime_skill_ids(
                regime,
                skill_catalog,
                max_count=max_count,
                available_skill_ids=available_ids or None,
            )
            if selected:
                selected = self._apply_learning_ranking(selected, max_count)
                logger.info("[SkillRouter] regime=%s -> skills: %s", regime, selected)
                return selected

        default_skills = get_default_router_skill_ids(
            skill_catalog,
            max_count=max_count,
            available_skill_ids=available_ids or None,
        )
        default_skills = self._apply_learning_ranking(default_skills, max_count)
        logger.info("[SkillRouter] using default skills: %s", default_skills)
        return default_skills

    def select_strategies(
        self,
        ctx: AgentContext,
        max_count: int = 3,
    ) -> List[str]:
        """Compatibility wrapper for legacy strategy-based callers."""
        return self.select_skills(ctx, max_count=max_count)

    def _detect_regime(self, ctx: AgentContext) -> Optional[str]:
        for op in ctx.opinions:
            if op.agent_name != "technical":
                continue
            raw = op.raw_data or {}

            ma_alignment = str(raw.get("ma_alignment", "")).lower()
            try:
                trend_score = float(raw.get("trend_score", 50))
            except (TypeError, ValueError):
                trend_score = 50.0
            volume_status = str(raw.get("volume_status", "")).lower()

            if ma_alignment == "bullish" and trend_score >= 70:
                return "trending_up"
            if ma_alignment == "bearish" and trend_score <= 30:
                return "trending_down"
            if ma_alignment == "neutral" or 35 <= trend_score <= 65:
                return "sideways"
            if volume_status == "heavy" and 30 < trend_score < 70:
                return "volatile"

        if ctx.meta.get("sector_hot"):
            return "sector_hot"
        return None

    @staticmethod
    def _get_routing_mode() -> str:
        try:
            from src.config import get_config

            config = get_config()
            return getattr(config, "agent_skill_routing", "auto")
        except Exception:
            logger.warning("Failed to get routing mode, falling back to auto", exc_info=True)
            return "auto"

    @staticmethod
    def _get_available_ids() -> set:
        return {skill.name for skill in SkillRouter._get_available_skills()}

    @staticmethod
    def _get_available_skills() -> list:
        try:
            from src.agent.factory import _SKILL_MANAGER_PROTOTYPE

            if _SKILL_MANAGER_PROTOTYPE is not None:
                return list(_SKILL_MANAGER_PROTOTYPE.list_skills())

            from src.agent.factory import get_skill_manager

            sm = get_skill_manager()
            return list(sm.list_skills())
        except Exception:
            logger.warning("Failed to get available skills", exc_info=True)
            return []

    @classmethod
    def _get_manual_skills(cls, max_count: int) -> List[str]:
        configured: List[str] = []
        try:
            from src.config import get_config

            config = get_config()
            configured = [
                skill_id
                for skill_id in getattr(config, "agent_skills", []) or []
                if isinstance(skill_id, str) and skill_id
            ]
        except Exception:
            logger.warning("Failed to get manual skills config", exc_info=True)
            configured = []

        available_skills = cls._get_available_skills()
        skill_catalog = available_skills or None
        available = {skill.name for skill in available_skills}
        selected = [skill_id for skill_id in configured if skill_id in available][:max_count]
        if selected:
            return selected

        return get_default_router_skill_ids(
            skill_catalog,
            max_count=max_count,
            available_skill_ids=available or None,
        )

    # -----------------------------------------------------------------
    # Phase D: adaptive learning — rank skills by verified win rate
    # -----------------------------------------------------------------

    @classmethod
    def _apply_learning_ranking(
        cls,
        skill_ids: List[str],
        max_count: int,
    ) -> List[str]:
        """按历史胜率对 skill 列表重排序，低胜率 skill 降权但不剔除。

        受 ``agent_skill_learning_enabled`` 开关控制；关闭时原样返回。
        样本不足（< ``_MIN_LEARNING_SAMPLES``）时也原样返回，避免早期噪音。
        """
        if not skill_ids:
            return skill_ids

        if not cls._is_learning_enabled():
            return skill_ids[:max_count]

        win_rates = cls._get_skill_win_rates(skill_ids)
        if not win_rates:
            return skill_ids[:max_count]

        # 按胜率降序排序；无数据的 skill 保持原顺序（排在有数据的之后）
        def _sort_key(sid: str) -> tuple:
            entry = win_rates.get(sid)
            if not entry or entry["total"] < _MIN_LEARNING_SAMPLES:
                return (0, 0.5, sid)  # 无数据 → 中性，排后
            return (1, entry["win_rate"], sid)

        ranked = sorted(skill_ids, key=_sort_key, reverse=True)

        # 标注低胜率 skill（仅日志，不剔除——用户可覆盖）
        for sid in ranked:
            entry = win_rates.get(sid)
            if entry and entry["total"] >= _MIN_LEARNING_SAMPLES:
                if entry["win_rate"] < _LOW_WIN_RATE_THRESHOLD:
                    logger.info(
                        "[SkillRouter] skill=%s 历史胜率 %.1f%% (< %.0f%%) — 降权标注",
                        sid,
                        entry["win_rate"] * 100,
                        _LOW_WIN_RATE_THRESHOLD * 100,
                    )

        return ranked[:max_count]

    @staticmethod
    def _is_learning_enabled() -> bool:
        try:
            from src.config import get_config
            config = get_config()
            return bool(getattr(config, "agent_skill_learning_enabled", False))
        except Exception:
            return False

    @staticmethod
    def _get_skill_win_rates(skill_ids: List[str]) -> Dict[str, Dict[str, float]]:
        """批量查询 skill 历史胜率。失败时返回空 dict。"""
        result: Dict[str, Dict[str, float]] = {}
        try:
            from src.agent.reflection.service import ReflectionService
            from src.agent.reflection.repository import ReflectionRepository
            from src.storage import DatabaseManager

            db = DatabaseManager.get_instance()
            repo = ReflectionRepository(db.session_scope)
            service = ReflectionService(repo)

            for sid in skill_ids:
                stats = service.get_skill_stats(sid, lookback_days=90)
                result[sid] = {
                    "win_rate": stats.get("win_rate", 0.5),
                    "total": stats.get("total_calls", 0),
                }
        except Exception as exc:
            logger.debug("[SkillRouter] failed to get skill win rates: %s", exc)
        return result


_MIN_LEARNING_SAMPLES = 5  # 至少 5 条已验证决策才参与排名


StrategyRouter = SkillRouter
_DEFAULT_STRATEGIES = tuple(get_default_router_skill_ids())
_DEFAULT_SKILLS = _DEFAULT_STRATEGIES
