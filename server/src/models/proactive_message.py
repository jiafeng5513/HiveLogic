# -*- coding: utf-8 -*-
"""
ProactiveMessage 数据模型 — Phase E 主动陪伴。

存储异动事件触发的 AI 主动分析结果（轻量版）与盘后机会扫描结果。

表 ``proactive_message`` 用途：
1. 管理面板"主动消息中心"展示历史主动分析。
2. 客户端轮询 / WebSocket 推送未读消息。
3. 闭环追踪：用户是否查看 / 采纳。

类型：
- anomaly_response: 异动事件触发的轻量分析（Phase E.2）
- opportunity: 盘后机会扫描结果（Phase E.3）
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)

from src.storage import Base


class ProactiveMessage(Base):
    """主动消息 — AI 主动分析结果。"""

    __tablename__ = "proactive_message"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 消息类型: anomaly_response / opportunity
    message_type = Column(String(30), nullable=False, index=True)

    # 关联标的
    symbol = Column(String(30), nullable=False, index=True)
    symbol_name = Column(String(100), default="")

    # 触发来源信息
    trigger_type = Column(String(50), default="")  # anomaly_type.value
    trigger_severity = Column(String(20), default="")  # severity.value
    trigger_summary = Column(Text, default="")  # 异动事件描述

    # AI 分析结果
    analysis_content = Column(Text, default="")  # AI 结论（markdown 文本）
    analysis_summary = Column(Text, default="")  # 一句话摘要
    signal = Column(String(20), default="")  # buy/sell/hold/watch
    confidence = Column(Float, default=0.0)  # 0-1

    # 元数据（JSON）
    context_json = Column(Text, default="")

    # 状态: unread / read / dismissed / acted
    status = Column(String(20), default="unread", nullable=False)

    # 关联账户（可选，个性化推送时用）
    account_id = Column(Integer, nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.now, nullable=False)
    read_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_proactive_message_type_status", "message_type", "status"),
        Index("ix_proactive_message_created", "created_at"),
        Index("ix_proactive_message_symbol", "symbol"),
    )

    def to_dict(self) -> Dict[str, Any]:
        import json

        context: Dict[str, Any] = {}
        if self.context_json:
            try:
                context = json.loads(self.context_json)
            except (ValueError, TypeError):
                context = {}

        return {
            "id": self.id,
            "message_type": self.message_type,
            "symbol": self.symbol,
            "symbol_name": self.symbol_name or "",
            "trigger_type": self.trigger_type or "",
            "trigger_severity": self.trigger_severity or "",
            "trigger_summary": self.trigger_summary or "",
            "analysis_content": self.analysis_content or "",
            "analysis_summary": self.analysis_summary or "",
            "signal": self.signal or "",
            "confidence": self.confidence or 0.0,
            "context": context,
            "status": self.status or "unread",
            "account_id": self.account_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "read_at": self.read_at.isoformat() if self.read_at else None,
        }
