# -*- coding: utf-8 -*-
"""
===================================
主动消息中心 Schema (Phase E.4)
===================================

Pydantic 响应模型 — 用于 /api/v1/proactive-messages 接口。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ProactiveMessageItem(BaseModel):
    """单条主动消息。"""

    id: int = Field(..., description="消息 ID")
    message_type: str = Field(..., description="消息类型: anomaly_response / opportunity")
    symbol: str = Field(..., description="关联标的代码")
    symbol_name: str = Field("", description="标的名称")
    trigger_type: str = Field("", description="触发类型")
    trigger_severity: str = Field("", description="严重程度: info / warning / critical")
    trigger_summary: str = Field("", description="触发事件摘要")
    analysis_content: str = Field("", description="AI 分析全文（markdown）")
    analysis_summary: str = Field("", description="一句话摘要")
    signal: str = Field("", description="信号: buy / sell / hold / watch")
    confidence: float = Field(0.0, description="置信度 0-1")
    context: Dict[str, Any] = Field(default_factory=dict, description="附加上下文")
    status: str = Field("unread", description="状态: unread / read / dismissed / acted")
    account_id: Optional[int] = Field(None, description="关联账户 ID")
    created_at: Optional[str] = Field(None, description="创建时间 ISO")
    read_at: Optional[str] = Field(None, description="阅读时间 ISO")


class ProactiveMessageListResponse(BaseModel):
    """主动消息列表分页响应。"""

    total: int = Field(..., description="总数")
    page: int = Field(..., description="当前页码")
    limit: int = Field(..., description="每页数量")
    unread_count: int = Field(..., description="未读总数（不受分页影响）")
    items: List[ProactiveMessageItem] = Field(default_factory=list, description="消息列表")


class ProactiveMessageDetailResponse(BaseModel):
    """单条主动消息详情。"""

    item: ProactiveMessageItem


class ProactiveMessageActionRequest(BaseModel):
    """操作主动消息 — 标记已读/忽略/采纳。"""

    status: str = Field(
        ...,
        description="目标状态: read / dismissed / acted",
    )


class ProactiveMessageActionResponse(BaseModel):
    """操作结果。"""

    success: bool = Field(..., description="是否成功")
    id: int = Field(..., description="消息 ID")
    status: str = Field(..., description="更新后的状态")


class ProactiveMessageStatsResponse(BaseModel):
    """主动消息统计 — 供管理面板首页徽标。"""

    total: int = Field(0, description="全部消息数")
    unread: int = Field(0, description="未读数")
    by_type: Dict[str, int] = Field(default_factory=dict, description="按类型计数")
    by_severity: Dict[str, int] = Field(default_factory=dict, description="按严重程度计数")
    recent_24h: int = Field(0, description="最近 24 小时新增数")
