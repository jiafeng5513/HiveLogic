# -*- coding: utf-8 -*-
"""
Reflection Repository — DecisionLog 数据访问层。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from src.agent.reflection.models import DecisionLog

logger = logging.getLogger(__name__)


class ReflectionRepository:
    """DecisionLog 的 CRUD 操作。"""

    def __init__(self, session_factory):
        """
        Args:
            session_factory: SQLAlchemy sessionmaker 实例
        """
        self._session_factory = session_factory

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
    ) -> int:
        """记录一条新的决策日志，返回 ID。"""
        with self._session_factory() as session:
            log = DecisionLog(
                stock_code=stock_code,
                stock_name=stock_name or "",
                signal=signal,
                confidence=confidence,
                reasoning=reasoning[:500] if reasoning else "",
                orchestrator_mode=orchestrator_mode,
                research_plan_json=json.dumps(research_plan, ensure_ascii=False) if research_plan else None,
                risk_verdict_json=json.dumps(risk_verdict, ensure_ascii=False) if risk_verdict else None,
                debate_summary_json=json.dumps(debate_summary, ensure_ascii=False) if debate_summary else None,
                autonomous_plan_json=json.dumps(autonomous_plan, ensure_ascii=False) if autonomous_plan else None,
                autonomous_step_reasoning_json=json.dumps(autonomous_step_reasoning, ensure_ascii=False) if autonomous_step_reasoning else None,
            )
            session.add(log)
            session.commit()
            return log.id

    def get_recent_decisions(
        self,
        stock_code: str,
        lookback_days: int = 30,
        limit: int = 10,
    ) -> List[DecisionLog]:
        """获取某只股票的近期决策记录。"""
        cutoff = datetime.now() - timedelta(days=lookback_days)
        with self._session_factory() as session:
            results = (
                session.query(DecisionLog)
                .filter(
                    DecisionLog.stock_code == stock_code,
                    DecisionLog.created_at >= cutoff,
                )
                .order_by(DecisionLog.created_at.desc())
                .limit(limit)
                .all()
            )
            # Detach from session
            session.expunge_all()
            return results

    def get_verified_decisions(
        self,
        stock_code: str,
        lookback_days: int = 30,
        limit: int = 10,
    ) -> List[DecisionLog]:
        """获取已验证的决策记录（有 deviation_score）。"""
        cutoff = datetime.now() - timedelta(days=lookback_days)
        with self._session_factory() as session:
            results = (
                session.query(DecisionLog)
                .filter(
                    DecisionLog.stock_code == stock_code,
                    DecisionLog.created_at >= cutoff,
                    DecisionLog.deviation_score.isnot(None),
                )
                .order_by(DecisionLog.created_at.desc())
                .limit(limit)
                .all()
            )
            session.expunge_all()
            return results

    def update_verification(
        self,
        decision_id: int,
        actual_return_pct: float,
        actual_direction: str,
        deviation_score: float,
    ) -> None:
        """异步更新决策的验证结果。"""
        with self._session_factory() as session:
            log = session.query(DecisionLog).filter(DecisionLog.id == decision_id).first()
            if log:
                log.actual_return_pct = actual_return_pct
                log.actual_direction = actual_direction
                log.deviation_score = deviation_score
                log.verified_at = datetime.now()
                session.commit()
