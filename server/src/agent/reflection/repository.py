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
        skill_ids: Optional[List[str]] = None,
        account_id: Optional[int] = None,
        target_price: Optional[float] = None,
    ) -> int:
        """记录一条新的决策日志，返回 ID。"""
        with self._session_factory() as session:
            log = DecisionLog(
                stock_code=stock_code,
                stock_name=stock_name or "",
                signal=signal,
                confidence=confidence,
                reasoning=reasoning[:500] if reasoning else "",
                target_price=target_price,
                skill_ids_json=json.dumps(skill_ids, ensure_ascii=False) if skill_ids else None,
                account_id=account_id,
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
        outcome: Optional[str] = None,
        return_1d_pct: Optional[float] = None,
        return_20d_pct: Optional[float] = None,
    ) -> None:
        """异步更新决策的验证结果（多窗口）。"""
        with self._session_factory() as session:
            log = session.query(DecisionLog).filter(DecisionLog.id == decision_id).first()
            if log:
                log.actual_return_pct = actual_return_pct
                log.actual_direction = actual_direction
                log.deviation_score = deviation_score
                log.verified_at = datetime.now()
                if outcome is not None:
                    log.outcome = outcome
                if return_1d_pct is not None:
                    log.return_1d_pct = return_1d_pct
                if return_20d_pct is not None:
                    log.return_20d_pct = return_20d_pct
                session.commit()

    def get_pending_verifications(
        self,
        window_days: int,
        limit: int = 100,
    ) -> List[DecisionLog]:
        """获取到达验证窗口但尚未验证的决策。

        Args:
            window_days: 验证窗口天数（如 1/5/20）。返回 created_at + window_days <= now
                且 verified_at 为 NULL 的记录。
            limit: 最多返回条数
        """
        cutoff = datetime.now() - timedelta(days=window_days)
        with self._session_factory() as session:
            results = (
                session.query(DecisionLog)
                .filter(
                    DecisionLog.created_at <= cutoff,
                    DecisionLog.verified_at.is_(None),
                )
                .order_by(DecisionLog.created_at.asc())
                .limit(limit)
                .all()
            )
            session.expunge_all()
            return results

    def get_skill_stats(self, skill_id: str, lookback_days: int = 90) -> dict:
        """统计某个 skill 在指定回溯窗口内的胜率与平均收益。

        skill_id 通过 JSON 数组列 ``skill_ids_json`` 匹配（LIKE 查询，
        避免依赖 JSON 函数 —— SQLite/PostgreSQL 兼容）。

        Returns:
            {
                "skill_id": str,
                "total_calls": int,        # 含该 skill 的已验证决策数
                "win_count": int,
                "loss_count": int,
                "neutral_count": int,
                "win_rate": float,         # win / (win+loss+neutral)
                "avg_return_pct": float,   # 已验证决策的 5 日平均收益
                "direction_accuracy": float,  # 预测方向与实际方向一致的比例
            }
        """
        cutoff = datetime.now() - timedelta(days=lookback_days)
        # JSON 数组匹配：["momentum", ...] —— LIKE '%"skill_id"%'
        like_pattern = f'%"{skill_id}"%'
        with self._session_factory() as session:
            rows = (
                session.query(DecisionLog)
                .filter(
                    DecisionLog.skill_ids_json.like(like_pattern),
                    DecisionLog.created_at >= cutoff,
                    DecisionLog.verified_at.isnot(None),
                )
                .all()
            )

        if not rows:
            return {
                "skill_id": skill_id,
                "total_calls": 0,
                "win_count": 0,
                "loss_count": 0,
                "neutral_count": 0,
                "win_rate": 0.5,
                "avg_return_pct": 0.0,
                "direction_accuracy": 0.5,
            }

        win_count = sum(1 for r in rows if r.outcome == "win")
        loss_count = sum(1 for r in rows if r.outcome == "loss")
        neutral_count = sum(1 for r in rows if r.outcome == "neutral")

        total = len(rows)
        win_rate = win_count / total if total else 0.5

        returns = [r.actual_return_pct for r in rows if r.actual_return_pct is not None]
        avg_return = sum(returns) / len(returns) if returns else 0.0

        # 方向准确率：buy 信号 + 实际 up / sell 信号 + 实际 down = 正确
        direction_correct = 0
        direction_total = 0
        for r in rows:
            if r.signal in ("buy", "strong_buy") and r.actual_direction == "up":
                direction_correct += 1
                direction_total += 1
            elif r.signal in ("sell", "strong_sell") and r.actual_direction == "down":
                direction_correct += 1
                direction_total += 1
            elif r.signal == "hold":
                continue
            else:
                direction_total += 1
        direction_accuracy = direction_correct / direction_total if direction_total else 0.5

        return {
            "skill_id": skill_id,
            "total_calls": total,
            "win_count": win_count,
            "loss_count": loss_count,
            "neutral_count": neutral_count,
            "win_rate": win_rate,
            "avg_return_pct": avg_return,
            "direction_accuracy": direction_accuracy,
        }

    def get_recent_decisions_by_account(
        self,
        account_id: int,
        lookback_days: int = 30,
        limit: int = 10,
    ) -> List[DecisionLog]:
        """获取某个用户的近期决策记录（Phase D 个性化）。"""
        cutoff = datetime.now() - timedelta(days=lookback_days)
        with self._session_factory() as session:
            results = (
                session.query(DecisionLog)
                .filter(
                    DecisionLog.account_id == account_id,
                    DecisionLog.created_at >= cutoff,
                )
                .order_by(DecisionLog.created_at.desc())
                .limit(limit)
                .all()
            )
            session.expunge_all()
            return results
