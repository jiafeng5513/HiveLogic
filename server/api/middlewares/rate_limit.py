# -*- coding: utf-8 -*-
"""
Rate limiting middleware.

Sliding-window rate limiter applied to /api/v1/* data endpoints.
Two buckets:
1. Per-IP: default 60 req/min (overridable via RATE_LIMIT_PER_MINUTE)
2. Per-account: default 120 req/min (overridable via RATE_LIMIT_ACCOUNT_PER_MINUTE)

Admin paths (/api/v1/admin/*) and auth paths are exempt — admin rate
limiting happens at the brute-force layer in src/auth.py.

When CLIENT_AUTH_ENABLED and a valid Bearer token is present, the account
bucket applies; otherwise the IP bucket applies.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


RATE_LIMIT_PER_MINUTE = _env_int("RATE_LIMIT_PER_MINUTE", 60)
RATE_LIMIT_ACCOUNT_PER_MINUTE = _env_int("RATE_LIMIT_ACCOUNT_PER_MINUTE", 120)

_EXEMPT_PREFIXES = (
    "/api/health",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
    "/ws/",
    "/assets/",
    "/api/v1/admin/",
    "/api/v1/auth/",
    "/api/v1/client-auth/",
)


class _SlidingWindow:
    """Thread-safe sliding-window counter."""

    def __init__(self, max_requests: int, window_seconds: int = _WINDOW_SECONDS):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> None:
        q = self._buckets.get(key)
        if not q:
            return
        cutoff = now - self.window_seconds
        while q and q[0] < cutoff:
            q.popleft()
        if not q:
            del self._buckets[key]

    def check(self, key: str) -> tuple[bool, int, int]:
        """Return (allowed, current_count, limit)."""
        now = time.time()
        with self._lock:
            self._prune(key, now)
            q = self._buckets.get(key)
            current = len(q) if q else 0
            if current >= self.max_requests:
                return False, current, self.max_requests
            if q is None:
                q = deque()
                self._buckets[key] = q
            q.append(now)
            return True, current + 1, self.max_requests

    def cleanup_all(self) -> None:
        now = time.time()
        with self._lock:
            for key in list(self._buckets.keys()):
                self._prune(key, now)


_ip_limiter = _SlidingWindow(RATE_LIMIT_PER_MINUTE)
_account_limiter = _SlidingWindow(RATE_LIMIT_ACCOUNT_PER_MINUTE)
_last_cleanup = time.time()


def _is_exempt(path: str) -> bool:
    for prefix in _EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _get_client_ip(request: Request) -> str:
    if os.getenv("TRUST_X_FORWARDED_FOR", "false").lower() == "true":
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    if request.client:
        return request.client.host or "127.0.0.1"
    return "127.0.0.1"


def _get_account_id(request: Request) -> Optional[int]:
    account = getattr(request.state, "client_account", None)
    if account is not None:
        return getattr(account, "id", None)
    return None


def _maybe_cleanup() -> None:
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup > 300:
        _ip_limiter.cleanup_all()
        _account_limiter.cleanup_all()
        _last_cleanup = now


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforce per-IP and per-account rate limits on data API endpoints."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ):
        path = request.url.path
        if _is_exempt(path) or not path.startswith("/api/v1/"):
            return await call_next(request)

        _maybe_cleanup()

        account_id = _get_account_id(request)
        if account_id is not None:
            allowed, current, limit = _account_limiter.check(f"acct:{account_id}")
            bucket = "account"
        else:
            ip = _get_client_ip(request)
            allowed, current, limit = _ip_limiter.check(f"ip:{ip}")
            bucket = "ip"

        if not allowed:
            logger.warning(
                "[RateLimit] Blocked %s bucket=%s current=%d limit=%d path=%s",
                account_id if account_id else _get_client_ip(request),
                bucket,
                current,
                limit,
                path,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limited",
                    "message": f"请求过于频繁，每分钟限 {limit} 次，请稍后重试",
                    "retry_after_seconds": _WINDOW_SECONDS,
                    "bucket": bucket,
                    "limit": limit,
                },
                headers={"Retry-After": str(_WINDOW_SECONDS)},
            )

        return await call_next(request)


def add_rate_limit_middleware(app) -> None:
    app.add_middleware(RateLimitMiddleware)
