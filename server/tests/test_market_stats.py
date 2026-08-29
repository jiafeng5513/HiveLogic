# -*- coding: utf-8 -*-
"""
calc_market_stats 共享实现行为锚定测试

背景：三个 fetcher（tushare/efinance/akshare）的 _calc_market_stats 复制粘贴
已合并为 data_provider.market_stats.calc_market_stats（网关收敛计划 Phase 1），
合并时修复了变量名冲突 bug（zip 循环变量遮蔽列名变量 + 候选列表重复字面量），
并新增必需列缺失时返回 None 的显式 guard（与原 KeyError 被调用方吞掉等价）。

测试场景:
1. 混合行情 DataFrame 的精确统计: up/down/flat/limit_up/limit_down 计数
2. 涨跌停价四舍五入手算锚定: 10% (10.0 -> 11.0 / 5.55 -> 6.11) 与
   30% 北交所 (10.0 -> 13.0 / 2.5 -> 3.25)
3. total_amount == 成交额全列求和 / 1e8（含被过滤行）
4. 必需列缺失 -> 返回 None 并记录 warning（显式 guard）
5. 返回 dict 键集合与合并前契约一致
6. 中文列名（代码/名称/最新价/昨收/成交额）与英文列名解析结果一致
7. 三个 fetcher 的私有副本已删除，统一引用共享实现
"""

import logging
import os
import sys

import numpy as np
import pandas as pd
import pytest

# 确保 backend 目录在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data_provider.market_stats import calc_market_stats  # noqa: E402


# 共享语料：覆盖 10%/20%(创业板)/20%(科创板)/30%(北交所)/5%(ST) 五档涨跌幅，
# 以及 '-' 价格、NaN 昨收、零成交额三种过滤场景
# 列: (代码, 名称, 最新价, 昨收, 成交额)
MIXED_ROWS = [
    ("600519", "贵州茅台", 11.0, 10.0, 100_000_000),    # 10% 涨停(11.0), up
    ("300750", "宁德时代", 55.0, 50.0, 200_000_000),    # 20% 创业板, up 未涨停(60.0)
    ("688981", "中芯国际", 70.0, 80.0, 300_000_000),    # 20% 科创板, down 未跌停(64.0)
    ("430047", "诺思兰德", 13.0, 10.0, 50_000_000),     # 30% 北交所 涨停(13.0), up
    ("600001", "ST测试", 10.5, 10.0, 80_000_000),       # 5% ST 涨停(10.5), up
    ("600002", "测试跌停", 9.0, 10.0, 60_000_000),      # 10% 跌停(9.0), down
    ("600003", "测试平盘", 10.0, 10.0, 40_000_000),     # flat
    ("600004", "测试停牌", "-", 10.0, 50_000_000),      # '-' 最新价 -> 过滤
    ("600005", "测试缺昨收", 11.0, np.nan, 50_000_000), # NaN 昨收 -> 过滤
    ("600006", "测试零额", 11.0, 10.0, 0),              # 成交额为 0 -> 过滤
]

ZH_COLUMNS = ["代码", "名称", "最新价", "昨收", "成交额"]
EN_COLUMNS = ["ts_code", "name", "close", "pre_close", "amount"]

EXPECTED_KEYS = {
    "up_count", "down_count", "flat_count",
    "limit_up_count", "limit_down_count", "total_amount",
}


def _make_df(columns) -> pd.DataFrame:
    return pd.DataFrame(MIXED_ROWS, columns=columns)


# ==================== 混合行情精确计数 ====================


class TestMixedMarketCounts:
    """混合涨跌幅档位 + 过滤行的精确统计锚定"""

    def test_exact_counts_chinese_columns(self):
        stats = calc_market_stats(_make_df(ZH_COLUMNS))
        assert stats == {
            "up_count": 4,
            "down_count": 2,
            "flat_count": 1,
            "limit_up_count": 3,
            "limit_down_count": 1,
            "total_amount": 9.3,
        }

    def test_dash_price_row_filtered(self):
        """'-' 最新价行（停牌）不计入任何计数"""
        df = pd.DataFrame(
            [("600519", "贵州茅台", "-", 10.0, 100_000_000)], columns=ZH_COLUMNS
        )
        stats = calc_market_stats(df)
        assert stats["up_count"] == 0
        assert stats["limit_up_count"] == 0

    def test_nan_pre_close_row_filtered(self):
        """NaN 昨收行不计入任何计数"""
        df = pd.DataFrame(
            [("600519", "贵州茅台", 11.0, np.nan, 100_000_000)], columns=ZH_COLUMNS
        )
        stats = calc_market_stats(df)
        assert stats["up_count"] == 0

    def test_zero_amount_row_filtered(self):
        """成交额为 0 的行不计入任何计数"""
        df = pd.DataFrame(
            [("600519", "贵州茅台", 11.0, 10.0, 0)], columns=ZH_COLUMNS
        )
        stats = calc_market_stats(df)
        assert stats["up_count"] == 0
        assert stats["limit_up_count"] == 0


# ==================== 涨跌停价四舍五入（手算锚定） ====================


class TestLimitPriceRounding:
    """np.floor(pre_close * (1 ± ratio) * 100 + 0.5) / 100.0 的手算锚定"""

    def test_10pct_limit_up(self):
        """10% 档: 昨收 10.0 -> 涨停 11.0（10.0 * 1.1 = 11.0）"""
        df = pd.DataFrame(
            [("600519", "贵州茅台", 11.0, 10.0, 1.0)], columns=ZH_COLUMNS
        )
        stats = calc_market_stats(df)
        assert stats["limit_up_count"] == 1

    def test_10pct_round_half_up(self):
        """10% 档半进一: 昨收 5.55 -> 涨停 6.11（5.55 * 1.1 = 6.105 -> 四舍五入 6.11）"""
        df = pd.DataFrame(
            [("600519", "贵州茅台", 6.11, 5.55, 1.0)], columns=ZH_COLUMNS
        )
        stats = calc_market_stats(df)
        assert stats["limit_up_count"] == 1
        # 6.10 未触及涨停价，不算涨停
        df.loc[0, "最新价"] = 6.10
        stats = calc_market_stats(df)
        assert stats["limit_up_count"] == 0

    def test_30pct_bse_limit_up(self):
        """30% 北交所档: 昨收 10.0 -> 涨停 13.0（10.0 * 1.3 = 13.0）"""
        df = pd.DataFrame(
            [("430047", "诺思兰德", 13.0, 10.0, 1.0)], columns=ZH_COLUMNS
        )
        stats = calc_market_stats(df)
        assert stats["limit_up_count"] == 1

    def test_30pct_bse_exact_quarter(self):
        """30% 北交所档: 昨收 2.5 -> 涨停 3.25（2.5 * 1.3 = 3.25）"""
        df = pd.DataFrame(
            [("430047", "诺思兰德", 3.25, 2.5, 1.0)], columns=ZH_COLUMNS
        )
        stats = calc_market_stats(df)
        assert stats["limit_up_count"] == 1

    def test_10pct_limit_down(self):
        """10% 档: 昨收 10.0 -> 跌停 9.0（10.0 * 0.9 = 9.0）"""
        df = pd.DataFrame(
            [("600519", "贵州茅台", 9.0, 10.0, 1.0)], columns=ZH_COLUMNS
        )
        stats = calc_market_stats(df)
        assert stats["limit_down_count"] == 1


# ==================== total_amount 汇总 ====================


class TestTotalAmount:
    """total_amount == 成交额全列求和 / 1e8（含被过滤行的成交额）"""

    def test_sum_includes_filtered_rows(self):
        stats = calc_market_stats(_make_df(ZH_COLUMNS))
        total = sum(row[4] for row in MIXED_ROWS) / 1e8
        assert stats["total_amount"] == pytest.approx(total)
        assert stats["total_amount"] == pytest.approx(9.3)


# ==================== 列名解析与返回契约 ====================


class TestColumnResolutionAndContract:
    """中文/英文列名等价解析 + 返回 dict 键集合契约"""

    def test_english_columns_resolve_identically(self):
        s_zh = calc_market_stats(_make_df(ZH_COLUMNS))
        s_en = calc_market_stats(_make_df(EN_COLUMNS))
        assert s_en == s_zh

    def test_return_dict_key_set(self):
        stats = calc_market_stats(_make_df(ZH_COLUMNS))
        assert set(stats.keys()) == EXPECTED_KEYS
        for key in ("up_count", "down_count", "flat_count",
                    "limit_up_count", "limit_down_count"):
            assert isinstance(stats[key], int)


# ==================== 必需列缺失 guard ====================


class TestMissingColumnGuard:
    """五个必需列任一缺失 -> 返回 None 并记录 warning（替代原 df[None] KeyError）"""

    @pytest.mark.parametrize(
        "drop_col",
        ["代码", "名称", "最新价", "昨收", "成交额"],
    )
    def test_any_required_column_missing_returns_none(self, drop_col):
        df = _make_df(ZH_COLUMNS).drop(columns=[drop_col])
        assert calc_market_stats(df) is None

    def test_missing_column_logs_warning(self, caplog):
        df = _make_df(ZH_COLUMNS).drop(columns=["最新价"])
        with caplog.at_level(logging.WARNING, logger="data_provider.market_stats"):
            result = calc_market_stats(df)
        assert result is None
        assert any("缺少必需列" in record.getMessage() for record in caplog.records)


# ==================== fetcher 收敛 ====================


class TestFetcherConvergence:
    """三个 fetcher 的私有 _calc_market_stats 已删除，统一引用共享实现"""

    def test_fetchers_no_private_copy(self):
        from data_provider import AkshareFetcher, EfinanceFetcher, TushareFetcher
        for cls in (TushareFetcher, EfinanceFetcher, AkshareFetcher):
            assert not hasattr(cls, "_calc_market_stats")

    def test_fetchers_use_shared_implementation(self):
        import data_provider.akshare_fetcher as akshare_fetcher
        import data_provider.efinance_fetcher as efinance_fetcher
        import data_provider.tushare_fetcher as tushare_fetcher
        for module in (tushare_fetcher, efinance_fetcher, akshare_fetcher):
            assert module.calc_market_stats is calc_market_stats
