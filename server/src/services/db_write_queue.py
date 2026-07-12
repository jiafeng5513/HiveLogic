# -*- coding: utf-8 -*-
"""
SQLite 写入队列（db_write_queue）

7×24 采集场景下，L0 快照 / L1 日线归档 / L2 实时流可能同时写入 market_cache.db。
虽然 WAL 模式允许读写并行，但写写冲突仍会触发 `database is locked`。

本模块通过单例 asyncio.Queue + 单 consumer 协程串行化所有写入：
  - 调用方 enqueue_write(write_fn, *args) → 立即返回 Future
  - consumer 逐个取出，在线程池执行（SQLite 写是阻塞 I/O）
  - 写入失败重试（指数退避，受 SQLITE_WRITE_RETRY_MAX 限制）
  - 队列深度 / 写入计数 / 错误计数 暴露为 metrics

注意：kline_cache_manager 已有进程内 threading.Lock 串行化同步写入，
本队列在 asyncio 层再做一层串行化，二者互补——同步路径走 Lock，异步路径走 Queue。
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

_RETRY_MAX = 3
_RETRY_BASE_DELAY = 0.1


@dataclass
class _WriteTask:
    fn: Callable[..., Any]
    args: tuple
    kwargs: dict
    future: asyncio.Future
    label: str = ""
    retries: int = 0
    enqueued_at: float = field(default_factory=time.time)


@dataclass
class WriteQueueMetrics:
    total_enqueued: int = 0
    total_completed: int = 0
    total_failed: int = 0
    total_retries: int = 0
    current_depth: int = 0
    last_error: str = ""
    last_error_at: float = 0.0


class DbWriteQueue:
    """异步 SQLite 写入队列（单例）"""

    _instance: Optional["DbWriteQueue"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._queue: Optional[asyncio.Queue] = None
        self._consumer_task: Optional[asyncio.Task] = None
        self._running = False
        self._metrics = WriteQueueMetrics()

    @property
    def metrics(self) -> WriteQueueMetrics:
        return self._metrics

    async def start(self):
        if self._running:
            return
        self._running = True
        self._queue = asyncio.Queue()
        self._consumer_task = asyncio.create_task(self._consumer_loop())
        logger.info("[DbWriteQueue] 已启动")

    async def stop(self):
        self._running = False
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None
        if self._queue:
            while not self._queue.empty():
                task = self._queue.get_nowait()
                if not task.future.done():
                    task.future.cancel()
            self._queue = None
        logger.info("[DbWriteQueue] 已停止")

    def enqueue_write(
        self,
        fn: Callable[..., Any],
        *args,
        label: str = "",
        **kwargs,
    ) -> asyncio.Future:
        """
        提交一个写入任务。fn 是同步写入函数（如 kline_cache_manager.upsert_klines），
        将在 consumer 协程中串行执行。返回 Future，调用方可 await 等待完成（也可 fire-and-forget）。
        """
        if not self._running or self._queue is None:
            fut = asyncio.get_event_loop().create_future()
            fut.set_exception(RuntimeError("DbWriteQueue 未启动"))
            return fut
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        task = _WriteTask(fn=fn, args=args, kwargs=kwargs, future=fut, label=label)
        self._queue.put_nowait(task)
        self._metrics.total_enqueued += 1
        self._metrics.current_depth = self._queue.qsize()
        return fut

    async def _consumer_loop(self):
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                task: _WriteTask = await self._queue.get()
            except asyncio.CancelledError:
                break
            self._metrics.current_depth = self._queue.qsize()
            try:
                result = await self._execute_with_retry(loop, task)
                if not task.future.done():
                    task.future.set_result(result)
                self._metrics.total_completed += 1
            except Exception as e:
                if not task.future.done():
                    task.future.set_exception(e)
                self._metrics.total_failed += 1
                self._metrics.last_error = str(e)
                self._metrics.last_error_at = time.time()
                logger.error(
                    "[DbWriteQueue] 写入失败 (label=%s, retries=%d): %s",
                    task.label, task.retries, e,
                )
            finally:
                self._queue.task_done()

    async def _execute_with_retry(self, loop: asyncio.AbstractEventLoop, task: _WriteTask) -> Any:
        last_exc: Optional[Exception] = None
        for attempt in range(_RETRY_MAX + 1):
            try:
                return await loop.run_in_executor(
                    None, task.fn, *task.args, **task.kwargs,
                )
            except Exception as e:
                last_exc = e
                if attempt < _RETRY_MAX:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    logger.debug(
                        "[DbWriteQueue] 写入重试 (label=%s, attempt=%d, delay=%.2fs): %s",
                        task.label, attempt + 1, delay, e,
                    )
                    self._metrics.total_retries += 1
                    task.retries += 1
                    await asyncio.sleep(delay)
        raise last_exc


def get_db_write_queue() -> DbWriteQueue:
    return DbWriteQueue()


async def enqueue_write(
    fn: Callable[..., Any],
    *args,
    label: str = "",
    **kwargs,
) -> asyncio.Future:
    return get_db_write_queue().enqueue_write(fn, *args, label=label, **kwargs)
