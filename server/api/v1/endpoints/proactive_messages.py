# -*- coding: utf-8 -*-
"""
===================================
主动消息中心接口 (Phase E.4)
===================================

职责：
1. GET  /api/v1/proactive-messages          分页列表（支持按类型/状态/标的筛选）
2. GET  /api/v1/proactive-messages/stats     统计（徽标/首页）
3. GET  /api/v1/proactive-messages/{id}      详情（自动标记已读）
4. PATCH /api/v1/proactive-messages/{id}     标记 dismissed / acted
5. POST /api/v1/proactive-messages/read-all  全部标记已读

推送通道接入（server_refine_plan Phase B 完成后）将复用本接口的数据。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.deps import get_db
from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.proactive_message import (
    ProactiveMessageActionRequest,
    ProactiveMessageActionResponse,
    ProactiveMessageDetailResponse,
    ProactiveMessageItem,
    ProactiveMessageListResponse,
    ProactiveMessageStatsResponse,
)
from src.models.proactive_message import ProactiveMessage

logger = logging.getLogger(__name__)

router = APIRouter()

_VALID_ACTION_STATUSES = {"read", "dismissed", "acted"}


# ======================================================================
# 列表
# ======================================================================

@router.get(
    "",
    response_model=ProactiveMessageListResponse,
    responses={
        200: {"description": "主动消息列表"},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取主动消息列表",
    description="分页获取主动消息（异动分析 + 机会扫描），支持按类型/状态/标的筛选",
)
def list_proactive_messages(
    message_type: Optional[str] = Query(None, description="类型筛选: anomaly_response / opportunity"),
    status: Optional[str] = Query(None, description="状态筛选: unread / read / dismissed / acted"),
    symbol: Optional[str] = Query(None, description="标的代码筛选"),
    severity: Optional[str] = Query(None, description="严重程度筛选: info / warning / critical"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
) -> ProactiveMessageListResponse:
    try:
        q = db.query(ProactiveMessage)
        if message_type:
            q = q.filter(ProactiveMessage.message_type == message_type)
        if status:
            q = q.filter(ProactiveMessage.status == status)
        if symbol:
            q = q.filter(ProactiveMessage.symbol == symbol)
        if severity:
            q = q.filter(ProactiveMessage.trigger_severity == severity)

        total = q.count()
        unread_count = (
            db.query(func.count(ProactiveMessage.id))
            .filter(ProactiveMessage.status == "unread")
            .scalar()
            or 0
        )

        items = (
            q.order_by(ProactiveMessage.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return ProactiveMessageListResponse(
            total=total,
            page=page,
            limit=page_size,
            unread_count=unread_count,
            items=[_to_item(m) for m in items],
        )
    except Exception as e:
        logger.error(f"查询主动消息列表失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"查询主动消息列表失败: {str(e)}"},
        )


# ======================================================================
# 统计
# ======================================================================

@router.get(
    "/stats",
    response_model=ProactiveMessageStatsResponse,
    responses={
        200: {"description": "主动消息统计"},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取主动消息统计",
    description="供管理面板徽标/首页使用：总数、未读、按类型/严重程度计数、最近 24h 新增",
)
def get_proactive_stats(
    db: Session = Depends(get_db),
) -> ProactiveMessageStatsResponse:
    try:
        total = db.query(func.count(ProactiveMessage.id)).scalar() or 0
        unread = (
            db.query(func.count(ProactiveMessage.id))
            .filter(ProactiveMessage.status == "unread")
            .scalar()
            or 0
        )

        # 按类型计数
        type_rows = (
            db.query(
                ProactiveMessage.message_type,
                func.count(ProactiveMessage.id),
            )
            .group_by(ProactiveMessage.message_type)
            .all()
        )
        by_type = {t or "unknown": c for t, c in type_rows}

        # 按严重程度计数
        sev_rows = (
            db.query(
                ProactiveMessage.trigger_severity,
                func.count(ProactiveMessage.id),
            )
            .group_by(ProactiveMessage.trigger_severity)
            .all()
        )
        by_severity = {s or "unknown": c for s, c in sev_rows}

        # 最近 24h 新增
        cutoff = datetime.now() - timedelta(hours=24)
        recent_24h = (
            db.query(func.count(ProactiveMessage.id))
            .filter(ProactiveMessage.created_at >= cutoff)
            .scalar()
            or 0
        )

        return ProactiveMessageStatsResponse(
            total=total,
            unread=unread,
            by_type=by_type,
            by_severity=by_severity,
            recent_24h=recent_24h,
        )
    except Exception as e:
        logger.error(f"查询主动消息统计失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"查询主动消息统计失败: {str(e)}"},
        )


# ======================================================================
# 详情（自动标记已读）
# ======================================================================

@router.get(
    "/{message_id}",
    response_model=ProactiveMessageDetailResponse,
    responses={
        200: {"description": "主动消息详情"},
        404: {"description": "消息不存在", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="获取主动消息详情",
    description="获取单条主动消息详情。若消息状态为 unread，访问时自动标记为 read。",
)
def get_proactive_message_detail(
    message_id: int,
    db: Session = Depends(get_db),
) -> ProactiveMessageDetailResponse:
    try:
        msg = db.query(ProactiveMessage).filter(ProactiveMessage.id == message_id).first()
        if msg is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "not_found", "message": f"主动消息 {message_id} 不存在"},
            )

        # 自动标记已读
        if msg.status == "unread":
            msg.status = "read"
            msg.read_at = datetime.now()
            db.commit()
            db.refresh(msg)

        return ProactiveMessageDetailResponse(item=_to_item(msg))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询主动消息详情失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"查询主动消息详情失败: {str(e)}"},
        )


# ======================================================================
# 标记操作
# ======================================================================

@router.patch(
    "/{message_id}",
    response_model=ProactiveMessageActionResponse,
    responses={
        200: {"description": "操作成功"},
        400: {"description": "非法状态", "model": ErrorResponse},
        404: {"description": "消息不存在", "model": ErrorResponse},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="标记主动消息状态",
    description="将消息标记为 dismissed（忽略）或 acted（已采纳）。read 状态由详情接口自动设置。",
)
def update_proactive_message_status(
    message_id: int,
    request: ProactiveMessageActionRequest,
    db: Session = Depends(get_db),
) -> ProactiveMessageActionResponse:
    if request.status not in _VALID_ACTION_STATUSES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_params",
                "message": f"非法状态 {request.status!r}，允许: {sorted(_VALID_ACTION_STATUSES)}",
            },
        )

    try:
        msg = db.query(ProactiveMessage).filter(ProactiveMessage.id == message_id).first()
        if msg is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "not_found", "message": f"主动消息 {message_id} 不存在"},
            )

        msg.status = request.status
        if request.status == "read" and msg.read_at is None:
            msg.read_at = datetime.now()
        db.commit()

        return ProactiveMessageActionResponse(
            success=True, id=message_id, status=msg.status
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新主动消息状态失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"更新主动消息状态失败: {str(e)}"},
        )


# ======================================================================
# 全部已读
# ======================================================================

@router.post(
    "/read-all",
    response_model=ProactiveMessageActionResponse,
    responses={
        200: {"description": "全部标记已读结果"},
        500: {"description": "服务器错误", "model": ErrorResponse},
    },
    summary="全部标记已读",
    description="将所有 unread 状态的主动消息标记为 read。",
)
def mark_all_read(
    db: Session = Depends(get_db),
) -> ProactiveMessageActionResponse:
    try:
        now = datetime.now()
        updated = (
            db.query(ProactiveMessage)
            .filter(ProactiveMessage.status == "unread")
            .update(
                {ProactiveMessage.status: "read", ProactiveMessage.read_at: now},
                synchronize_session=False,
            )
        )
        db.commit()

        return ProactiveMessageActionResponse(
            success=True, id=0, status=f"updated={updated}"
        )
    except Exception as e:
        logger.error(f"全部标记已读失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": f"全部标记已读失败: {str(e)}"},
        )


# ======================================================================
# 辅助
# ======================================================================

def _to_item(m: ProactiveMessage) -> ProactiveMessageItem:
    """ORM → Pydantic item。"""
    return ProactiveMessageItem(
        id=m.id,
        message_type=m.message_type,
        symbol=m.symbol,
        symbol_name=m.symbol_name or "",
        trigger_type=m.trigger_type or "",
        trigger_severity=m.trigger_severity or "",
        trigger_summary=m.trigger_summary or "",
        analysis_content=m.analysis_content or "",
        analysis_summary=m.analysis_summary or "",
        signal=m.signal or "",
        confidence=m.confidence or 0.0,
        context=_parse_context(m.context_json),
        status=m.status or "unread",
        account_id=m.account_id,
        created_at=m.created_at.isoformat() if m.created_at else None,
        read_at=m.read_at.isoformat() if m.read_at else None,
    )


def _parse_context(context_json: Optional[str]) -> dict:
    if not context_json:
        return {}
    import json
    try:
        result = json.loads(context_json)
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}
