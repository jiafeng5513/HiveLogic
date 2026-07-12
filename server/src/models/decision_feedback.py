# -*- coding: utf-8 -*-
"""
DecisionFeedback 数据模型 — Phase D.5 学习反馈闭环。

用户对某条 DecisionLog 的执行情况与实际结果反馈，用于：
1. 管理面板"决策复盘"卡片展示用户视角的执行结果。
2. 反哺 skill 学习——用户反馈优先于自动验证 outcome。
3. 生成"AI 自我评估报告"的数据源之一。

表 ``decision_feedback`` 与 ``decision_log`` 多对一（一条决策可被多次反馈）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)

from src.storage import Base


class DecisionFeedback(Base):
    """用户对决策的反馈 — 执行与否 + 实际结果 + 备注。"""

    __tablename__ = "decision_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 关联决策
    decision_log_id = Column(
        Integer,
        ForeignKey("decision_log.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 反馈用户
    account_id = Column(
        Integer,
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # 执行情况: executed / not_executed / partial
    execution_status = Column(String(20), nullable=False)

    # 用户视角的实际结果: profit / loss / breakeven / pending
    user_outcome = Column(String(20))

    # 用户填写的实际收益率（可选，百分比）
    user_return_pct = Column(Float)

    # 反馈备注
    notes = Column(Text)

    # 反馈来源: user / admin
    source = Column(String(20), default="user")

    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.now, onupdate=datetime.now, nullable=False
    )

    __table_args__ = (
        Index("ix_decision_feedback_decision", "decision_log_id"),
        Index("ix_decision_feedback_account", "account_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "decision_log_id": self.decision_log_id,
            "account_id": self.account_id,
            "execution_status": self.execution_status,
            "user_outcome": self.user_outcome,
            "user_return_pct": self.user_return_pct,
            "notes": self.notes or "",
            "source": self.source or "user",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
