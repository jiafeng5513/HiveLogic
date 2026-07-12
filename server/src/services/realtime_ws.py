# -*- coding: utf-8 -*-
"""
===================================
WebSocket 实时行情中继服务 (Realtime WS Relay)
===================================

职责:
1. 后端连接 TickFlow WebSocket (上游), 持有 API Key (安全)
2. 前端通过本地 WebSocket ws://127.0.0.1:8100/ws/market 订阅
3. 多前端页面共享一条上游连接, 减少 API 配额消耗
4. 自动重连 + 订阅恢复
5. 不持有 API Key 的情况下, 降级为 REST 轮询模式

协议:
  前端 → 后端:
    {"op": "subscribe", "channel": "quotes", "symbols": ["600519", "000001"]}
    {"op": "unsubscribe", "channel": "quotes", "symbols": ["600519"]}
    {"op": "subscribe", "channel": "depth", "symbols": ["600519"]}
    {"op": "ping"}

  后端 → 前端:
    {"op": "quotes", "data": [{ symbol, name, price, change, ... }]}
    {"op": "depth", "data": { symbol, bids: [...], asks: [...] }}
    {"op": "pong"}
    {"op": "error", "message": "..."}
    {"op": "status", "upstream": "connected" | "disconnected" | "polling"}
"""

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket, WebSocketDisconnect

from src.services.subscription_manager import SubscriptionManager

logger = logging.getLogger(__name__)


@dataclass
class _CandleBuilder:
    """单标的 1 分钟 K 线增量构建器（从 tick quotes 聚合）"""
    symbol: str
    market: str
    minute_ts: int = 0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    amount: float = 0.0
    has_data: bool = False

    def update(self, price: float, vol: float = 0.0, amt: float = 0.0, ts_ms: int = 0):
        bucket = (ts_ms // 60000) * 60000 if ts_ms else (int(time.time() * 1000) // 60000) * 60000
        if self.minute_ts == 0:
            self.minute_ts = bucket
            self.open = self.high = self.low = self.close = price
            self.volume = vol
            self.amount = amt
            self.has_data = True
            return
        if bucket != self.minute_ts:
            return
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += vol
        self.amount += amt

    def to_kline(self, is_complete: bool = True) -> Dict[str, Any]:
        return {
            "timestamp": self.minute_ts,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount,
            "is_complete": is_complete,
        }


class RealtimeWSRelay:
    """WebSocket 实时行情中继服务 (单例)"""

    _instance: Optional["RealtimeWSRelay"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 前端客户端管理
        self._clients: Set[WebSocket] = set()
        # 每个客户端的订阅: {ws: {"quotes": set(...), "depth": set(...)}}（用于按客户端分发）
        self._subscriptions: Dict[WebSocket, Dict[str, Set[str]]] = {}
        # ws → 订阅管理器使用的稳定 client_id
        self._client_ids: Dict[WebSocket, str] = {}

        # 订阅管理器：引用计数 + 多路复用 + LRU grace 退订（聚合订阅的真相源）
        grace = float(os.environ.get("REALTIME_LRU_GRACE_SECONDS", "60"))
        self._submgr = SubscriptionManager(
            lru_grace_seconds=grace,
            on_upstream_subscribe=self._on_upstream_sub,
            on_upstream_unsubscribe=self._on_upstream_unsub,
        )
        self._evict_task: Optional[asyncio.Task] = None

        # 上游 TickFlow WebSocket 状态
        self._upstream_ws = None
        self._upstream_task: Optional[asyncio.Task] = None
        self._upstream_connected = False
        self._reconnect_delay = 1.0

        # 轮询 fallback
        self._polling_task: Optional[asyncio.Task] = None
        self._polling_interval = 5.0  # 5 秒轮询

        # 配置
        self._api_key = os.environ.get("TICKFLOW_API_KEY", "")
        self._upstream_url = "wss://api.tickflow.org/v1/ws/stream"

        # 实时 tick → 1m K线聚合（写缓存）
        self._candle_builders: Dict[str, _CandleBuilder] = {}
        self._candle_flush_task: Optional[asyncio.Task] = None
        self._candle_cache_enabled = os.environ.get("REALTIME_CACHE_ENABLED", "true").lower() == "true"

    @property
    def has_api_key(self) -> bool:
        return bool(self._api_key.strip())

    @property
    def mode(self) -> str:
        """当前工作模式: websocket / polling / idle"""
        if self._upstream_connected:
            return "websocket"
        if self._polling_task and not self._polling_task.done():
            return "polling"
        return "idle"

    # ==================== 聚合订阅（由订阅管理器派生） ====================

    @property
    def _aggregated_quotes(self) -> Set[str]:
        """quotes 频道当前需上游保活的标的（含 grace 期内）。"""
        return self._submgr.get_all_active().get("quotes", set())

    @property
    def _aggregated_depth(self) -> Set[str]:
        """depth 频道当前需上游保活的标的（含 grace 期内）。"""
        return self._submgr.get_all_active().get("depth", set())

    async def _on_upstream_sub(self, channel: str, symbol: str):
        """订阅管理器回调：某标的引用计数 0→1，需向上游订阅。"""
        if self._upstream_connected:
            await self._upstream_subscribe(channel, [symbol])

    async def _on_upstream_unsub(self, channel: str, symbol: str):
        """订阅管理器回调：某标的 grace 期满被退订，向上游退订。"""
        if self._upstream_connected:
            await self._upstream_unsubscribe(channel, [symbol])

    def reload_config(self):
        """重新加载配置 (API Key 变更后调用)"""
        new_key = os.environ.get("TICKFLOW_API_KEY", "")
        if new_key != self._api_key:
            self._api_key = new_key
            logger.info("[RealtimeWS] API Key 已更新, 重连上游")
            # 触发重连
            asyncio.ensure_future(self._reconnect_upstream())

    # ==================== 前端 WebSocket 管理 ====================

    async def handle_client(self, ws: WebSocket):
        """处理一个前端 WebSocket 连接"""
        await ws.accept()
        self._clients.add(ws)
        self._subscriptions[ws] = {"quotes": set(), "depth": set()}
        self._client_ids[ws] = uuid.uuid4().hex
        logger.info("[RealtimeWS] 新客户端连接, 当前 %d 个", len(self._clients))

        # 通知客户端当前上游状态
        await self._send_to_client(ws, {
            "op": "status",
            "upstream": self.mode,
        })

        try:
            while True:
                raw = await ws.receive_text()
                await self._handle_client_message(ws, raw)
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.warning("[RealtimeWS] 客户端异常: %s", e)
        finally:
            await self._remove_client(ws)

    async def _handle_client_message(self, ws: WebSocket, raw: str):
        """处理前端发来的消息"""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await self._send_to_client(ws, {"op": "error", "message": "无效 JSON"})
            return

        op = msg.get("op", "")

        if op == "ping":
            await self._send_to_client(ws, {"op": "pong"})
            return

        if op == "subscribe":
            channel = msg.get("channel", "quotes")
            symbols = msg.get("symbols", [])
            if not isinstance(symbols, list):
                symbols = [symbols]
            self._subscriptions[ws].setdefault(channel, set()).update(symbols)
            cid = self._client_ids.get(ws)
            if cid:
                # 引用计数 0→1 时由管理器回调触发上游订阅
                await self._submgr.subscribe(cid, channel, symbols)
            self._ensure_transports()
            return

        if op == "unsubscribe":
            channel = msg.get("channel", "quotes")
            symbols = msg.get("symbols", [])
            if not isinstance(symbols, list):
                symbols = [symbols]
            sub_set = self._subscriptions[ws].get(channel, set())
            for s in symbols:
                sub_set.discard(s)
            cid = self._client_ids.get(ws)
            if cid:
                # 引用计数降为 0 进入 grace；实际上游退订由 eviction 循环完成
                await self._submgr.unsubscribe(cid, channel, symbols)
            return

        await self._send_to_client(ws, {"op": "error", "message": f"未知操作: {op}"})

    async def _remove_client(self, ws: WebSocket):
        """移除一个客户端连接"""
        self._clients.discard(ws)
        self._subscriptions.pop(ws, None)
        cid = self._client_ids.pop(ws, None)
        if cid:
            # 该客户端所有订阅进入 grace；实际退订由 eviction 循环完成
            await self._submgr.remove_client(cid)
        logger.info("[RealtimeWS] 客户端断开, 剩余 %d 个", len(self._clients))

    # ==================== 传输层管理（上游 WS / 轮询） ====================

    def _ensure_transports(self):
        """有活跃订阅但上游未连通时，启动轮询并尝试连接上游。"""
        if (self._aggregated_quotes or self._aggregated_depth) and not self._upstream_connected:
            self._ensure_polling()
            self._ensure_upstream()

    def _maybe_stop_transports(self):
        """无任何活跃/grace 订阅时，停止轮询并取消上游连接任务。"""
        if not self._aggregated_quotes and not self._aggregated_depth:
            self._stop_polling()
            if self._upstream_task and not self._upstream_task.done():
                self._upstream_task.cancel()

    # ==================== 订阅 LRU 退订（eviction） ====================

    def start_subscription_eviction_loop(self, interval: float = 15.0):
        """启动订阅 grace 退订循环（供 FastAPI lifespan 调用）。"""
        if self._evict_task and not self._evict_task.done():
            return
        self._evict_task = asyncio.ensure_future(self._subscription_evict_loop(interval))

    async def stop_subscription_eviction_loop(self):
        if self._evict_task:
            self._evict_task.cancel()
            try:
                await self._evict_task
            except asyncio.CancelledError:
                pass
            self._evict_task = None

    async def _subscription_evict_loop(self, interval: float):
        """周期性退订 grace 期满的标的，并在无订阅时收敛传输层。"""
        while True:
            try:
                await asyncio.sleep(interval)
                evicted = await self._submgr.evict_expired()
                if evicted:
                    logger.debug("[RealtimeWS] LRU 退订 %d 个标的", len(evicted))
                self._maybe_stop_transports()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("[RealtimeWS] eviction loop error: %s", e)

    # ==================== 上游 TickFlow WebSocket ====================

    def _ensure_upstream(self):
        """确保上游连接任务在运行"""
        if not self.has_api_key:
            return  # 无 API Key 则只走轮询
        if self._upstream_task is None or self._upstream_task.done():
            self._upstream_task = asyncio.ensure_future(self._upstream_loop())

    async def _upstream_loop(self):
        """上游 WebSocket 连接循环 (自动重连)"""
        while self._aggregated_quotes or self._aggregated_depth:
            try:
                await self._connect_upstream()
            except asyncio.CancelledError:
                break
            except (AttributeError, RuntimeError) as e:
                # websockets 14+ cleanup bug: 'ClientConnection' has no attribute 'recv_messages'
                logger.debug("[RealtimeWS] 上游清理异常 (已忽略): %s", e)
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60)
            except Exception as e:
                logger.warning("[RealtimeWS] 上游连接失败: %s, %s秒后重试",
                               e, self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60)

    async def _connect_upstream(self):
        """建立上游 TickFlow WebSocket 连接"""
        import websockets

        url = f"{self._upstream_url}?api_key={self._api_key}"
        logger.info("[RealtimeWS] 连接上游 TickFlow WebSocket...")

        async with websockets.connect(
            url, ping_interval=25, ping_timeout=10, open_timeout=15,
            close_timeout=5,
        ) as ws:
            self._upstream_ws = ws
            self._upstream_connected = True
            self._reconnect_delay = 1.0
            logger.info("[RealtimeWS] 上游连接成功")
            self._stop_polling()  # 上游连通后停止轮询

            # 通知所有前端客户端
            await self._broadcast({"op": "status", "upstream": "websocket"})

            # 重新订阅所有聚合的标的
            if self._aggregated_quotes:
                await self._upstream_subscribe("quotes", list(self._aggregated_quotes))
            if self._aggregated_depth:
                await self._upstream_subscribe("depth", list(self._aggregated_depth))

            # 接收消息循环
            try:
                async for raw in ws:
                    await self._handle_upstream_message(raw)
            except websockets.ConnectionClosed as e:
                logger.warning("[RealtimeWS] 上游连接关闭: %s", e)
            finally:
                self._upstream_connected = False
                self._upstream_ws = None
                await self._broadcast({"op": "status", "upstream": "disconnected"})
                # 恢复轮询
                if self._aggregated_quotes or self._aggregated_depth:
                    self._ensure_polling()

    async def _reconnect_upstream(self):
        """强制重连上游"""
        if self._upstream_ws:
            await self._upstream_ws.close()
        if self._upstream_task and not self._upstream_task.done():
            self._upstream_task.cancel()
        self._ensure_upstream()

    async def _upstream_subscribe(self, channel: str, symbols: List[str]):
        """向上游发送订阅消息"""
        if not self._upstream_ws:
            return
        from src.services.tickflow_symbol import to_tickflow_symbol
        tf_symbols = [to_tickflow_symbol(s) for s in symbols]
        msg = json.dumps({"op": "subscribe", "channel": channel, "symbols": tf_symbols})
        try:
            await self._upstream_ws.send(msg)
            logger.debug("[RealtimeWS] 上游订阅 %s: %s", channel, tf_symbols)
        except Exception as e:
            logger.warning("[RealtimeWS] 上游发送失败: %s", e)

    async def _upstream_unsubscribe(self, channel: str, symbols: List[str]):
        """向上游发送退订消息"""
        if not self._upstream_ws:
            return
        from src.services.tickflow_symbol import to_tickflow_symbol
        tf_symbols = [to_tickflow_symbol(s) for s in symbols]
        msg = json.dumps({"op": "unsubscribe", "channel": channel, "symbols": tf_symbols})
        try:
            await self._upstream_ws.send(msg)
        except Exception:
            pass

    async def _handle_upstream_message(self, raw: str):
        """处理上游推送的消息, 转发给前端"""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        op = msg.get("op", "")

        if op == "quotes":
            data = msg.get("data", [])
            normalized = self._normalize_quotes(data)
            await self._dispatch_quotes(normalized)

        elif op == "depth":
            data = msg.get("data", {})
            normalized = self._normalize_depth(data)
            await self._dispatch_depth(normalized)

        # TickFlow ping/pong 由 websockets 库自动处理

    def _normalize_quotes(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """将 TickFlow 行情格式转为前端统一格式"""
        from src.services.tickflow_symbol import from_tickflow_symbol

        results = []
        for q in data:
            if not q:
                continue
            tf_sym = str(q.get("symbol", ""))
            code = from_tickflow_symbol(tf_sym)
            ext = q.get("ext") or {}
            change_pct = ext.get("change_pct")
            if change_pct is not None:
                try:
                    change_pct = float(change_pct) * 100  # 比例 → 百分比
                except (TypeError, ValueError):
                    change_pct = None
            results.append({
                "symbol": code,
                "name": ext.get("name") or q.get("name") or "",
                "price": q.get("last_price"),
                "change": ext.get("change_amount"),
                "change_percent": change_pct,
                "volume": q.get("volume"),
                "turnover": q.get("amount"),
                "high": q.get("high"),
                "low": q.get("low"),
                "open": q.get("open"),
                "prev_close": q.get("prev_close"),
                "timestamp": q.get("timestamp"),
            })
        return results

    def _normalize_depth(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """将 TickFlow 五档盘口转为前端格式"""
        from src.services.tickflow_symbol import from_tickflow_symbol

        tf_sym = str(data.get("symbol", ""))
        return {
            "symbol": from_tickflow_symbol(tf_sym),
            "bids": data.get("bids", []),  # [[price, volume], ...]
            "asks": data.get("asks", []),
            "timestamp": data.get("timestamp"),
        }

    async def _dispatch_quotes(self, quotes: List[Dict[str, Any]]):
        """将行情数据分发给已订阅的前端客户端"""
        if not quotes:
            return
        # 构建 symbol → quote 索引
        quote_map: Dict[str, Dict] = {q["symbol"]: q for q in quotes}

        for ws, subs in list(self._subscriptions.items()):
            sub_symbols = subs.get("quotes", set())
            if not sub_symbols:
                continue
            # 过滤出该客户端关心的
            client_quotes = [quote_map[s] for s in sub_symbols if s in quote_map]
            if client_quotes:
                await self._send_to_client(ws, {"op": "quotes", "data": client_quotes})

        await self._update_candles(quotes)

    async def _dispatch_depth(self, depth: Dict[str, Any]):
        """将五档数据分发给已订阅的前端客户端"""
        symbol = depth.get("symbol", "")
        if not symbol:
            return
        for ws, subs in list(self._subscriptions.items()):
            if symbol in subs.get("depth", set()):
                await self._send_to_client(ws, {"op": "depth", "data": depth})

    # ==================== REST 轮询 Fallback ====================

    def _ensure_polling(self):
        """确保轮询任务在运行"""
        if self._polling_task is None or self._polling_task.done():
            self._polling_task = asyncio.ensure_future(self._polling_loop())

    def _stop_polling(self):
        """停止轮询"""
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()

    async def _polling_loop(self):
        """REST 轮询循环: 定期获取行情并推送"""
        logger.info("[RealtimeWS] 进入 REST 轮询模式 (间隔 %.1fs)", self._polling_interval)
        await self._broadcast({"op": "status", "upstream": "polling"})

        try:
            while True:
                await self._poll_once()
                await asyncio.sleep(self._polling_interval)
        except asyncio.CancelledError:
            logger.info("[RealtimeWS] 轮询已停止")

    async def _poll_once(self):
        """执行一次 REST 轮询"""
        if not self._aggregated_quotes:
            return

        symbols_list = list(self._aggregated_quotes)
        try:
            from src.services.market_gateway import MarketGateway
            gateway = MarketGateway()
            quotes = gateway.get_realtime_quotes(symbols_list)
            if quotes:
                await self._dispatch_quotes(quotes)
        except Exception as e:
            logger.warning("[RealtimeWS] 轮询失败: %s", e)

    # ==================== 工具方法 ====================

    async def _send_to_client(self, ws: WebSocket, data: dict):
        """安全地发送消息给客户端"""
        try:
            await ws.send_json(data)
        except Exception:
            # 客户端可能已断开
            pass

    async def _broadcast(self, data: dict):
        """广播消息给所有客户端"""
        for ws in list(self._clients):
            await self._send_to_client(ws, data)

    def get_status(self) -> Dict[str, Any]:
        """获取中继服务状态"""
        return {
            "mode": self.mode,
            "has_api_key": self.has_api_key,
            "clients": len(self._clients),
            "subscribed_quotes": list(self._aggregated_quotes),
            "subscribed_depth": list(self._aggregated_depth),
            "upstream_connected": self._upstream_connected,
            "active_candle_builders": len(self._candle_builders),
            "subscription_manager": self._submgr.get_status(),
        }

    # ==================== 实时 tick → 1m K线缓存写入 ====================

    @staticmethod
    def _infer_market(symbol: str) -> str:
        """从内部标的代码推断 market 标识（用于 kline_data 表的 market 列）"""
        from src.services.tickflow_symbol import to_tickflow_symbol
        tf = to_tickflow_symbol(symbol)
        if "." not in tf:
            return "unknown"
        suffix = tf.rsplit(".", 1)[1].upper()
        if suffix in ("SH", "SZ", "BJ"):
            return "cn"
        if suffix == "HK":
            return "hk"
        if suffix == "US":
            return "us"
        return suffix.lower()

    async def _update_candles(self, quotes: List[Dict[str, Any]]):
        """将上游/轮询的 quotes 增量更新到 1m candle builder，并 flush 已收盘的分钟"""
        if not self._candle_cache_enabled or not quotes:
            return
        now_ms = int(time.time() * 1000)
        current_minute = (now_ms // 60000) * 60000
        for q in quotes:
            sym = q.get("symbol", "")
            if not sym:
                continue
            price = q.get("price")
            if price is None:
                continue
            try:
                price = float(price)
            except (TypeError, ValueError):
                continue
            vol = float(q.get("volume") or 0)
            amt = float(q.get("turnover") or 0)
            ts = q.get("timestamp")
            if isinstance(ts, (int, float)) and ts > 0:
                ts_ms = int(ts)
                if ts_ms < 1_000_000_000_000:
                    ts_ms *= 1000
            else:
                ts_ms = now_ms

            builder = self._candle_builders.get(sym)
            if builder is None:
                builder = _CandleBuilder(symbol=sym, market=self._infer_market(sym))
                self._candle_builders[sym] = builder

            bucket = (ts_ms // 60000) * 60000
            if builder.minute_ts != 0 and bucket != builder.minute_ts:
                await self._flush_candle(builder, is_complete=True)
                builder = _CandleBuilder(symbol=sym, market=builder.market)
                self._candle_builders[sym] = builder

            builder.update(price=price, vol=vol, amt=amt, ts_ms=ts_ms)

        await self._flush_closed_candles(current_minute)

    async def _flush_closed_candles(self, current_minute: int):
        """flush 所有已收盘的 candle（minute_ts < current_minute）到缓存"""
        to_flush = [
            (sym, b) for sym, b in self._candle_builders.items()
            if b.minute_ts and b.minute_ts < current_minute
        ]
        for sym, builder in to_flush:
            await self._flush_candle(builder, is_complete=True)

    async def _flush_candle(self, builder: _CandleBuilder, is_complete: bool):
        """将单个 candle 写入 kline_cache（通过 db_write_queue 串行化）"""
        if not builder.has_data:
            return
        kline = builder.to_kline(is_complete=is_complete)
        try:
            from src.services.db_write_queue import enqueue_write
            from src.services.kline_cache_manager import get_kline_cache_manager
            manager = get_kline_cache_manager()
            await enqueue_write(
                manager.upsert_klines,
                builder.market,
                builder.symbol,
                "1m",
                [kline],
                "realtime_ws",
                label=f"rt_kline_{builder.symbol}",
            )
        except Exception as e:
            logger.debug("[RealtimeWS] candle flush failed for %s: %s", builder.symbol, e)

    def start_candle_flush_loop(self):
        """启动定期 flush 协程（每 15s flush 一次已收盘的分钟 candle）"""
        if self._candle_flush_task and not self._candle_flush_task.done():
            return
        if not self._candle_cache_enabled:
            return
        self._candle_flush_task = asyncio.ensure_future(self._candle_flush_loop())

    async def _candle_flush_loop(self):
        """定期扫描并 flush 已收盘的 candle builder"""
        while True:
            try:
                await asyncio.sleep(15)
                now_ms = int(time.time() * 1000)
                current_minute = (now_ms // 60000) * 60000
                await self._flush_closed_candles(current_minute)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("[RealtimeWS] candle flush loop error: %s", e)

    async def stop_candle_flush_loop(self):
        if self._candle_flush_task:
            self._candle_flush_task.cancel()
            try:
                await self._candle_flush_task
            except asyncio.CancelledError:
                pass
            self._candle_flush_task = None
