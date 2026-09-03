# -*- coding: utf-8 -*-
"""
Phase 2 follow-up tests: stock_daily derivation and backtest zero-network reads.

Covers:
1. stock_daily derived columns are built from authoritative kline_data bars
2. KlineStore syncs derived daily rows through the DatabaseManager save path
3. Backtest fill uses KlineStore authoritative coverage before any network fetch
"""

import math
import os
import sys
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_bars(count: int = 25):
    from src.services.kline_store import KlineBar

    day_ms = 24 * 3600 * 1000
    start_ts = 1704067200000  # 2024-01-01
    return [
        KlineBar(
            timestamp_ms=start_ts + i * day_ms,
            open=float(100 + i),
            high=float(101 + i),
            low=float(99 + i),
            close=float(100 + i),
            volume=float(1000 + i * 10),
            amount=float(100000 + i * 1000),
        )
        for i in range(count)
    ]


class _FakeDailyDb:
    def __init__(self):
        self.saved = []

    def save_daily_data(self, df, code, data_source="Unknown"):
        self.saved.append((df, code, data_source))
        return len(df)


class TestStockDailyDerivation:
    """stock_daily is a derived view of authoritative kline_data."""

    def test_build_stock_daily_frame_computes_ma_pct_and_volume_ratio(self):
        """Given ordered daily bars, when building stock_daily rows, then pct/MA/volume_ratio match the derived contract."""
        from src.services.stock_daily_deriver import build_stock_daily_frame

        df = build_stock_daily_frame(_make_bars(25))

        assert len(df) == 25
        assert math.isnan(df.iloc[0]["pct_chg"])
        assert df.iloc[4]["ma5"] == pytest.approx(102.0)
        assert df.iloc[9]["ma10"] == pytest.approx(104.5)
        assert df.iloc[19]["ma20"] == pytest.approx(109.5)
        expected_volume_ratio = df.iloc[24]["volume"] / df.iloc[19:24]["volume"].mean()
        assert df.iloc[24]["volume_ratio"] == pytest.approx(expected_volume_ratio)

    def test_sync_stock_daily_uses_db_save_path(self, tmp_path):
        """Given complete authoritative bars, when syncing stock_daily, then DatabaseManager.save_daily_data receives derived rows."""
        from src.services.kline_cache_manager import KlineCacheManager
        from src.services.kline_store import KlineStore, StockDailySyncRequest

        manager = KlineCacheManager(db_path=str(tmp_path / "derived.db"))
        store = KlineStore(manager)
        bars = _make_bars(25)
        store.upsert_bars("cn", "600519", "1d", bars, source="test")
        fake_db = _FakeDailyDb()

        saved = store.sync_stock_daily(
            fake_db,
            StockDailySyncRequest(
                market="cn",
                symbol="600519",
                interval="1d",
                start_time=bars[0].timestamp_ms,
                end_time=bars[-1].timestamp_ms,
                code="600519",
                data_source="kline_data",
            ),
        )

        assert saved == 25
        df, code, data_source = fake_db.saved[0]
        assert code == "600519"
        assert data_source == "kline_data"
        assert {"ma5", "ma10", "ma20", "volume_ratio", "pct_chg"}.issubset(df.columns)


class TestBacktestAuthoritativeFill:
    """Backtest daily fill must not touch network when kline_data coverage is complete."""

    def test_try_fill_daily_data_uses_kline_store_before_data_fetcher(self):
        """Given complete kline_data coverage, when backtest fills daily rows, then it syncs from KlineStore and never enters fetcher fallback."""
        from src.services.backtest_service import BacktestService
        from src.services.kline_store import StockDailySyncRequest

        service = object.__new__(BacktestService)
        service.db = _FakeDailyDb()

        store = MagicMock()
        store.has_complete_coverage.return_value = True
        store.sync_stock_daily.return_value = 25

        with patch("src.services.backtest_service.get_kline_store", return_value=store):
            service._try_fill_daily_data(
                code="600519",
                analysis_date=date(2024, 1, 1),
                eval_window_days=10,
            )

        store.has_complete_coverage.assert_called_once()
        store.sync_stock_daily.assert_called_once()
        request = store.sync_stock_daily.call_args.args[1]
        assert isinstance(request, StockDailySyncRequest)
        assert request.market == "cn"
        assert request.symbol == "600519"
        assert request.interval == "1d"
