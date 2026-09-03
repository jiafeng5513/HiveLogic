# -*- coding: utf-8 -*-
"""
===================================
市场数据网关服务 (Market Data Gateway)
===================================

职责：
1. 聚合多个数据源的标的列表
2. 提供统一的 K 线数据接口
3. 管理缓存策略
4. 为 TradingView DataFeed 和标的浏览器提供后端支撑
5. 多数据源优先级链自动降级

数据源优先级（A 股/ETF）：
  TickFlow → Tushare → AKShare → BaoStock → Efinance

数据源优先级（虚拟货币）：
  Binance → OKX
"""

import logging
import os
import time
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.services.market_cache import MarketCache
from src.services.kline_store import KlineBar, get_kline_store
from src.services.data_source_chain import DataSourceChain, DataSource, AllSourcesFailedError

logger = logging.getLogger(__name__)


@contextmanager
def _no_proxy():
    """临时绕过所有代理（含 Windows 系统代理），避免国内数据源走代理导致连接失败。

    原理：
    1. 清除代理相关环境变量
    2. Monkey-patch requests.Session.__init__，设置 trust_env=False，
       彻底阻止 requests 通过 Windows 注册表读取系统代理设置
    """
    import requests

    proxy_keys = ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]
    saved = {}
    for key in proxy_keys:
        if key in os.environ:
            saved[key] = os.environ.pop(key)

    # Monkey-patch: 让此上下文中新建的 Session 不读取系统代理
    _orig_init = requests.Session.__init__

    def _patched_init(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        self.trust_env = False

    requests.Session.__init__ = _patched_init

    try:
        yield
    finally:
        requests.Session.__init__ = _orig_init
        os.environ.update(saved)


# ==================== 市场类型定义 ====================

MARKET_TYPES = [
    {
        "type": "crypto",
        "name": "虚拟货币",
        "description": "加密货币现货市场 (Binance)",
        "data_source": "binance",
        "icon": "crypto",
        "enabled": True,
    },
    {
        "type": "cn_stock",
        "name": "A股",
        "description": "中国 A 股市场 (沪深京)",
        "data_source": "akshare",
        "icon": "stock",
        "enabled": True,
    },
    {
        "type": "cn_etf",
        "name": "ETF基金",
        "description": "A 股 ETF 基金",
        "data_source": "akshare",
        "icon": "etf",
        "enabled": True,
    },
    {
        "type": "cn_futures",
        "name": "期货",
        "description": "中国期货市场",
        "data_source": "akshare",
        "icon": "futures",
        "enabled": False,  # 后续开启
    },
    {
        "type": "hk_stock",
        "name": "港股",
        "description": "香港证券市场 (HKEX)",
        "data_source": "tickflow",
        "icon": "stock",
        "enabled": True,
    },
    {
        "type": "us_stock",
        "name": "美股",
        "description": "美国证券市场 (NYSE/NASDAQ)",
        "data_source": "tickflow",
        "icon": "stock",
        "enabled": True,
    },
]


class MarketGateway:
    """
    统一市场数据网关

    线程安全：拉取操作加锁，避免并发请求数据源
    """

    _instance: Optional["MarketGateway"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """单例模式"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, cache: Optional[MarketCache] = None):
        if self._initialized:
            return
        self._cache = cache or MarketCache()
        self._fetch_locks: Dict[str, threading.Lock] = {}
        self._fetch_locks_lock = threading.Lock()
        self._chain = DataSourceChain()
        self._tickflow_fetcher = None
        self._realtime_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}  # market_type -> (timestamp, data)
        self._realtime_cache_ttl = 10.0  # 缓存有效期（秒），避免高频触发限流
        self._cache_metrics = {"kline_cache_hit": 0, "kline_cache_miss": 0, "kline_live_fetch": 0}
        self._register_chains()
        self._initialized = True
        logger.info("[MarketGateway] 初始化完成 (含数据源链)")

    _MARKET_TYPE_TO_KLINE = {
        "cn_stock": "cn", "cn_etf": "cn", "cn_futures": "cn",
        "hk_stock": "hk", "us_stock": "us", "crypto": "crypto_binance",
    }

    _PERIOD_TO_INTERVAL = {
        "1": "1m", "5": "5m", "15": "15m", "30": "30m",
        "60": "60m", "1h": "1h", "4h": "4h",
        "1d": "1d", "1w": "1w", "1M": "1M",
    }

    def get_cache_metrics(self) -> Dict[str, int]:
        return dict(self._cache_metrics)

    def _get_tickflow_fetcher(self):
        """延迟初始化 TickFlowFetcher (避免启动时导入失败)"""
        if self._tickflow_fetcher is None:
            try:
                api_key = os.environ.get("TICKFLOW_API_KEY", "")
                from data_provider.tickflow_fetcher import TickFlowFetcher
                self._tickflow_fetcher = TickFlowFetcher(api_key=api_key)
            except Exception as exc:
                logger.warning("[MarketGateway] TickFlowFetcher 初始化失败: %s", exc)
        return self._tickflow_fetcher

    def _register_chains(self) -> None:
        """注册所有数据类别的优先级链"""
        # ---------- 标的列表 ----------
        self._chain.register("symbols:cn_stock", [
            DataSource("tickflow", lambda **kw: self._fetch_tickflow_symbols("cn_stock")),
            DataSource("akshare", lambda **kw: self._fetch_cn_stock_symbols()),
        ])
        self._chain.register("symbols:cn_etf", [
            DataSource("tickflow", lambda **kw: self._fetch_tickflow_symbols("cn_etf")),
            DataSource("akshare", lambda **kw: self._fetch_cn_etf_symbols()),
        ])
        self._chain.register("symbols:crypto", [
            DataSource("binance", lambda **kw: self._fetch_crypto_symbols()),
        ])
        self._chain.register("symbols:hk_stock", [
            DataSource("tickflow", lambda **kw: self._fetch_tickflow_symbols("hk_stock")),
        ])
        self._chain.register("symbols:us_stock", [
            DataSource("tickflow", lambda **kw: self._fetch_tickflow_symbols("us_stock")),
        ])

        # ---------- K 线 ----------
        self._chain.register("kline:cn", [
            DataSource("tickflow", self._fetch_tickflow_kline),
            DataSource("data_provider", self._fetch_cn_kline_via_manager),
        ])
        self._chain.register("kline:crypto", [
            DataSource("binance", self._fetch_crypto_kline),
        ])
        self._chain.register("kline:hk", [
            DataSource("tickflow", self._fetch_tickflow_kline),
        ])
        self._chain.register("kline:us", [
            DataSource("tickflow", self._fetch_tickflow_kline),
        ])

        # ---------- 实时行情 ----------
        self._chain.register("realtime:cn", [
            DataSource("tickflow", self._fetch_tickflow_realtime),
            DataSource("data_provider", self._fetch_cn_realtime_via_manager),
        ])
        self._chain.register("realtime:crypto", [
            DataSource("binance", self._fetch_crypto_realtime),
        ])
        self._chain.register("realtime:hk", [
            DataSource("tickflow", self._fetch_tickflow_realtime),
        ])
        self._chain.register("realtime:us", [
            DataSource("tickflow", self._fetch_tickflow_realtime),
        ])

    def _get_fetch_lock(self, key: str) -> threading.Lock:
        """获取指定 key 的拉取锁"""
        with self._fetch_locks_lock:
            if key not in self._fetch_locks:
                self._fetch_locks[key] = threading.Lock()
            return self._fetch_locks[key]

    # ==================== 市场类型 ====================

    def get_market_types(self) -> List[Dict[str, Any]]:
        """获取支持的市场类型列表"""
        return [mt for mt in MARKET_TYPES if mt["enabled"]]

    # ==================== 标的列表 ====================

    def get_symbols(self, market_type: str, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        获取某市场类型的标的列表

        优先读缓存，缓存失效时从数据源拉取
        """
        # 检查缓存
        if not force_refresh and self._cache.is_symbol_cache_valid(market_type):
            cached = self._cache.get_cached_symbols(market_type)
            if cached:
                logger.debug(f"[MarketGateway] 命中缓存: {market_type} ({len(cached)} 条)")
                return cached

        # 从数据源拉取 (加锁防并发)
        lock = self._get_fetch_lock(f"symbols:{market_type}")
        if not lock.acquire(blocking=False):
            # 有其他线程正在拉取，返回旧缓存
            logger.info(f"[MarketGateway] 其他线程正在拉取 {market_type}，返回旧缓存")
            return self._cache.get_cached_symbols(market_type)

        try:
            # 双重检查：获取锁后再次检查缓存
            if not force_refresh and self._cache.is_symbol_cache_valid(market_type):
                return self._cache.get_cached_symbols(market_type)

            symbols = self._fetch_symbols_from_source(market_type)
            if symbols:
                self._cache.set_cached_symbols(market_type, symbols)
            return symbols
        except Exception as e:
            logger.error(f"[MarketGateway] 拉取标的列表失败 ({market_type}): {e}", exc_info=True)
            # 回退到旧缓存
            return self._cache.get_cached_symbols(market_type)
        finally:
            lock.release()

    def search_symbols(self, query: str, market_type: str = "") -> List[Dict[str, Any]]:
        """搜索标的 (从缓存搜索)"""
        if not query or len(query.strip()) == 0:
            return []
        return self._cache.search_cached_symbols(query.strip(), market_type)

    # ==================== K 线数据 ====================

    def get_kline(
        self,
        symbol: str,
        market_type: str,
        period: str = "1d",
        start_time: int = 0,
        end_time: int = 0,
        limit: int = 300,
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """
        获取 K 线数据

        返回: (bars, no_data)
        - bars: K 线数据列表
        - no_data: True 表示已无更多历史数据
        """
        kline_market = self._MARKET_TYPE_TO_KLINE.get(market_type, "")
        interval = self._PERIOD_TO_INTERVAL.get(period, period)

        if kline_market and interval:
            try:
                store = get_kline_store()
                start_ms = start_time * 1000 if start_time > 0 else 0
                end_ms = end_time * 1000 if end_time > 0 else int(time.time() * 1000)
                cached_bars = store.query_bars(kline_market, symbol, interval, start_ms, end_ms)
                if cached_bars:
                    bars = [
                        {
                            "time": bar.time_sec,
                            "open": bar.open,
                            "high": bar.high,
                            "low": bar.low,
                            "close": bar.close,
                            "volume": bar.volume,
                            "turnover": bar.amount,
                        }
                        for bar in cached_bars
                    ]
                    self._cache_metrics["kline_cache_hit"] += 1
                    return bars[-limit:], False
            except Exception as e:
                logger.debug("[MarketGateway] KlineStore 缓存查询异常: %s", e)

        self._cache_metrics["kline_cache_miss"] += 1

        # 从数据源拉取
        self._cache_metrics["kline_live_fetch"] += 1
        try:
            bars = self._fetch_kline_from_source(
                symbol, market_type, period, start_time, end_time, limit
            )
            if bars:
                self._persist_live_klines(kline_market, symbol, interval, bars)
                return bars, False
            return [], True
        except Exception as e:
            logger.error(
                f"[MarketGateway] 拉取 K 线失败 ({symbol}/{period}): {e}",
                exc_info=True,
            )
            return [], True

    def _persist_live_klines(
        self,
        kline_market: str,
        symbol: str,
        interval: str,
        bars: List[Dict[str, Any]],
    ) -> None:
        """把 live fetch 的 K 线写入权威源（CN 已由 DataFetcherManager 持久化，跳过避免覆盖 source）。"""
        if not kline_market or not bars or kline_market == "cn":
            return
        store = get_kline_store()
        store.upsert_bars(
            kline_market,
            symbol,
            interval,
            [
                KlineBar(
                    timestamp_ms=int(bar["time"]) * 1000,
                    open=float(bar["open"]),
                    high=float(bar["high"]),
                    low=float(bar["low"]),
                    close=float(bar["close"]),
                    volume=float(bar.get("volume", 0)),
                    amount=float(bar.get("turnover", 0)),
                )
                for bar in bars
            ],
            source="market_gateway_live",
        )

    # ==================== 实时行情 ====================

    def get_realtime_quotes(
        self, symbols: List[str], market_type: str = ""
    ) -> List[Dict[str, Any]]:
        """获取批量实时行情"""
        if not symbols:
            return []

        # 自动推断市场类型
        if not market_type:
            # 简单按首个标的猜测
            market_type = self._guess_market_type(symbols[0])

        try:
            return self._fetch_realtime_from_source(symbols, market_type)
        except Exception as e:
            logger.error(f"[MarketGateway] 获取实时行情失败: {e}", exc_info=True)
            return []

    # ==================== 内部: 数据源拉取 ====================

    def _fetch_symbols_from_source(self, market_type: str) -> List[Dict[str, Any]]:
        """根据市场类型从数据源链拉取标的列表"""
        chain_category = {
            "crypto": "symbols:crypto",
            "cn_stock": "symbols:cn_stock",
            "cn_etf": "symbols:cn_etf",
            "hk_stock": "symbols:hk_stock",
            "us_stock": "symbols:us_stock",
        }.get(market_type)

        if not chain_category:
            if market_type == "cn_futures":
                return self._fetch_cn_futures_symbols()
            logger.warning(f"[MarketGateway] 不支持的市场类型: {market_type}")
            return []

        try:
            return self._chain.fetch(chain_category)
        except AllSourcesFailedError as e:
            logger.error("[MarketGateway] 标的列表所有数据源均失败: %s", e)
            return []

    def _fetch_crypto_symbols(self) -> List[Dict[str, Any]]:
        """从 Binance REST API 获取虚拟货币标的列表"""
        import requests

        try:
            logger.info("[MarketGateway] 正在从 Binance 获取交易对列表...")
            resp = requests.get(
                "https://api.binance.com/api/v3/exchangeInfo",
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            symbols = []
            for pair in data.get("symbols", []):
                if pair.get("status") != "TRADING":
                    continue
                base = pair.get("baseAsset", "")
                quote = pair.get("quoteAsset", "")
                symbol_code = f"{base}/{quote}"
                symbols.append(
                    {
                        "symbol": symbol_code,
                        "name": f"{base}/{quote}",
                        "exchange": "Binance",
                        "data_source": "binance",
                        "currency": quote,
                        "status": "trading",
                    }
                )

            logger.info(f"[MarketGateway] Binance 标的: {len(symbols)} 条")
            return symbols

        except Exception as e:
            logger.error(f"[MarketGateway] Binance exchangeInfo 获取失败: {e}")
            return []

    def _fetch_cn_stock_symbols(self) -> List[Dict[str, Any]]:
        """从 AKShare 获取 A 股标的列表

        使用 stock_info_a_code_name()（数据源: 东财行情中心列表页），
        避免 stock_zh_a_spot_em() 依赖的 push2.eastmoney.com 接口在
        某些网络环境下不可用的问题。
        """
        try:
            import akshare as ak

            logger.info("[MarketGateway] 正在从 AKShare 获取 A 股列表...")
            with _no_proxy():
                df = ak.stock_info_a_code_name()

            if df is None or df.empty:
                logger.warning("[MarketGateway] AKShare A 股列表为空")
                return []

            symbols = []
            for _, row in df.iterrows():
                code = str(row.get("code", "")).strip()
                name = str(row.get("name", "")).strip()
                if not code:
                    continue

                # 判断交易所
                if code.startswith(("6", "9")):
                    exchange = "SSE"
                elif code.startswith(("0", "3")):
                    exchange = "SZSE"
                elif code.startswith(("4", "8")):
                    exchange = "BSE"
                else:
                    exchange = ""

                symbols.append(
                    {
                        "symbol": code,
                        "name": name,
                        "exchange": exchange,
                        "data_source": "akshare",
                        "currency": "CNY",
                        "status": "trading",
                    }
                )

            logger.info(f"[MarketGateway] A 股标的: {len(symbols)} 条")
            return symbols

        except Exception as e:
            logger.error(f"[MarketGateway] AKShare A 股列表获取失败: {e}", exc_info=True)
            return []

    def _fetch_cn_etf_symbols(self) -> List[Dict[str, Any]]:
        """从 AKShare 获取 ETF 标的列表

        使用 fund_etf_category_sina()（数据源: 新浪财经），
        避免 fund_etf_spot_em() 依赖的 push2.eastmoney.com 接口在
        某些网络环境下不可用的问题。
        """
        try:
            import akshare as ak

            logger.info("[MarketGateway] 正在从 AKShare 获取 ETF 列表...")
            with _no_proxy():
                df = ak.fund_etf_category_sina(symbol="ETF基金")

            if df is None or df.empty:
                logger.warning("[MarketGateway] AKShare ETF 列表为空")
                return []

            symbols = []
            for _, row in df.iterrows():
                code = str(row.get("代码", "")).strip()
                name = str(row.get("名称", "")).strip()
                if not code:
                    continue

                if code.startswith(("5",)):
                    exchange = "SSE"
                elif code.startswith(("1",)):
                    exchange = "SZSE"
                else:
                    exchange = ""

                price = row.get("最新价")
                change_pct = row.get("涨跌幅")

                symbols.append(
                    {
                        "symbol": code,
                        "name": name,
                        "exchange": exchange,
                        "data_source": "akshare",
                        "currency": "CNY",
                        "status": "trading",
                        "extra": {
                            "price": float(price) if pd.notna(price) else None,
                            "change_pct": float(change_pct) if pd.notna(change_pct) else None,
                        },
                    }
                )

            logger.info(f"[MarketGateway] ETF 标的: {len(symbols)} 条")
            return symbols

        except Exception as e:
            logger.error(f"[MarketGateway] AKShare ETF 列表获取失败: {e}", exc_info=True)
            return []

    def _fetch_cn_futures_symbols(self) -> List[Dict[str, Any]]:
        """从 AKShare 获取期货标的列表 (预留)"""
        # 后续实现
        logger.info("[MarketGateway] 期货标的拉取尚未实现")
        return []

    def _fetch_kline_from_source(
        self,
        symbol: str,
        market_type: str,
        period: str,
        start_time: int,
        end_time: int,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """通过数据源链拉取 K 线数据"""
        if market_type == "crypto":
            chain_cat = "kline:crypto"
        elif market_type in ("cn_stock", "cn_etf"):
            chain_cat = "kline:cn"
        elif market_type == "hk_stock":
            chain_cat = "kline:hk"
        elif market_type == "us_stock":
            chain_cat = "kline:us"
        else:
            logger.warning(f"[MarketGateway] 不支持的 K 线市场类型: {market_type}")
            return []

        try:
            return self._chain.fetch(
                chain_cat,
                symbol=symbol,
                period=period,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
            )
        except AllSourcesFailedError as e:
            logger.error("[MarketGateway] K 线所有数据源均失败: %s", e)
            return []

    def _fetch_crypto_kline(
        self,
        symbol: str = "",
        period: str = "1d",
        start_time: int = 0,
        end_time: int = 0,
        limit: int = 300,
        **_kwargs,
    ) -> List[Dict[str, Any]]:
        """从 Binance 获取虚拟货币 K 线"""
        import requests

        # 转换周期格式: 1d -> 1d, 1h -> 1h, 5 -> 5m
        interval_map = {
            "1": "1m", "5": "5m", "15": "15m", "30": "30m",
            "60": "1h", "1h": "1h", "1H": "1h",
            "4h": "4h", "4H": "4h",
            "1d": "1d", "1D": "1d",
            "1w": "1w", "1W": "1w",
            "1M": "1M",
        }
        interval = interval_map.get(period, period)

        # symbol: "BTC/USDT" -> "BTCUSDT"
        binance_symbol = symbol.replace("/", "")

        params = {
            "symbol": binance_symbol,
            "interval": interval,
            "limit": min(limit, 1000),
        }
        if start_time > 0:
            params["startTime"] = start_time * 1000  # Binance 用毫秒
        if end_time > 0:
            params["endTime"] = end_time * 1000

        try:
            resp = requests.get(
                "https://api.binance.com/api/v3/klines",
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            raw = resp.json()

            bars = []
            for item in raw:
                bars.append(
                    {
                        "time": int(item[0]) // 1000,  # 毫秒 -> 秒
                        "open": float(item[1]),
                        "high": float(item[2]),
                        "low": float(item[3]),
                        "close": float(item[4]),
                        "volume": float(item[5]),
                        "turnover": float(item[7]),  # quote asset volume
                    }
                )
            return bars

        except Exception as e:
            logger.error(f"[MarketGateway] Binance K 线获取失败 ({symbol}): {e}")
            return []

    def _fetch_cn_kline_via_manager(
        self,
        symbol: str = "",
        period: str = "1d",
        start_time: int = 0,
        end_time: int = 0,
        limit: int = 300,
        **_kwargs,
    ) -> List[Dict[str, Any]]:
        """
        通过 DataFetcherManager 获取 A 股 / ETF K 线

        复用已有的 data_provider 层 (AKShare/Tushare/BaoStock 等)
        """
        try:
            from data_provider.base import DataFetcherManager

            manager = DataFetcherManager()

            # 计算日期范围
            if end_time > 0:
                end_date = datetime.fromtimestamp(end_time).strftime("%Y%m%d")
            else:
                end_date = datetime.now().strftime("%Y%m%d")

            if start_time > 0:
                start_date = datetime.fromtimestamp(start_time).strftime("%Y%m%d")
            else:
                # 默认取 limit 天
                start_dt = datetime.now() - timedelta(days=limit * 2)  # 交易日粗算
                start_date = start_dt.strftime("%Y%m%d")

            with _no_proxy():
                df, source_name = manager.get_daily_data(
                    stock_code=symbol,
                    start_date=start_date,
                    end_date=end_date,
                )

            if df is None or df.empty:
                return []

            bars = []
            for _, row in df.iterrows():
                # 日期转时间戳 (秒)
                date_val = row.get("date")
                if isinstance(date_val, str):
                    try:
                        dt = datetime.strptime(date_val, "%Y-%m-%d")
                    except ValueError:
                        dt = datetime.strptime(date_val, "%Y%m%d")
                elif hasattr(date_val, "timestamp"):
                    dt = date_val
                else:
                    continue

                bars.append(
                    {
                        "time": int(dt.timestamp()),
                        "open": float(row.get("open", 0)),
                        "high": float(row.get("high", 0)),
                        "low": float(row.get("low", 0)),
                        "close": float(row.get("close", 0)),
                        "volume": float(row.get("volume", 0)) if pd.notna(row.get("volume")) else 0,
                        "turnover": float(row.get("amount", 0)) if pd.notna(row.get("amount")) else 0,
                    }
                )

            # 按时间排序
            bars.sort(key=lambda b: b["time"])

            logger.info(
                f"[MarketGateway] CN K 线 ({symbol}/{period}): {len(bars)} bars from {source_name}"
            )
            return bars

        except Exception as e:
            logger.error(
                f"[MarketGateway] CN K 线获取失败 ({symbol}/{period}): {e}",
                exc_info=True,
            )
            return []

    def _fetch_realtime_from_source(
        self, symbols: List[str], market_type: str
    ) -> List[Dict[str, Any]]:
        """通过数据源链获取实时行情"""
        if market_type == "crypto":
            chain_cat = "realtime:crypto"
        elif market_type in ("cn_stock", "cn_etf"):
            chain_cat = "realtime:cn"
        elif market_type == "hk_stock":
            chain_cat = "realtime:hk"
        elif market_type == "us_stock":
            chain_cat = "realtime:us"
        else:
            return []

        try:
            return self._chain.fetch(chain_cat, symbols=symbols)
        except AllSourcesFailedError as e:
            logger.error("[MarketGateway] 实时行情所有数据源均失败: %s", e)
            return []

    def _fetch_crypto_realtime(self, symbols: List[str] = None, **_kwargs) -> List[Dict[str, Any]]:
        """从 Binance 获取虚拟货币实时行情"""
        import requests

        symbols = symbols or []
        results = []
        try:
            # Binance 24hr ticker (批量)
            resp = requests.get(
                "https://api.binance.com/api/v3/ticker/24hr",
                timeout=15,
            )
            resp.raise_for_status()
            tickers = resp.json()

            # 建立索引
            ticker_map = {}
            for t in tickers:
                ticker_map[t["symbol"]] = t

            for symbol in symbols:
                binance_symbol = symbol.replace("/", "")
                ticker = ticker_map.get(binance_symbol)
                if ticker:
                    results.append(
                        {
                            "symbol": symbol,
                            "name": symbol,
                            "price": float(ticker.get("lastPrice", 0)),
                            "change": float(ticker.get("priceChange", 0)),
                            "change_percent": float(ticker.get("priceChangePercent", 0)),
                            "volume": float(ticker.get("volume", 0)),
                            "turnover": float(ticker.get("quoteVolume", 0)),
                            "high": float(ticker.get("highPrice", 0)),
                            "low": float(ticker.get("lowPrice", 0)),
                            "open": float(ticker.get("openPrice", 0)),
                            "prev_close": float(ticker.get("prevClosePrice", 0)),
                            "update_time": datetime.now().isoformat(),
                        }
                    )
        except Exception as e:
            logger.error(f"[MarketGateway] Binance 实时行情获取失败: {e}")

        return results

    def _fetch_cn_realtime_via_manager(self, symbols: List[str] = None, **_kwargs) -> List[Dict[str, Any]]:
        """通过 DataFetcherManager 获取 A 股实时行情"""
        symbols = symbols or []
        try:
            from data_provider.base import DataFetcherManager

            manager = DataFetcherManager()
            results = []

            with _no_proxy():
                for symbol in symbols:
                    try:
                        quote = manager.get_realtime_quote(symbol)
                        if quote is None:
                            continue
                        results.append(
                            {
                                "symbol": symbol,
                                "name": getattr(quote, "name", ""),
                                "price": getattr(quote, "price", None),
                                "change": getattr(quote, "change_amount", None),
                                "change_percent": getattr(quote, "change_pct", None),
                                "volume": getattr(quote, "volume", None),
                                "turnover": getattr(quote, "amount", None),
                                "high": getattr(quote, "high", None),
                                "low": getattr(quote, "low", None),
                                "open": getattr(quote, "open_price", None),
                                "prev_close": getattr(quote, "pre_close", None),
                                "update_time": datetime.now().isoformat(),
                            }
                        )
                    except Exception as e:
                        logger.warning(f"[MarketGateway] 获取 {symbol} 实时行情失败: {e}")

            return results

        except Exception as e:
            logger.error(f"[MarketGateway] CN 实时行情获取失败: {e}", exc_info=True)
            return []

    # ==================== TickFlow 适配方法 ====================

    def _fetch_tickflow_symbols(self, market_type: str = "", **_kwargs) -> List[Dict[str, Any]]:
        """通过 TickFlowFetcher 获取标的列表"""
        fetcher = self._get_tickflow_fetcher()
        if fetcher is None:
            raise Exception("TickFlowFetcher 不可用")
        result = fetcher.get_symbol_list(market_type)
        if not result:
            raise Exception(f"TickFlow 标的列表为空 ({market_type})")
        return result

    def _fetch_tickflow_kline(
        self,
        symbol: str = "",
        period: str = "1d",
        start_time: int = 0,
        end_time: int = 0,
        limit: int = 300,
        **_kwargs,
    ) -> List[Dict[str, Any]]:
        """通过 TickFlowFetcher 获取 K 线"""
        fetcher = self._get_tickflow_fetcher()
        if fetcher is None:
            raise Exception("TickFlowFetcher 不可用")
        return fetcher.get_klines(
            symbol, period,
            count=limit,
            start_time=start_time if start_time > 0 else None,
            end_time=end_time if end_time > 0 else None,
        )

    def _fetch_tickflow_realtime(self, symbols: List[str] = None, **_kwargs) -> List[Dict[str, Any]]:
        """通过 TickFlowFetcher 获取实时行情（带缓存防限流）"""
        fetcher = self._get_tickflow_fetcher()
        if fetcher is None:
            raise Exception("TickFlowFetcher 不可用")
        symbols = symbols or []
        if not symbols:
            return []

        cache_key = ",".join(sorted(symbols[:50]))
        now = time.time()
        cached = self._realtime_cache.get(cache_key)
        if cached and (now - cached[0]) < self._realtime_cache_ttl:
            return cached[1]

        try:
            result = fetcher.get_realtime_quotes(symbols)
            if result:
                self._realtime_cache[cache_key] = (now, result)
            return result
        except Exception:
            # 限流或其他异常，返回缓存数据
            if cached:
                return cached[1]
            raise

    def get_chain_health(self) -> Dict[str, Any]:
        """获取数据源链健康报告 (调试/监控)"""
        return self._chain.get_health_report()

    def reset_chain(self, category: Optional[str] = None) -> None:
        """重置数据源链状态 (配置变更后调用)"""
        self._chain.reset(category)
        if self._tickflow_fetcher is not None:
            self._tickflow_fetcher.close()
            self._tickflow_fetcher = None
        logger.info("[MarketGateway] 数据源链已重置")

    # ==================== 辅助方法 ====================

    @staticmethod
    def _guess_market_type(symbol: str) -> str:
        """根据标的代码猜测市场类型"""
        s = symbol.strip()
        # 含 "/" 且全英文大写，大概率是虚拟货币
        if "/" in s:
            return "crypto"
        # 港股: HKxxxxx 格式
        if s.upper().startswith("HK") and s[2:].isdigit():
            return "hk_stock"
        # 6 位数字
        if s.isdigit() and len(s) == 6:
            if s.startswith(("5",)):
                return "cn_etf"
            if s.startswith(("1",)) and s[:2] in ("15", "16", "18"):
                return "cn_etf"
            return "cn_stock"
        # 纯字母 → 美股
        if s.isalpha():
            return "us_stock"
        return "cn_stock"
