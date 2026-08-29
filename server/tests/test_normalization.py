# -*- coding: utf-8 -*-
"""
规范化规则单元测试（市场数据网关收敛计划 Phase 1 第 4 项）

覆盖：
1. compute_pct_chg：本地计算首行 NaN（禁止 fillna(0) 假信号）
2. hands_to_shares：东财系 A股 手→股 转换
3. market_currency：amount 本地币种标记
4. 各 fetcher 落地点的行为钉住：
   - akshare 东财/ETF/腾讯路径 volume ×100，新浪/港股路径不转换
   - efinance _normalize_data volume ×100
   - yfinance / pytdx _normalize_data pct_chg 首行 NaN
"""

import os
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data_provider.normalization import (
    AMOUNT_BASE,
    VOLUME_BASE_UNIT,
    compute_pct_chg,
    hands_to_shares,
    market_currency,
)
from data_provider.akshare_fetcher import AkshareFetcher
from data_provider.efinance_fetcher import EfinanceFetcher
from data_provider.pytdx_fetcher import PytdxFetcher
from data_provider.yfinance_fetcher import YfinanceFetcher


def _em_a_share_frame(volumes=(100.0, 200.0, 300.0)):
    """东财 A股原始列结构（成交量单位：手）。"""
    return pd.DataFrame({
        '日期': ['2026-01-01', '2026-01-02', '2026-01-03'],
        '开盘': [100.0, 110.0, 105.0],
        '收盘': [110.0, 105.0, 115.0],
        '最高': [112.0, 111.0, 116.0],
        '最低': [99.0, 104.0, 104.0],
        '成交量': list(volumes),
        '成交额': [11000.0, 21000.0, 33000.0],
        '涨跌幅': [np.nan, -4.55, 9.52],
    })


class TestComputePctChg:
    """本地 pct_chg 计算：首行 NaN、不填充、不内联 round。"""

    def test_first_row_is_nan_not_zero(self):
        close = pd.Series([100.0, 110.0, 105.0])
        result = compute_pct_chg(close)
        assert pd.isna(result.iloc[0])
        assert result.iloc[0] != 0

    def test_values_match_pct_change_times_100(self):
        close = pd.Series([100.0, 110.0, 105.0])
        result = compute_pct_chg(close)
        assert result.iloc[1] == pytest.approx(10.0)
        assert result.iloc[2] == pytest.approx(-4.5454545, rel=1e-6)

    def test_caller_side_rounding_still_works(self):
        close = pd.Series([100.0, 103.333, 101.0])
        result = compute_pct_chg(close).round(2)
        assert result.iloc[1] == pytest.approx(3.33)
        assert pd.isna(result.iloc[0])


class TestHandsToShares:
    """手 -> 股 转换（×100），标量与 Series 均可。"""

    def test_series(self):
        result = hands_to_shares(pd.Series([1.0, 2.5, 300.0]))
        assert list(result) == [100.0, 250.0, 30000.0]

    def test_scalar(self):
        assert hands_to_shares(3) == 300
        assert hands_to_shares(2.5) == 250.0


class TestMarketCurrency:
    """amount 本地币种标记。"""

    def test_cn(self):
        assert market_currency('600519') == 'CNY'
        assert market_currency('000001.SZ') == 'CNY'

    def test_hk(self):
        assert market_currency('HK00700') == 'HKD'
        assert market_currency('00700.HK') == 'HKD'

    def test_us(self):
        assert market_currency('AAPL') == 'USD'

    def test_crypto_quote_parsing(self):
        assert market_currency('BTC-USD') == 'USD'
        assert market_currency('BTCUSDT') == 'USDT'
        assert market_currency('ETHUSDC') == 'USDC'
        assert market_currency('ETHBTC') == 'BTC'

    def test_constants(self):
        assert VOLUME_BASE_UNIT == 'shares'
        assert AMOUNT_BASE == 'local_currency'


class TestAkshareVolumeNormalization:
    """akshare 各日K路径的成交量量纲落地（东财系 ×100，新浪/港股不转）。"""

    @pytest.fixture
    def fetcher(self):
        f = AkshareFetcher(sleep_min=0, sleep_max=0)
        f._enforce_rate_limit = MagicMock()
        f._set_random_user_agent = MagicMock()
        return f

    def test_em_path_converts_hands_to_shares(self, fetcher):
        with patch('akshare.stock_zh_a_hist', return_value=_em_a_share_frame()):
            df = fetcher._fetch_stock_data_em('600519', '2026-01-01', '2026-01-03')
        assert list(df['成交量']) == [10000.0, 20000.0, 30000.0]

    def test_etf_path_converts_hands_to_shares(self, fetcher):
        with patch('akshare.fund_etf_hist_em', return_value=_em_a_share_frame()):
            df = fetcher._fetch_etf_data('510300', '2026-01-01', '2026-01-03')
        assert list(df['成交量']) == [10000.0, 20000.0, 30000.0]

    def test_tx_path_converts_hands_to_shares(self, fetcher):
        tx_frame = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-02'],
            'open': [100.0, 110.0], 'close': [110.0, 105.0],
            'high': [112.0, 111.0], 'low': [99.0, 104.0],
            'volume': [100.0, 200.0], 'amount': [11000.0, 21000.0],
        })
        with patch('akshare.stock_zh_a_hist_tx', return_value=tx_frame):
            df = fetcher._fetch_stock_data_tx('600519', '2026-01-01', '2026-01-02')
        assert list(df['成交量']) == [10000.0, 20000.0]
        # 规范化：腾讯路径本地计算 pct_chg 首行 NaN
        assert pd.isna(df['涨跌幅'].iloc[0])

    def test_sina_path_not_converted(self, fetcher):
        sina_frame = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-02'],
            'open': [100.0, 110.0], 'high': [112.0, 111.0],
            'low': [99.0, 104.0], 'close': [110.0, 105.0],
            'volume': [10000.0, 20000.0], 'amount': [1100000.0, 2100000.0],
        })
        with patch('akshare.stock_zh_a_daily', return_value=sina_frame):
            df = fetcher._fetch_stock_data_sina('600519', '2026-01-01', '2026-01-02')
        assert list(df['成交量']) == [10000.0, 20000.0]
        # 规范化：新浪路径本地计算 pct_chg 首行 NaN
        assert pd.isna(df['涨跌幅'].iloc[0])

    def test_hk_path_not_converted(self, fetcher):
        with patch('akshare.stock_hk_hist', return_value=_em_a_share_frame()):
            df = fetcher._fetch_hk_data('00700', '2026-01-01', '2026-01-03')
        assert list(df['成交量']) == [100.0, 200.0, 300.0]


class TestEfinanceVolumeNormalization:
    """efinance（东财后端）_normalize_data 成交量 ×100。"""

    def test_volume_converted(self):
        fetcher = EfinanceFetcher(sleep_min=0, sleep_max=0)
        raw = _em_a_share_frame()
        raw['股票代码'] = '600519'
        raw['股票名称'] = '贵州茅台'
        df = fetcher._normalize_data(raw, '600519')
        assert list(df['volume']) == [10000.0, 20000.0, 30000.0]
        # 源直给 pct_chg（涨跌幅列）不受影响
        assert df['pct_chg'].iloc[1] == pytest.approx(-4.55)

    def test_missing_volume_fills_zero(self):
        fetcher = EfinanceFetcher(sleep_min=0, sleep_max=0)
        raw = _em_a_share_frame().drop(columns=['成交量'])
        df = fetcher._normalize_data(raw, '600519')
        assert list(df['volume']) == [0, 0, 0]


class TestPctChgSites:
    """yfinance / pytdx 规范化落地：pct_chg 首行 NaN、round(2) 保留。"""

    def test_yfinance_first_row_nan_and_rounded(self):
        fetcher = YfinanceFetcher()
        raw = pd.DataFrame({
            'Date': ['2026-01-01', '2026-01-02', '2026-01-03'],
            'Open': [100.0, 110.0, 105.0], 'High': [112.0, 111.0, 116.0],
            'Low': [99.0, 104.0, 104.0], 'Close': [100.0, 110.0, 105.0],
            'Volume': [1000.0, 2000.0, 1500.0],
        })
        df = fetcher._normalize_data(raw, 'AAPL')
        assert pd.isna(df['pct_chg'].iloc[0])
        assert df['pct_chg'].iloc[1] == pytest.approx(10.0)
        assert df['pct_chg'].iloc[2] == pytest.approx(-4.55)

    def test_pytdx_first_row_nan_and_rounded(self):
        fetcher = PytdxFetcher()
        raw = pd.DataFrame({
            'datetime': ['2026-01-01', '2026-01-02', '2026-01-03'],
            'open': [100.0, 110.0, 105.0], 'high': [112.0, 111.0, 116.0],
            'low': [99.0, 104.0, 104.0], 'close': [100.0, 110.0, 105.0],
            'vol': [1000.0, 2000.0, 1500.0],
        })
        df = fetcher._normalize_data(raw, '600519')
        assert pd.isna(df['pct_chg'].iloc[0])
        assert df['pct_chg'].iloc[1] == pytest.approx(10.0)

    def test_pytdx_volume_untouched(self):
        """pytdx volume 量纲未审计（见 normalization.py），本阶段不转换。"""
        fetcher = PytdxFetcher()
        raw = pd.DataFrame({
            'datetime': ['2026-01-01', '2026-01-02'],
            'open': [100.0, 110.0], 'high': [112.0, 111.0],
            'low': [99.0, 104.0], 'close': [110.0, 105.0],
            'vol': [1234.0, 5678.0],
        })
        df = fetcher._normalize_data(raw, '600519')
        assert list(df['volume']) == [1234.0, 5678.0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
