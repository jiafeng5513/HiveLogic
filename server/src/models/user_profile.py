# -*- coding: utf-8 -*-
"""
UserProfile data model — Phase D.3 用户画像与偏好。

存储单个用户的投资偏好画像，供 orchestrator 注入 agent context，
让分析建议考虑用户实际持仓、风险偏好、持仓周期等。

表 ``user_profiles`` 与 ``accounts`` 一对一（account_id UNIQUE）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from src.storage import Base


class UserProfile(Base):
    """用户画像 — 投资偏好与约束。"""

    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(
        Integer,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # 风险偏好: conservative / moderate / aggressive
    risk_tolerance = Column(String(20), default="moderate")

    # 持仓周期: short_term / mid_term / long_term
    holding_horizon = Column(String(20), default="mid_term")

    # 偏好市场 (JSON 数组字符串): ["cn_stock", "hk_stock", "us_stock", "crypto"]
    preferred_markets = Column(Text, default="[]")

    # 偏好板块 (JSON 数组字符串): ["新能源", "半导体", "医药"]
    preferred_sectors = Column(Text, default="[]")

    # 排除个股 (JSON 数组字符串): ["ST股", "创业板"]
    excluded_stocks = Column(Text, default="[]")

    # 自由备注（用户口述的额外偏好，由 D.4 对话长记忆自动提取）
    notes = Column(Text, default="")

    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    __table_args__ = (
        Index("ix_user_profiles_account", "account_id"),
    )

    def to_dict(self) -> Dict[str, Any]:
        import json as _json
        return {
            "id": self.id,
            "account_id": self.account_id,
            "risk_tolerance": self.risk_tolerance,
            "holding_horizon": self.holding_horizon,
            "preferred_markets": _safe_json_list(self.preferred_markets),
            "preferred_sectors": _safe_json_list(self.preferred_sectors),
            "excluded_stocks": _safe_json_list(self.excluded_stocks),
            "notes": self.notes or "",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


def _safe_json_list(raw: Optional[str]) -> List[str]:
    """安全解析 JSON 数组字符串为 list，失败时返回空列表。"""
    if not raw:
        return []
    try:
        import json as _json
        parsed = _json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


class UserNote(Base):
    """用户长期笔记 — Phase D.4 跨 session 长记忆。

    用户在对话中表达的长期偏好（"我是长线投资者""我不碰 ST"），
    由 AI 自动识别并提取入库，或由用户手动添加。
    与 session 无关，跨 session 持久存在，注入每轮对话上下文。
    """

    __tablename__ = "user_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(
        Integer,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 笔记内容（用户原话或 AI 提炼的偏好摘要）
    content = Column(Text, nullable=False)

    # 来源: user_explicit (用户明确说) / ai_extracted (AI 识别后询问确认) / manual
    source = Column(String(20), default="user_explicit")

    # 类别: preference / constraint / goal / fact (可选，便于过滤)
    category = Column(String(20), default="preference")

    # 是否激活（用户可禁用某条笔记而不删除）
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    __table_args__ = (
        Index("ix_user_notes_account_active", "account_id", "is_active"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "content": self.content or "",
            "source": self.source or "user_explicit",
            "category": self.category or "preference",
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
