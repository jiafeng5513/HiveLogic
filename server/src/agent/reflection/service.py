# -*- coding: utf-8 -*-
"""
Reflection Service — 反思注入与决策记录服务。

提供:
1. build_reflection_prompt() — 基于历史偏差生成反思注入文本
2. record_decision() — 在决策完成后记录日志
"""

from __future__ import annotations

import logging
from typing import Optional

from src.agent.reflection.repository import ReflectionRepository

logger = logging.getLogger(__name__)


class ReflectionService:
    """反思服务 — 注入历史偏差信息到 agent prompt。"""

    def __init__(self, repository: ReflectionRepository):
        self._repo = repository

    def build_reflection_prompt(
        self,
        stock_code: str,
        lookback_days: int = 30,
    ) -> str:
        """
        基于历史已验证决策生成反思文本。

        如果没有已验证记录，返回空字符串（不注入）。
        """
        verified = self._repo.get_verified_decisions(
            stock_code=stock_code,
            lookback_days=lookback_days,
            limit=5,
        )
        if not verified:
            return ""

        # 计算偏差统计
        deviations = [v.deviation_score for v in verified if v.deviation_score is not None]
        if not deviations:
            return ""

        avg_deviation = sum(deviations) / len(deviations)
        bullish_bias = sum(1 for d in deviations if d > 0.3)
        bearish_bias = sum(1 for d in deviations if d < -0.3)

        lines = [
            "## Historical Reflection (Self-Calibration)",
            f"Based on {len(verified)} recent verified decisions for this stock:",
            f"- Average deviation: {avg_deviation:+.2f} (positive = over-bullish, negative = over-bearish)",
        ]

        if bullish_bias > len(verified) * 0.5:
            lines.append(
                "- ⚠️ PATTERN: You have been systematically TOO BULLISH on this stock. "
                "Apply extra scrutiny to bullish arguments."
            )
        elif bearish_bias > len(verified) * 0.5:
            lines.append(
                "- ⚠️ PATTERN: You have been systematically TOO BEARISH on this stock. "
                "Ensure you're not dismissing legitimate bullish signals."
            )

        # 列出最近几个误判
        wrong = [v for v in verified[:3] if abs(v.deviation_score or 0) > 0.3]
        if wrong:
            lines.append("- Recent mispredictions:")
            for w in wrong:
                date_str = w.created_at.strftime("%m-%d") if w.created_at else "?"
                lines.append(
                    f"  - {date_str}: Signal={w.signal}, "
                    f"Actual={w.actual_direction} ({w.actual_return_pct:+.1f}%)"
                )

        lines.append("")
        lines.append("Use this information to calibrate your confidence, NOT to reverse your analysis.")
        return "\n".join(lines)

    def record_decision(
        self,
        stock_code: str,
        stock_name: str,
        signal: str,
        confidence: float,
        reasoning: str,
        orchestrator_mode: str = "",
        research_plan: Optional[dict] = None,
        risk_verdict: Optional[dict] = None,
        debate_summary: Optional[dict] = None,
        autonomous_plan: Optional[dict] = None,
        autonomous_step_reasoning: Optional[dict] = None,
    ) -> Optional[int]:
        """记录决策日志。失败时返回 None 而非抛出异常。"""
        try:
            return self._repo.record_decision(
                stock_code=stock_code,
                stock_name=stock_name,
                signal=signal,
                confidence=confidence,
                reasoning=reasoning,
                orchestrator_mode=orchestrator_mode,
                research_plan=research_plan,
                risk_verdict=risk_verdict,
                debate_summary=debate_summary,
                autonomous_plan=autonomous_plan,
                autonomous_step_reasoning=autonomous_step_reasoning,
            )
        except Exception as exc:
            logger.warning("[Reflection] failed to record decision: %s", exc)
            return None
