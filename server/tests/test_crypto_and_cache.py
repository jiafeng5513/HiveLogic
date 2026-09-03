# -*- coding: utf-8 -*-
"""
Binance & OKX Fetcher + KlineCacheManager 单元测试

测试场景:
1. BinanceFetcher: 交易对格式转换、数据标准化、分页逻辑
2. OKXFetcher: 交易对格式转换、K线周期映射、数据标准化
3. KlineCacheManager: 缓存写入/查询/缺口分析/删除/合并
4. 缓存集成: cache-first 策略正确性
"""

import os
import sys
import time
import tempfile
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timedelta

import pytest
import pandas as pd

# 确保 backend 目录在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ==================== Binance Fetcher 测试 ====================


class TestBinanceFetcher:
    """测试 BinanceFetcher 核心逻辑"""

    def test_to_binance_symbol(self):
        """测试交易对格式转换: 内部格式 -> Binance"""
        from data_provider.binance_fetcher import to_binance_symbol
        assert to_binance_symbol("BTC-USDT") == "BTCUSDT"
        assert to_binance_symbol("ETH-USDT") == "ETHUSDT"
        assert to_binance_symbol("BTCUSDT") == "BTCUSDT"  # 已经是Binance格式
        assert to_binance_symbol("btc-usdt") == "BTCUSDT"  # 大小写

    def test_from_binance_symbol(self):
        """测试交易对格式转换: Binance -> 内部格式"""
        from data_provider.binance_fetcher import from_binance_symbol
        assert from_binance_symbol("BTCUSDT") == "BTC-USDT"
        assert from_binance_symbol("ETHUSDT") == "ETH-USDT"
        assert from_binance_symbol("SOLUSDT") == "SOL-USDT"

    def test_is_crypto_code(self):
        """测试加密货币代码识别"""
        from data_provider.binance_fetcher import is_crypto_code
        # 加密货币
        assert is_crypto_code("BTC-USDT") is True
        assert is_crypto_code("ETH-USDT") is True
        assert is_crypto_code("BTCUSDT") is True
        assert is_crypto_code("SOL-USDT") is True
        # 非加密货币
        assert is_crypto_code("600519") is False
        assert is_crypto_code("000001") is False
        assert is_crypto_code("AAPL") is False
        assert is_crypto_code("00700") is False

    def test_normalize_data(self):
        """测试K线数据标准化"""
        from data_provider.binance_fetcher import BinanceFetcher
        fetcher = BinanceFetcher()

        # 模拟 Binance API 返回格式 -> 先转成 _fetch_raw_data 输出的 DataFrame
        raw_data = [
            [1704067200000, "42000.5", "42500.0", "41800.0", "42200.3",
             "1234.56", 1704153599999, "51897600.0", 5000, "600.0", "25200000.0", "0"],
            [1704153600000, "42200.3", "43000.0", "42100.0", "42800.7",
             "1500.00", 1704239999999, "64200000.0", 6000, "700.0", "29900000.0", "0"],
        ]

        df = pd.DataFrame(raw_data, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore"
        ])

        result = fetcher._normalize_data(df, "BTCUSDT")
        assert result is not None
        assert len(result) == 2
        assert "open" in result.columns
        assert "high" in result.columns
        assert "low" in result.columns
        assert "close" in result.columns
        assert "volume" in result.columns
        assert result["open"].iloc[0] == 42000.5
        assert result["close"].iloc[1] == 42800.7

    def test_fetch_raw_data_success(self):
        """测试REST API调用成功"""
        from data_provider.binance_fetcher import BinanceFetcher
        fetcher = BinanceFetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            [1704067200000, "42000.5", "42500.0", "41800.0", "42200.3",
             "1234.56", 1704153599999, "51897600.0", 5000, "600.0", "25200000.0", "0"],
        ]

        with patch.object(fetcher._session, "get", return_value=mock_response) as mock_get:
            result = fetcher._fetch_raw_data(
                stock_code="BTC-USDT",
                start_date="2024-01-01",
                end_date="2024-01-10",
            )
            assert result is not None
            assert len(result) >= 1
            mock_get.assert_called()

    def test_fetch_rate_limit_handling(self):
        """测试速率限制处理"""
        from data_provider.binance_fetcher import BinanceFetcher
        fetcher = BinanceFetcher()

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "60"}
        mock_response.text = "Rate limit exceeded"

        with patch.object(fetcher._session, "get", return_value=mock_response):
            with pytest.raises(Exception):
                fetcher._fetch_raw_data(
                    stock_code="BTC-USDT",
                    start_date="2024-01-01",
                    end_date="2024-01-10",
                )


# ==================== OKX Fetcher 测试 ====================


class TestOKXFetcher:
    """测试 OKXFetcher 核心逻辑"""

    def test_to_okx_inst_id(self):
        """测试交易对格式转换: 内部格式 -> OKX"""
        from data_provider.okx_fetcher import to_okx_inst_id
        assert to_okx_inst_id("BTC-USDT") == "BTC-USDT"
        assert to_okx_inst_id("BTCUSDT") == "BTC-USDT"
        assert to_okx_inst_id("ETH-USDT") == "ETH-USDT"
        assert to_okx_inst_id("ETHUSDT") == "ETH-USDT"

    def test_from_okx_inst_id(self):
        """测试交易对格式转换: OKX -> 内部格式"""
        from data_provider.okx_fetcher import from_okx_inst_id
        assert from_okx_inst_id("BTC-USDT") == "BTC-USDT"
        assert from_okx_inst_id("ETH-USDT") == "ETH-USDT"

    def test_normalize_data(self):
        """测试OKX K线数据标准化"""
        from data_provider.okx_fetcher import OKXFetcher
        fetcher = OKXFetcher()

        # OKX API 返回格式: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        raw_data = [
            ["1704153600000", "42200.3", "43000.0", "42100.0", "42800.7",
             "1500.00", "64200000.0", "64200000.0", "1"],
            ["1704067200000", "42000.5", "42500.0", "41800.0", "42200.3",
             "1234.56", "51897600.0", "51897600.0", "1"],
        ]

        df = pd.DataFrame(raw_data, columns=[
            "ts", "open", "high", "low", "close", "vol",
            "vol_ccy", "vol_ccy_quote", "confirm"
        ])

        result = fetcher._normalize_data(df, "BTC-USDT")
        assert result is not None
        assert len(result) == 2
        assert "open" in result.columns
        # 应按时间升序排列，所以第一条是更早的
        assert result["open"].iloc[0] == 42000.5

    def test_fetch_raw_data_success(self):
        """测试OKX REST API调用"""
        from data_provider.okx_fetcher import OKXFetcher
        fetcher = OKXFetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": "0",
            "data": [
                ["1704153600000", "42200.3", "43000.0", "42100.0", "42800.7",
                 "1500.00", "64200000.0", "64200000.0", "1"],
            ]
        }

        with patch.object(fetcher._session, "get", return_value=mock_response):
            result = fetcher._fetch_raw_data(
                stock_code="BTC-USDT",
                start_date="2024-01-01",
                end_date="2024-01-10",
            )
            assert result is not None


# ==================== KlineCacheManager 测试 ====================


class TestKlineCacheManager:
    """测试本地缓存管理器"""

    @pytest.fixture
    def cache_manager(self):
        """创建临时数据库的 CacheManager 实例"""
        from src.services.kline_cache_manager import KlineCacheManager
        # 使用临时文件
        tmp_dir = tempfile.mkdtemp()
        db_path = os.path.join(tmp_dir, "test_cache.db")
        manager = KlineCacheManager(db_path=db_path)
        yield manager
        # cleanup
        try:
            os.unlink(db_path)
            os.rmdir(tmp_dir)
        except Exception:
            pass

    def _make_sample_klines(self, start_ts: int, count: int = 10) -> list:
        """生成测试用K线数据（List[Dict]格式）"""
        day_ms = 24 * 3600 * 1000
        klines = []
        for i in range(count):
            klines.append({
                "timestamp": start_ts + i * day_ms,
                "open": float(100 + i),
                "high": float(110 + i),
                "low": float(90 + i),
                "close": float(105 + i),
                "volume": float(1000 + i * 100),
                "amount": float(100000 + i * 10000),
            })
        return klines

    def test_upsert_and_query(self, cache_manager):
        """测试写入和查询"""
        start_ts = 1704067200000  # 2024-01-01
        klines = self._make_sample_klines(start_ts, 10)

        # 写入
        cache_manager.upsert_klines(
            market="cn", symbol="600519", interval="1d",
            klines=klines, source="test"
        )

        # 查询全部
        result = cache_manager.query_klines(
            market="cn", symbol="600519", interval="1d",
            start_time=start_ts,
            end_time=start_ts + 10 * 24 * 3600 * 1000
        )
        assert result is not None
        assert len(result) == 10

    def test_upsert_idempotent(self, cache_manager):
        """测试重复写入（upsert）幂等性"""
        start_ts = 1704067200000
        klines = self._make_sample_klines(start_ts, 5)

        # 写入两次
        cache_manager.upsert_klines("cn", "600519", "1d", klines, "test")
        cache_manager.upsert_klines("cn", "600519", "1d", klines, "test")

        result = cache_manager.query_klines(
            "cn", "600519", "1d", start_ts, start_ts + 5 * 24 * 3600 * 1000
        )
        assert len(result) == 5  # 不重复

    def test_find_gaps(self, cache_manager):
        """测试缺口分析"""
        day_ms = 24 * 3600 * 1000
        start_ts = 1704067200000  # 2024-01-01

        # 写入第1-5天数据
        klines1 = self._make_sample_klines(start_ts, 5)
        cache_manager.upsert_klines("cn", "600519", "1d", klines1, "test")

        # 写入第8-10天数据（第6-7天缺失）
        klines2 = self._make_sample_klines(start_ts + 7 * day_ms, 3)
        cache_manager.upsert_klines("cn", "600519", "1d", klines2, "test")

        # 查询第1-10天的缺口
        gaps = cache_manager.find_gaps(
            "cn", "600519", "1d",
            start_ts, start_ts + 10 * day_ms
        )
        # 应该有缺口（第5-8天之间）
        assert len(gaps) >= 1

    def test_delete_range(self, cache_manager):
        """测试删除指定范围"""
        day_ms = 24 * 3600 * 1000
        start_ts = 1704067200000
        klines = self._make_sample_klines(start_ts, 10)

        cache_manager.upsert_klines("cn", "600519", "1d", klines, "test")

        # 删除前5天 (start_ts + 4*day_ms 是第5条的时间戳)
        deleted = cache_manager.delete_range(
            "cn", "600519", "1d",
            start_ts, start_ts + 4 * day_ms
        )
        assert deleted >= 5

        # 查询应只剩后5天
        result = cache_manager.query_klines(
            "cn", "600519", "1d",
            start_ts, start_ts + 10 * day_ms
        )
        assert len(result) == 5

    def test_clear_market(self, cache_manager):
        """测试清空市场缓存"""
        start_ts = 1704067200000
        klines = self._make_sample_klines(start_ts, 5)

        cache_manager.upsert_klines("cn", "600519", "1d", klines, "test")
        cache_manager.upsert_klines("cn", "000001", "1d", klines, "test")

        deleted = cache_manager.clear_market("cn")
        assert deleted == 10

        # 验证清空
        result = cache_manager.query_klines(
            "cn", "600519", "1d", start_ts, start_ts + 5 * 24 * 3600 * 1000
        )
        assert result is None or len(result) == 0

    def test_get_cache_status(self, cache_manager):
        """测试缓存状态查询"""
        start_ts = 1704067200000
        klines = self._make_sample_klines(start_ts, 10)

        cache_manager.upsert_klines("cn", "600519", "1d", klines, "test")
        cache_manager.upsert_klines("crypto_binance", "BTCUSDT", "1d", klines, "test")

        status = cache_manager.get_cache_status()
        assert status["total_records"] == 20
        assert "cn" in status["markets"]
        assert "crypto_binance" in status["markets"]

    def test_get_timeline_data(self, cache_manager):
        """测试时间轴数据获取"""
        start_ts = 1704067200000
        klines = self._make_sample_klines(start_ts, 10)

        cache_manager.upsert_klines("cn", "600519", "1d", klines, "test")

        timeline = cache_manager.get_timeline_data(market="cn", interval="1d")
        assert len(timeline) > 0
        seg = timeline[0]
        assert "start_time" in seg
        assert "end_time" in seg

    def test_download_task_lifecycle(self, cache_manager):
        """测试下载任务生命周期"""
        # 创建任务
        task_id = cache_manager.create_download_task(
            market="cn", symbol="600519", interval="1d",
            start_time=1704067200000, end_time=1704672000000
        )
        assert task_id

        # 查询状态
        status = cache_manager.get_task_status(task_id)
        assert status["status"] == "pending"
        assert status["progress"] == 0.0

        # 更新进度
        cache_manager.update_task_progress(task_id, 0.5, status="running")
        status = cache_manager.get_task_status(task_id)
        assert status["status"] == "running"
        assert status["progress"] == 0.5

        # 取消
        assert cache_manager.cancel_task(task_id) is True
        status = cache_manager.get_task_status(task_id)
        assert status["status"] == "cancelled"

        # 再次取消应返回 False
        assert cache_manager.cancel_task(task_id) is False


# ==================== 缓存集成测试 ====================


class TestCacheIntegration:
    """测试缓存优先策略集成"""

    def test_detect_market(self):
        """测试市场检测"""
        from data_provider.base import DataFetcherManager
        mgr = DataFetcherManager()

        assert mgr._detect_market("BTC-USDT") == "crypto_binance"
        assert mgr._detect_market("BTCUSDT") == "crypto_binance"
        assert mgr._detect_market("600519") == "cn"
        assert mgr._detect_market("000001") == "cn"

    def test_resolve_time_range_with_days(self):
        """测试时间范围解析（天数模式）"""
        from data_provider.base import DataFetcherManager
        mgr = DataFetcherManager()

        start_ms, end_ms = mgr._resolve_time_range(None, None, 30)
        assert end_ms > start_ms
        duration_days = (end_ms - start_ms) / (24 * 3600 * 1000)
        assert abs(duration_days - 30) < 1

    def test_resolve_time_range_with_dates(self):
        """测试时间范围解析（日期模式）"""
        from data_provider.base import DataFetcherManager
        mgr = DataFetcherManager()

        start_ms, end_ms = mgr._resolve_time_range("20240101", "20240110", 30)
        duration_days = (end_ms - start_ms) / (24 * 3600 * 1000)
        assert abs(duration_days - 9) < 1

    @patch("src.services.kline_store.get_kline_store")
    def test_cache_hit_skips_network(self, mock_get_store):
        """测试缓存命中跳过网络请求"""
        from data_provider.base import DataFetcherManager

        # 模拟权威缓存命中
        mock_store = MagicMock()
        mock_store.query_dataframe.return_value = pd.DataFrame({
            "open": [100], "high": [110], "low": [90], "close": [105],
            "volume": [1000], "amount": [100000],
        })
        mock_store.find_gaps.return_value = []  # 无缺口
        mock_get_store.return_value = mock_store

        mgr = DataFetcherManager()
        mgr._skip_cache = False

        df, source = mgr.get_daily_data("600519", start_date="20240101", end_date="20240102")
        assert source == "local_cache"
        assert len(df) == 1


# ==================== WebSocket Client 测试 ====================


class TestBinanceWSClient:
    """测试 Binance WebSocket 客户端基础功能"""

    def test_stream_name_generation(self):
        """测试流名称生成"""
        from data_provider.binance_ws_client import BinanceWSClient
        client = BinanceWSClient()
        # 验证对象创建不抛错
        assert client is not None

    def test_subscription_tracking(self):
        """测试订阅追踪"""
        from data_provider.binance_ws_client import BinanceWSClient
        client = BinanceWSClient()
        # 内部订阅列表应为空
        assert len(client._subscriptions) == 0


class TestOKXWSClient:
    """测试 OKX WebSocket 客户端基础功能"""

    def test_client_creation(self):
        """测试客户端创建"""
        from data_provider.okx_ws_client import OKXWSClient
        client = OKXWSClient()
        assert client is not None

    def test_subscription_tracking(self):
        """测试订阅追踪"""
        from data_provider.okx_ws_client import OKXWSClient
        client = OKXWSClient()
        assert len(client._subscriptions) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
