# -*- coding: utf-8 -*-
"""
===================================
KlineStore：K线权威存储门面
===================================

市场数据网关 Phase 2：kline_data + kline_cache_meta 是唯一权威源。
本模块收拢对 KlineCacheManager 的访问，向消费方提供类型化读取入口，
避免各调用点直接拼装 SQL/表结构细节。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Final, Protocol, Sequence

import pandas as pd

from src.services.kline_cache_manager import (
    CacheGap,
    KlineCacheManager,
    get_kline_cache_manager,
)
from src.services.stock_daily_deriver import build_stock_daily_frame

# Phase 1 前写入的东财系 A股 volume 为“手”，新写入为“股”。
# 这些 source 的 cn/1d 缓存段在 Phase 2 统一失效，重新拉取后即为股量纲。
_STALE_EASTMONEY_VOLUME_SOURCES: Final[frozenset[str]] = frozenset(
    {
        "EfinanceFetcher",
        "efinance",
        "AkshareFetcher",
        "AKShareFetcher",
        "akshare",
    }
)


@dataclass(frozen=True, slots=True)
class KlineBar:
    """一根权威 K 线（timestamp_ms 为 Unix 毫秒）。"""

    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    amount: float = 0.0
    is_complete: bool = True

    @property
    def time_sec(self) -> int:
        """TradingView/UDF 使用的 Unix 秒时间戳。"""
        return self.timestamp_ms // 1000

    def to_record(self) -> dict[str, int | float | bool]:
        """转换为 KlineCacheManager.upsert_klines 的记录形状。"""
        return {
            "timestamp": self.timestamp_ms,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount,
            "is_complete": self.is_complete,
        }


class DailyDataSaver(Protocol):
    """stock_daily 写入契约（DatabaseManager.save_daily_data 的结构化子集）。"""

    def save_daily_data(
        self,
        df: pd.DataFrame,
        code: str,
        data_source: str = "Unknown",
    ) -> int: ...


@dataclass(frozen=True, slots=True)
class StockDailySyncRequest:
    """一次 stock_daily 衍生同步请求。"""

    market: str
    symbol: str
    interval: str
    start_time: int
    end_time: int
    code: str = ""
    data_source: str = "kline_data"


def detect_kline_market(stock_code: str) -> str:
    """根据标的代码推断 kline_data market 标识。"""
    from data_provider.base import _is_hk_market
    from data_provider.binance_fetcher import is_crypto_code
    from data_provider.us_index_mapping import is_us_index_code, is_us_stock_code

    if is_crypto_code(stock_code):
        return "crypto_binance"
    if is_us_index_code(stock_code) or is_us_stock_code(stock_code):
        return "us"
    if _is_hk_market(stock_code):
        return "hk"
    return "cn"


class KlineStore:
    """kline_data + kline_cache_meta 的单一读写入口。"""

    def __init__(self, manager: KlineCacheManager | None = None):
        self._manager = manager or get_kline_cache_manager()

    def query_bars(
        self,
        market: str,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
    ) -> list[KlineBar]:
        """按毫秒时间范围读取权威 K 线，返回按时间升序的 typed bars。"""
        df = self._manager.query_klines(market, symbol, interval, start_time, end_time)
        if df is None or df.empty:
            return []

        bars: list[KlineBar] = []
        for _, row in df.iterrows():
            if "timestamp" in row:
                timestamp_ms = int(row["timestamp"])
            else:
                date_value = row["date"]
                timestamp_ms = int(pd.Timestamp(date_value).timestamp() * 1000)
            bars.append(
                KlineBar(
                    timestamp_ms=timestamp_ms,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume", 0) or 0),
                    amount=float(row.get("amount", 0) or 0),
                    is_complete=bool(row.get("is_complete", True)),
                )
            )
        return bars

    def query_dataframe(
        self,
        market: str,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
    ) -> pd.DataFrame:
        """兼容 DataFetcherManager 现有 DataFrame 消费路径。"""
        return self._manager.query_klines(market, symbol, interval, start_time, end_time)

    def upsert_bars(
        self,
        market: str,
        symbol: str,
        interval: str,
        bars: Sequence[KlineBar],
        source: str = "",
    ) -> int:
        """写入权威 K 线并维护 kline_cache_meta 覆盖段。"""
        return self._manager.upsert_klines(
            market,
            symbol,
            interval,
            [bar.to_record() for bar in bars],
            source,
        )

    def upsert_dataframe(
        self,
        market: str,
        symbol: str,
        interval: str,
        df: pd.DataFrame,
        source: str = "",
    ) -> int:
        """从标准化 DataFrame 写入权威 K 线。"""
        return self._manager.upsert_klines_from_df(market, symbol, interval, df, source)

    def find_gaps(
        self,
        market: str,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
    ) -> list[CacheGap]:
        """返回指定范围内的权威缓存缺口。"""
        return self._manager.find_gaps(market, symbol, interval, start_time, end_time)

    def has_complete_coverage(
        self,
        market: str,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
    ) -> bool:
        """检查指定范围是否被权威缓存完整覆盖。"""
        return self._manager.has_complete_coverage(market, symbol, interval, start_time, end_time)

    def sync_stock_daily(self, db: DailyDataSaver, request: StockDailySyncRequest) -> int:
        """从权威 kline_data 构建并写入 stock_daily 衍生视图。"""
        bars = self.query_bars(
            request.market,
            request.symbol,
            request.interval,
            request.start_time,
            request.end_time,
        )
        df = build_stock_daily_frame(bars)
        if df.empty:
            return 0
        return db.save_daily_data(
            df,
            code=request.code or request.symbol,
            data_source=request.data_source,
        )

    def invalidate_stale_eastmoney_volume_units(
        self,
        market: str = "cn",
        interval: str = "1d",
    ) -> int:
        """失效 Phase 1 前写入的东财系 A股混合量纲缓存段。"""
        deleted = 0
        segments = self._manager.get_timeline_data(market=market, interval=interval)
        for segment in segments:
            if segment["source"] not in _STALE_EASTMONEY_VOLUME_SOURCES:
                continue
            deleted += self._manager.delete_range(
                market,
                segment["symbol"],
                interval,
                int(segment["start_time"]),
                int(segment["end_time"]),
            )
        return deleted


_kline_store_instance: KlineStore | None = None
_kline_store_lock = threading.Lock()


def get_kline_store() -> KlineStore:
    """获取全局 KlineStore 单例。"""
    global _kline_store_instance
    if _kline_store_instance is None:
        with _kline_store_lock:
            if _kline_store_instance is None:
                _kline_store_instance = KlineStore()
    return _kline_store_instance
