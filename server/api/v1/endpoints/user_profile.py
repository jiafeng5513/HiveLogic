# -*- coding: utf-8 -*-
"""
User profile & long-term note endpoints — Phase D.3 / D.4.

Provides:
- GET/PUT /api/v1/user-profile          — 读取/更新用户画像
- GET    /api/v1/user-profile/notes     — 列出激活的长期笔记
- POST   /api/v1/user-profile/notes     — 新增长期笔记（用户手动或 AI 提取后调用）
- DELETE /api/v1/user-profile/notes/{id} — 禁用（软删除）一条笔记

鉴权：依赖 AuthMiddleware 设置的 ``request.state.client_account``。
未启用客户端鉴权时所有端点返回 401。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_account(request: Request):
    """获取已鉴权的客户端账号，未鉴权返回 401。"""
    account = getattr(request.state, "client_account", None)
    if account is None:
        raise HTTPException(status_code=401, detail="客户端未鉴权，无法访问用户画像")
    return account


# ==================== Schemas ====================


class UserProfileResponse(BaseModel):
    account_id: int
    risk_tolerance: str = "moderate"
    holding_horizon: str = "mid_term"
    preferred_markets: List[str] = Field(default_factory=list)
    preferred_sectors: List[str] = Field(default_factory=list)
    excluded_stocks: List[str] = Field(default_factory=list)
    notes: str = ""


class UpdateUserProfileRequest(BaseModel):
    risk_tolerance: Optional[str] = None
    holding_horizon: Optional[str] = None
    preferred_markets: Optional[List[str]] = None
    preferred_sectors: Optional[List[str]] = None
    excluded_stocks: Optional[List[str]] = None
    notes: Optional[str] = None


class UserNoteResponse(BaseModel):
    id: int
    account_id: int
    content: str
    source: str = "user_explicit"
    category: str = "preference"
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CreateUserNoteRequest(BaseModel):
    content: str = Field(..., min_length=1, description="笔记内容")
    source: str = Field(default="user_explicit")
    category: str = Field(default="preference")


# ==================== Profile endpoints ====================


@router.get("", summary="获取当前用户画像")
async def get_user_profile(request: Request) -> Dict[str, Any]:
    account = _require_account(request)
    try:
        from src.services.user_profile_service import get_user_profile_service

        service = get_user_profile_service()
        profile = service.get_or_create_profile(account.id)
        return profile.to_dict()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[UserProfile] 读取失败")
        raise HTTPException(status_code=500, detail=f"读取用户画像失败: {exc}")


@router.put("", summary="更新当前用户画像")
async def update_user_profile(
    request: Request,
    body: UpdateUserProfileRequest,
) -> Dict[str, Any]:
    account = _require_account(request)
    try:
        from src.services.user_profile_service import get_user_profile_service

        service = get_user_profile_service()
        updates = body.model_dump(exclude_none=True)
        profile = service.update_profile(account.id, updates)
        return profile.to_dict()
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[UserProfile] 更新失败")
        raise HTTPException(status_code=500, detail=f"更新用户画像失败: {exc}")


# ==================== Note endpoints ====================


@router.get("/notes", summary="列出当前用户的长期笔记")
async def list_user_notes(
    request: Request,
    category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    account = _require_account(request)
    try:
        from src.storage import get_db

        return get_db().get_active_user_notes(account.id, category=category)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[UserNote] 列表失败")
        raise HTTPException(status_code=500, detail=f"读取用户笔记失败: {exc}")


@router.post("/notes", summary="新增长期笔记", status_code=201)
async def create_user_note(
    request: Request,
    body: CreateUserNoteRequest,
) -> Dict[str, Any]:
    account = _require_account(request)
    try:
        from src.storage import get_db

        note_id = get_db().add_user_note(
            account_id=account.id,
            content=body.content,
            source=body.source,
            category=body.category,
        )
        notes = get_db().get_active_user_notes(account.id)
        for n in notes:
            if n["id"] == note_id:
                return n
        return {"id": note_id, "account_id": account.id, "content": body.content,
                "source": body.source, "category": body.category, "is_active": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[UserNote] 新增失败")
        raise HTTPException(status_code=500, detail=f"新增用户笔记失败: {exc}")


@router.delete("/notes/{note_id}", summary="禁用（软删除）一条长期笔记")
async def delete_user_note(request: Request, note_id: int) -> Dict[str, Any]:
    account = _require_account(request)
    try:
        from src.storage import get_db

        ok = get_db().deactivate_user_note(note_id, account_id=account.id)
        if not ok:
            raise HTTPException(status_code=404, detail="笔记不存在或无权操作")
        return {"success": True, "note_id": note_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[UserNote] 删除失败")
        raise HTTPException(status_code=500, detail=f"删除用户笔记失败: {exc}")
