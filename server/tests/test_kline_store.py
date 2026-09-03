# -*- coding: utf-8 -*-
"""
KlineStore Phase 2 regression tests.

Covers:
1. KlineStore typed bar reads over kline_data + kline_cache_meta
2. MarketGateway/UDF kline path consumes KlineStore before any legacy cache or live fetch
3. Eastmoney A-share mixed-unit cache invalidation via kline_cache_meta.source
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestKlineStore:
    """KlineStore read/write facade over the authoritative kline_data tables."""

    @pytest.fixture
    def store(self, tmp_path):
        from src.services.kline_cache_manager import KlineCacheManager
        from src.services.kline_store import KlineStore

        manager = KlineCacheManager(db_path=str(tmp_path / "kline_store_test.db"))
        return KlineStore(manager)

    def _make_klines(self, start_ts: int, count: int = 3):
        from src.services.kline_store import KlineBar

        day_ms = 24 * 3600 * 1000
        return [
            KlineBar(
                timestamp_ms=start_ts + i * day_ms,
                open=float(100 + i),
                high=float(110 + i),
                low=float(90 + i),
                close=float(105 + i),
                volume=float(1000 + i * 100),
                amount=float(100000 + i * 10000),
            )
            for i in range(count)
        ]

    def test_query_bars_returns_gateway_compatible_bars(self, store):
        """Given cached kline_data, when querying bars, then seconds/ms and OHLCV fields are exposed explicitly."""
        start_ts = 1704067200000  # 2024-01-01
        store.upsert_bars(
            market="cn",
            symbol="600519",
            interval="1d",
            bars=self._make_klines(start_ts),
            source="test",
        )

        bars = store.query_bars(
            market="cn",
            symbol="600519",
            interval="1d",
            start_time=start_ts,
            end_time=start_ts + 3 * 24 * 3600 * 1000,
        )

        assert len(bars) == 3
        assert bars[0].timestamp_ms == start_ts
        assert bars[0].time_sec == start_ts // 1000
        assert bars[0].open == 100.0
        assert bars[0].volume == 1000.0
        assert bars[0].amount == 100000.0

    def test_query_bars_empty_range_returns_empty_list(self, store):
        """Given no cached rows, when querying bars, then an empty list is returned instead of None."""
        bars = store.query_bars(
            market="cn",
            symbol="000001",
            interval="1d",
            start_time=1704067200000,
            end_time=1704153600000,
        )
        assert bars == []

    def test_invalidate_stale_eastmoney_volume_units(self, store):
        """Given mixed-source cn cache rows, when invalidating Eastmoney stale volume units, then only stale-source rows are removed."""
        start_ts = 1704067200000
        stale = self._make_klines(start_ts)
        fresh = self._make_klines(start_ts)

        store.upsert_bars("cn", "600519", "1d", stale, source="EfinanceFetcher")
        store.upsert_bars("cn", "000001", "1d", fresh, source="TushareFetcher")
        store.upsert_bars("hk", "00700", "1d", stale, source="EfinanceFetcher")

        deleted = store.invalidate_stale_eastmoney_volume_units()

        assert deleted == 3
        assert store.query_bars("cn", "600519", "1d", start_ts, start_ts + 3 * 24 * 3600 * 1000) == []
        assert len(store.query_bars("cn", "000001", "1d", start_ts, start_ts + 3 * 24 * 3600 * 1000)) == 3
        assert len(store.query_bars("hk", "00700", "1d", start_ts, start_ts + 3 * 24 * 3600 * 1000)) == 3


class TestMarketGatewayKlineStorePath:
    """MarketGateway/UDF must read authoritative kline_data via KlineStore first."""

    def test_get_kline_uses_kline_store_before_legacy_cache_or_live_fetch(self):
        """Given a KlineStore hit, when MarketGateway serves UDF kline, then legacy kline_cache and live fetch are bypassed."""
        from src.services.kline_store import KlineBar
        from src.services.market_gateway import MarketGateway

        gateway = object.__new__(MarketGateway)
        gateway._cache = MagicMock()
        gateway._cache_metrics = {"kline_cache_hit": 0, "kline_cache_miss": 0, "kline_live_fetch": 0}
        gateway._fetch_kline_from_source = MagicMock(side_effect=AssertionError("live fetch must not run"))

        store = MagicMock()
        store.query_bars.return_value = [
            KlineBar(
                timestamp_ms=1704067200000,
                open=100.0,
                high=110.0,
                low=90.0,
                close=105.0,
                volume=1000.0,
                amount=100000.0,
            )
        ]

        with patch("src.services.market_gateway.get_kline_store", return_value=store):
            bars, no_data = gateway.get_kline(
                symbol="600519",
                market_type="cn_stock",
                period="1d",
                start_time=1704067200,
                end_time=1704153600,
                limit=300,
            )

        assert no_data is False
        assert bars == [
            {
                "time": 1704067200,
                "open": 100.0,
                "high": 110.0,
                "low": 90.0,
                "close": 105.0,
                "volume": 1000.0,
                "turnover": 100000.0,
            }
        ]
        assert gateway._cache_metrics["kline_cache_hit"] == 1
        assert gateway._cache_metrics["kline_live_fetch"] == 0
        gateway._cache.get_cached_kline.assert_not_called()
        gateway._cache.set_cached_kline.assert_not_called()
        gateway._fetch_kline_from_source.assert_not_called()
