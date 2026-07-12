# -*- coding: utf-8 -*-
"""
===================================
内存事件总线 (In-Memory Event Bus)
===================================

职责：
1. 进程内 pub/sub 事件总线（单例，线程安全）
2. Phase E 异动监控引擎发布 AnomalyEvent，下游订阅者消费
3. 轻量级设计：无外部依赖（无 Redis / Kafka），适合内网部署

设计：
- 单例模式，进程全局唯一
- 线程安全（RLock 保护订阅者列表）
- 同步发布：callback 在发布线程内执行（适合轻量处理）
- 主题隔离：不同 topic 的订阅者互不干扰

使用::

    from src.services.event_bus import get_event_bus, EventBus

    bus = get_event_bus()
    bus.subscribe("anomaly", my_handler)
    bus.publish("anomaly", anomaly_event)
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)


class EventBus:
    """进程内 pub/sub 事件总线（单例，线程安全）。"""

    _instance: "EventBus | None" = None
    _init_lock = threading.Lock()

    def __new__(cls) -> "EventBus":
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._subscribers: Dict[str, List[Callable[[Any], None]]] = {}
        self._lock = threading.RLock()
        self._initialized = True
        logger.info("[EventBus] 初始化完成")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def subscribe(self, topic: str, callback: Callable[[Any], None]) -> None:
        """订阅主题。

        Args:
            topic: 主题名称（如 "anomaly", "opportunity"）
            callback: 事件回调函数，接收一个参数（事件对象）
        """
        with self._lock:
            self._subscribers.setdefault(topic, []).append(callback)
        logger.debug("[EventBus] 新订阅者: topic=%s (总计 %d)",
                     topic, len(self._subscribers.get(topic, [])))

    def unsubscribe(self, topic: str, callback: Callable[[Any], None]) -> None:
        """取消订阅。"""
        with self._lock:
            callbacks = self._subscribers.get(topic, [])
            if callback in callbacks:
                callbacks.remove(callback)

    def publish(self, topic: str, event: Any) -> int:
        """发布事件到指定主题的所有订阅者。

        回调在当前线程同步执行。异常被捕获并记录，不影响其他订阅者。

        Returns:
            成功通知的订阅者数量。
        """
        with self._lock:
            callbacks = list(self._subscribers.get(topic, []))

        delivered = 0
        for cb in callbacks:
            try:
                cb(event)
                delivered += 1
            except Exception as exc:
                logger.warning(
                    "[EventBus] 订阅者回调异常 topic=%s: %s", topic, exc
                )
        return delivered

    def subscriber_count(self, topic: str) -> int:
        """返回指定主题的订阅者数量。"""
        with self._lock:
            return len(self._subscribers.get(topic, []))

    def reset(self) -> None:
        """清空所有订阅者（测试用）。"""
        with self._lock:
            self._subscribers.clear()


def get_event_bus() -> EventBus:
    """获取全局 EventBus 单例。"""
    return EventBus()
