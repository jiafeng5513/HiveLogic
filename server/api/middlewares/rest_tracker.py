# -*- coding: utf-8 -*-
"""
REST client tracker: records recent API callers for admin monitoring.
Bounded ring buffer, no persistence — purely for the admin clients panel.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Dict, List

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

_EXEMPT_PREFIXES = ("/api/health", "/health", "/docs", "/redoc", "/openapi.json", "/favicon.ico", "/ws/", "/assets/")


class RestClientTracker:
    """Thread-safe bounded ring buffer of recent REST API calls."""

    def __init__(self, max_entries: int = 200):
        self._entries: deque[Dict[str, Any]] = deque(maxlen=max_entries)
        self._lock = threading.Lock()
        self._ip_index: Dict[str, Dict[str, Any]] = {}

    def record(self, ip: str, method: str, path: str, status_code: int, duration_ms: float):
        entry = {
            "ip": ip,
            "method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 1),
            "timestamp": time.time(),
        }
        with self._lock:
            self._entries.append(entry)
            agg = self._ip_index.setdefault(ip, {"ip": ip, "request_count": 0, "last_active": 0.0})
            agg["request_count"] += 1
            agg["last_active"] = entry["timestamp"]
            agg["last_path"] = path
            agg["last_method"] = method

    def get_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._entries)
        items.reverse()
        return items[:limit]

    def get_unique_clients(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._ip_index.values())


class RestClientTrackerMiddleware(BaseHTTPMiddleware):
    """Record each REST API call into the tracker."""

    def __init__(self, app, tracker: RestClientTracker):
        super().__init__(app)
        self._tracker = tracker

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        for prefix in _EXEMPT_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        t0 = time.time()
        response = await call_next(request)
        duration_ms = (time.time() - t0) * 1000

        ip = request.client.host if request.client else "unknown"
        if "x-forwarded-for" in request.headers:
            ip = request.headers["x-forwarded-for"].split(",")[0].strip()

        self._tracker.record(ip, request.method, path, response.status_code, duration_ms)
        return response
