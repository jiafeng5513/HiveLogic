# -*- coding: utf-8 -*-
"""
Client authentication endpoints — email/password login issuing Bearer tokens.

Separate from admin auth (cookie-based). Client auth uses Authorization: Bearer
header, controlled by CLIENT_AUTH_ENABLED env toggle.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from dotenv import dotenv_values

from src.repositories.account_repository import get_account_repository

logger = logging.getLogger(__name__)

router = APIRouter()

BEARER_PREFIX = "Bearer "
TOKEN_DEFAULT_EXPIRE_DAYS = 30


def _is_client_auth_enabled() -> bool:
    """Read CLIENT_AUTH_ENABLED from .env (same pattern as admin auth)."""
    from src.config import setup_env
    setup_env()
    env_file = os.getenv("ENV_FILE")
    env_path = os.path.join(os.path.dirname(env_file)) if env_file else None
    if env_path:
        from pathlib import Path
        p = Path(env_path) / ".env"
        if not p.exists():
            return False
        values = dotenv_values(p)
    else:
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent.parent / ".env"
        if not p.exists():
            return False
        values = dotenv_values(p)
    val = (values.get("CLIENT_AUTH_ENABLED") or "").strip().lower()
    return val in ("true", "1", "yes")


def _extract_bearer_token(request: Request) -> Optional[str]:
    """从 Authorization 头提取 Bearer token。"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith(BEARER_PREFIX):
        return None
    return auth_header[len(BEARER_PREFIX):].strip()


def _get_client_account(request: Request):
    """
    从 request.state 获取客户端账号信息（由 AuthMiddleware 设置）。
    返回 (account, tier) 或 None。
    """
    account = getattr(request.state, "client_account", None)
    if account is None:
        return None
    repo = get_account_repository()
    tier = repo.get_account_tier(account.id)
    return account, tier


# ==================== Schemas ====================

class ClientLoginRequest(BaseModel):
    model_config = {"populate_by_name": True}
    email: str = Field(..., description="账号邮箱")
    password: str = Field(..., description="密码")
    device_info: Optional[str] = Field(default=None, alias="deviceInfo", description="设备信息")


class ClientLoginResponse(BaseModel):
    token: str
    token_type: str = "Bearer"
    account: dict
    tier: str


class ClientAccountInfo(BaseModel):
    account: dict
    tier: str
    usage: dict


# ==================== Endpoints ====================

@router.get(
    "/status",
    summary="Client auth status",
    description="Whether client auth is enabled and the current token is valid.",
)
async def client_auth_status(request: Request):
    enabled = _is_client_auth_enabled()
    account_info = None
    if enabled:
        result = _get_client_account(request)
        if result:
            account, tier = result
            account_info = {
                "id": account.id,
                "email": account.email,
                "display_name": account.display_name,
                "tier": tier,
            }
    return {
        "client_auth_enabled": enabled,
        "logged_in": account_info is not None,
        "account": account_info,
    }


@router.post(
    "/login",
    summary="Client login",
    description="Email + password login, returns Bearer token.",
)
async def client_login(request: Request, body: ClientLoginRequest):
    if not _is_client_auth_enabled():
        return JSONResponse(
            status_code=400,
            content={"error": "client_auth_disabled", "message": "Client authentication is not enabled"},
        )

    repo = get_account_repository()
    account = repo.verify_credentials(body.email, body.password)
    if account is None:
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_credentials", "message": "邮箱或密码错误"},
        )

    device_info = body.device_info or request.headers.get("User-Agent", "")[:255]
    token_record, raw_token = repo.create_token(
        account_id=account.id,
        device_info=device_info,
        expires_days=TOKEN_DEFAULT_EXPIRE_DAYS,
    )
    tier = repo.get_account_tier(account.id)

    return ClientLoginResponse(
        token=raw_token,
        account=account.to_dict(),
        tier=tier,
    ).model_dump()


@router.post(
    "/logout",
    summary="Client logout",
    description="Revoke the current Bearer token.",
)
async def client_logout(request: Request):
    token = _extract_bearer_token(request)
    if not token:
        return Response(status_code=204)

    repo = get_account_repository()
    result = repo.validate_token(token)
    if result:
        token_record, _ = result
        repo.revoke_token(token_record.id)
    return Response(status_code=204)


@router.get(
    "/me",
    summary="Current client account",
    description="Return account info, subscription tier, and usage summary.",
)
async def client_me(request: Request):
    result = _get_client_account(request)
    if result is None:
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized", "message": "Valid Bearer token required"},
        )
    account, tier = result
    repo = get_account_repository()
    usage = repo.get_usage_summary(account.id, days=30)
    return {
        "account": account.to_dict(),
        "tier": tier,
        "usage": usage,
    }
