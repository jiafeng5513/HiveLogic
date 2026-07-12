# -*- coding: utf-8 -*-
"""
Reflection 数据模型 — DecisionLog ORM 模型。

记录每次 multi-agent 决策的完整上下文和后续结果，
用于反思注入（将历史偏差信息注入新决策 prompt）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text

from src.storage import Base


class DecisionLog(Base):
    """决策日志 — 记录每次 agent 决策及后续验证。"""

    __tablename__ = "decision_log"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 股票信息
    stock_code = Column(String(10), nullable=False, index=True)
    stock_name = Column(String(50))

    # 决策信息
    signal = Column(String(20), nullable=False)  # buy/sell/hold
    confidence = Column(Float)
    reasoning = Column(Text)  # 决策摘要

    # 上下文快照
    research_plan_json = Column(Text)  # ResearchPlan JSON
    risk_verdict_json = Column(Text)  # Risk debate verdict JSON
    debate_summary_json = Column(Text)  # Bull/Bear debate summary

    # Phase A: autonomous mode — investigation plan + step reasoning trace
    autonomous_plan_json = Column(Text)  # AutonomousPlannerAgent investigation plan
    autonomous_step_reasoning_json = Column(Text)  # Per-step reasoning chain (REASONING model)

    # 模式
    orchestrator_mode = Column(String(20))  # quick/standard/full/specialist

    # 后续验证 (异步更新)
    actual_return_pct = Column(Float)  # 实际收益率 (N天后)
    actual_direction = Column(String(10))  # up/down/flat
    deviation_score = Column(Float)  # 偏差分 (-1 到 1, 0=准确)
    verified_at = Column(DateTime)

    # 时间
    created_at = Column(DateTime, default=datetime.now, index=True)

    __table_args__ = (
        Index("ix_decision_log_code_time", "stock_code", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "signal": self.signal,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "orchestrator_mode": self.orchestrator_mode,
            "actual_return_pct": self.actual_return_pct,
            "actual_direction": self.actual_direction,
            "deviation_score": self.deviation_score,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
        }
