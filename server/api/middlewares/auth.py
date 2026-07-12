# -*- coding: utf-8 -*-
"""
Auth middleware: protect /api/v1/* when admin or client auth is enabled.

Two auth branches coexist:
1. Admin auth (cookie-based, dsa_session) — toggled by ADMIN_AUTH_ENABLED
2. Client auth (Bearer token, Authorization header) — toggled by CLIENT_AUTH_ENABLED

Either branch grants access. request.state marks which branch succeeded:
- request.state.admin_session = True (admin cookie)
- request.state.client_account = Account (client token)
"""

from __future__ import annotations

import logging
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.auth import COOKIE_NAME, is_auth_enabled, verify_session

logger = logging.getLogger(__name__)

EXEMPT_PATHS = frozenset({
    "/api/v1/auth/login",
    "/api/v1/auth/status",
    "/api/v1/auth/settings",
    "/api/v1/client-auth/status",
    "/api/v1/client-auth/login",
    "/api/health",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
})

BEARER_PREFIX = "Bearer "


def _path_exempt(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    return normalized in EXEMPT_PATHS


def _is_client_auth_enabled() -> bool:
    """Read CLIENT_AUTH_ENABLED from .env (lazy import to avoid circular deps)."""
    try:
        from api.v1.endpoints.client_auth import _is_client_auth_enabled as _check
        return _check()
    except Exception:
        return False


def _validate_client_token(request: Request) -> bool:
    """If Bearer token present and valid, set request.state.client_account. Returns True if valid."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith(BEARER_PREFIX):
        return False
    raw_token = auth_header[len(BEARER_PREFIX):].strip()
    if not raw_token:
        return False
    try:
        from src.repositories.account_repository import get_account_repository
        result = get_account_repository().validate_token(raw_token)
        if result is None:
            return False
        _, account = result
        request.state.client_account = account
        return True
    except Exception as e:
        logger.warning("[AuthMiddleware] Client token validation failed: %s", e)
        return False


def _is_admin_path(path: str) -> bool:
    """Admin-only endpoints require admin session, not client token."""
    return path.startswith("/api/v1/admin/")


class AuthMiddleware(BaseHTTPMiddleware):
    """Require valid admin session or client Bearer token for /api/v1/*."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ):
        admin_enabled = is_auth_enabled()
        client_enabled = _is_client_auth_enabled()

        if not admin_enabled and not client_enabled:
            return await call_next(request)

        path = request.url.path
        if _path_exempt(path):
            return await call_next(request)

        if not path.startswith("/api/v1/"):
            return await call_next(request)

        admin_ok = False
        client_ok = False

        if admin_enabled:
            cookie_val = request.cookies.get(COOKIE_NAME)
            if cookie_val and verify_session(cookie_val):
                admin_ok = True
                request.state.admin_session = True

        if client_enabled and not admin_ok:
            client_ok = _validate_client_token(request)

        if not admin_ok and not client_ok:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "unauthorized",
                    "message": "Login required",
                },
            )

        if _is_admin_path(path) and not admin_ok:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "forbidden",
                    "message": "Admin session required",
                },
            )

        return await call_next(request)


def add_auth_middleware(app):
    """Add auth middleware to protect API routes."""
    app.add_middleware(AuthMiddleware)
