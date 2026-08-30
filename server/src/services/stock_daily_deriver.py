# -*- coding: utf-8 -*-
"""
===================================
stock_daily 衍生视图构建器
===================================

从权威 kline_data bars 构建 stock_daily 衍生列。
stock_daily 不再是独立权威源，只是 KlineStore 的物化视图。
"""

from __future__ import annotations

from typing import Protocol, Sequence

import pandas as pd

from data_provider.normalization import compute_pct_chg


class _BarLike(Protocol):
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float

_STOCK_DAILY_COLUMNS = [
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "pct_chg",
    "ma5",
    "ma10",
    "ma20",
    "volume_ratio",
]


def build_stock_daily_frame(bars: Sequence[_BarLike]) -> pd.DataFrame:
    """把权威 K 线 bars 转换为带衍生列的 stock_daily DataFrame。"""
    if not bars:
        return pd.DataFrame(columns=_STOCK_DAILY_COLUMNS)

    df = pd.DataFrame(
        [
            {
                "date": pd.to_datetime(bar.timestamp_ms, unit="ms"),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "amount": bar.amount,
            }
            for bar in bars
        ]
    ).sort_values("date", kind="stable")

    df["pct_chg"] = compute_pct_chg(df["close"])
    df["ma5"] = df["close"].rolling(window=5).mean()
    df["ma10"] = df["close"].rolling(window=10).mean()
    df["ma20"] = df["close"].rolling(window=20).mean()

    previous_5d_avg_volume = df["volume"].rolling(window=5).mean().shift(1)
    volume_ratio = df["volume"] / previous_5d_avg_volume
    df["volume_ratio"] = volume_ratio.replace([float("inf"), float("-inf")], pd.NA)

    return df[_STOCK_DAILY_COLUMNS]
