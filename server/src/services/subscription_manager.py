# -*- coding: utf-8 -*-
"""
订阅管理器（SubscriptionManager）

职责：
1. 引用计数 — 每个标的（按 channel）维护订阅它的 client_id 集合
2. 多路复用 — 一个标的上游只订阅一次，扇出给 N 个客户端
3. LRU 退订 — 无订阅者后不立即退订上游，等待 grace period；期间有新客户端订阅则取消退订

设计要点：
- 上游订阅/退订由 ref count 0↔1 边界触发，通过回调通知调用方
- LRU grace period 避免客户端频繁断连重连导致上游订阅抖动
- 线程安全：内部用 asyncio.Lock 保护（所有操作在事件循环中调用）
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class _SubEntry:
    clients: Set[str] = field(default_factory=set)
    last_active: float = field(default_factory=time.time)
    pending_evict: bool = False


class SubscriptionManager:
    """
    引用计数 + 多路复用 + LRU 退订的订阅管理器。

    channel 维度独立计数（如 "quotes" / "depth"），同一标的可同时在多个 channel 被订阅。
    """

    def __init__(
        self,
        lru_grace_seconds: float = 60.0,
        on_upstream_subscribe: Optional[Callable[[str, str], Awaitable[None]]] = None,
        on_upstream_unsubscribe: Optional[Callable[[str, str], Awaitable[None]]] = None,
    ):
        self._lru_grace = lru_grace_seconds
        self._on_upstream_subscribe = on_upstream_subscribe
        self._on_upstream_unsubscribe = on_upstream_unsubscribe
        self._subs: Dict[str, Dict[str, _SubEntry]] = defaultdict(dict)
        self._lock = asyncio.Lock()
        self._evict_task: Optional[asyncio.Task] = None

    async def subscribe(
        self,
        client_id: str,
        channel: str,
        symbols: list,
    ) -> Set[Tuple[str, str]]:
        """
        客户端订阅一批标的。返回需要新上游订阅的 (channel, symbol) 集合
        （即 ref count 从 0→1 的标的）。
        """
        newly_subscribed: Set[Tuple[str, str]] = set()
        async with self._lock:
            chan_map = self._subs[channel]
            for sym in symbols:
                entry = chan_map.get(sym)
                if entry is None:
                    entry = _SubEntry()
                    chan_map[sym] = entry
                was_empty = len(entry.clients) == 0
                entry.clients.add(client_id)
                entry.last_active = time.time()
                entry.pending_evict = False
                if was_empty:
                    newly_subscribed.add((channel, sym))
        if newly_subscribed and self._on_upstream_subscribe:
            for ch, sym in newly_subscribed:
                try:
                    await self._on_upstream_subscribe(ch, sym)
                except Exception as e:
                    logger.warning("[SubMgr] on_upstream_subscribe(%s,%s) failed: %s", ch, sym, e)
        return newly_subscribed

    async def unsubscribe(
        self,
        client_id: str,
        channel: str,
        symbols: list,
    ) -> Set[Tuple[str, str]]:
        """
        客户端退订一批标的。返回可被 LRU 退订的 (channel, symbol) 集合
        （即 ref count 降为 0、进入 grace period 的标的）。实际上游退订由 evict_expired 执行。
        """
        entered_grace: Set[Tuple[str, str]] = set()
        async with self._lock:
            chan_map = self._subs[channel]
            for sym in symbols:
                entry = chan_map.get(sym)
                if entry is None:
                    continue
                entry.clients.discard(client_id)
                if not entry.clients:
                    entry.pending_evict = True
                    entry.last_active = time.time()
                    entered_grace.add((channel, sym))
        return entered_grace

    async def remove_client(self, client_id: str) -> Set[Tuple[str, str]]:
        """
        移除客户端的所有订阅（断连时调用）。返回进入 grace period 的 (channel, symbol) 集合。
        """
        entered_grace: Set[Tuple[str, str]] = set()
        async with self._lock:
            for channel, chan_map in self._subs.items():
                for sym, entry in chan_map.items():
                    if client_id in entry.clients:
                        entry.clients.discard(client_id)
                        if not entry.clients:
                            entry.pending_evict = True
                            entry.last_active = time.time()
                            entered_grace.add((channel, sym))
        return entered_grace

    async def evict_expired(self) -> Set[Tuple[str, str]]:
        """
        扫描所有 pending_evict 标的，退订 grace period 已过期的。
        返回实际被上游退订的 (channel, symbol) 集合。
        """
        evicted: Set[Tuple[str, str]] = set()
        now = time.time()
        to_remove: list = []
        async with self._lock:
            for channel, chan_map in self._subs.items():
                for sym, entry in chan_map.items():
                    if entry.pending_evict and not entry.clients:
                        if now - entry.last_active >= self._lru_grace:
                            evicted.add((channel, sym))
                            to_remove.append((channel, sym))
            for channel, sym in to_remove:
                self._subs[channel].pop(sym, None)
        if evicted and self._on_upstream_unsubscribe:
            for ch, sym in evicted:
                try:
                    await self._on_upstream_unsubscribe(ch, sym)
                except Exception as e:
                    logger.warning("[SubMgr] on_upstream_unsubscribe(%s,%s) failed: %s", ch, sym, e)
        return evicted

    def get_active_symbols(self, channel: str) -> Set[str]:
        """获取某 channel 当前有客户端订阅的标的集合（不含 grace period 内的）"""
        chan_map = self._subs.get(channel, {})
        return {sym for sym, entry in chan_map.items() if entry.clients}

    def get_client_symbols(self, client_id: str, channel: str) -> Set[str]:
        """获取某客户端在某 channel 订阅的标的集合"""
        chan_map = self._subs.get(channel, {})
        return {sym for sym, entry in chan_map.items() if client_id in entry.clients}

    def get_all_active(self) -> Dict[str, Set[str]]:
        """获取所有 channel 的活跃标的（含 grace period 内的）"""
        result: Dict[str, Set[str]] = {}
        for channel, chan_map in self._subs.items():
            result[channel] = set(chan_map.keys())
        return result

    def get_status(self) -> Dict[str, Any]:
        """获取管理器状态摘要"""
        status: Dict[str, Any] = {}
        for channel, chan_map in self._subs.items():
            active = sum(1 for e in chan_map.values() if e.clients)
            grace = sum(1 for e in chan_map.values() if e.pending_evict and not e.clients)
            total_clients: Set[str] = set()
            for e in chan_map.values():
                total_clients.update(e.clients)
            status[channel] = {
                "active_symbols": active,
                "grace_symbols": grace,
                "clients": len(total_clients),
            }
        return status

    async def start_eviction_loop(self, interval: float = 15.0):
        """启动定期 eviction 协程（在 FastAPI lifespan 中调用）"""
        if self._evict_task and not self._evict_task.done():
            return
        self._evict_task = asyncio.create_task(self._eviction_loop(interval))

    async def stop_eviction_loop(self):
        if self._evict_task:
            self._evict_task.cancel()
            try:
                await self._evict_task
            except asyncio.CancelledError:
                pass
            self._evict_task = None

    async def _eviction_loop(self, interval: float):
        while True:
            try:
                await asyncio.sleep(interval)
                evicted = await self.evict_expired()
                if evicted:
                    logger.debug("[SubMgr] evicted %d expired symbols", len(evicted))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("[SubMgr] eviction loop error: %s", e)
