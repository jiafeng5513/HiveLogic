# -*- coding: utf-8 -*-
"""
Fetcher 能力矩阵测试（市场数据网关收敛计划 Phase 1 第 1 项）

测试场景:
1. 矩阵 vs 内省守卫: 每个 fetcher 类的矩阵能力 ⇔ 实际方法存在性
   （能力⇔方法映射规则见 data_provider/capabilities.py 模块 docstring，
   本测试对该映射做机械强制）
2. 矩阵 vs 盘点表一致性: markets 与 00_data_inventory.md §1.2 精确一致；
   datatypes 与 §1.2 一致，仅允许 DOCUMENTED_DEVIATIONS 中已声明的偏差
3. 替换等价性: 每个被替换的 hasattr 探针点，旧表达式 == 新矩阵查询，
   对全部 10 个已注册 fetcher 类逐点成立
"""

import ast
import inspect
import os
import sys
import textwrap

import pytest

# 确保 backend 目录在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data_provider.base import BaseFetcher  # noqa: E402
from data_provider.capabilities import (  # noqa: E402
    CAPABILITIES,
    CAPABILITY_MATRIX,
    MARKETS,
    fetchers_supporting,
    supports,
)
from data_provider.efinance_fetcher import EfinanceFetcher  # noqa: E402
from data_provider.akshare_fetcher import AkshareFetcher  # noqa: E402
from data_provider.tushare_fetcher import TushareFetcher  # noqa: E402
from data_provider.pytdx_fetcher import PytdxFetcher  # noqa: E402
from data_provider.baostock_fetcher import BaostockFetcher  # noqa: E402
from data_provider.yfinance_fetcher import YfinanceFetcher  # noqa: E402
from data_provider.longbridge_fetcher import LongbridgeFetcher  # noqa: E402
from data_provider.binance_fetcher import BinanceFetcher  # noqa: E402
from data_provider.okx_fetcher import OKXFetcher  # noqa: E402
from data_provider.tickflow_fetcher import TickFlowFetcher  # noqa: E402


# 全部已注册 fetcher 类（DataFetcherManager 默认 9 个 + 旁路的 TickFlow）
FETCHER_CLASSES = [
    EfinanceFetcher, AkshareFetcher, TushareFetcher, PytdxFetcher,
    BaostockFetcher, YfinanceFetcher, LongbridgeFetcher, BinanceFetcher,
    OKXFetcher, TickFlowFetcher,
]

# 简单方法探测：能力 ⇔ hasattr(cls, 方法名)（含继承）
SIMPLE_PROBE_METHODS = {
    'realtime_quote': 'get_realtime_quote',
    'chip_distribution': 'get_chip_distribution',
    'stock_name': 'get_stock_name',
    'belong_board': 'get_belong_board',
    'stock_list': 'get_stock_list',
    'symbol_list': 'get_symbol_list',
    # BaseFetcher 提供默认实现（返回 None），hasattr 恒真——
    # 与 base.py 原 2586 行探针语义逐点一致
    'sector_rankings': 'get_sector_rankings',
}


def _overrides(cls, method_name: str) -> bool:
    """方法在 MRO 中被真实覆盖（排除 BaseFetcher 默认实现）。"""
    return any(
        method_name in c.__dict__
        for c in cls.__mro__
        if c not in (BaseFetcher, object)
    )


def _method_only_raises(cls, method_name: str) -> bool:
    """方法体（除 docstring 外）仅由 raise 语句构成（AST 判定）。

    TickFlowFetcher._fetch_raw_data 无条件 raise DataFetchError
    （P0 仅支持 market review 端点），据此判定其不具备标准 daily 管线。
    """
    func = getattr(cls, method_name, None)
    if func is None:
        return False
    try:
        source = inspect.getsource(func)
    except (OSError, TypeError):
        return False
    tree = ast.parse(textwrap.dedent(source))
    fn_node = next(
        (n for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))),
        None,
    )
    if fn_node is None:
        return False
    body = fn_node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]  # 跳过 docstring
    return bool(body) and all(isinstance(stmt, ast.Raise) for stmt in body)


def _has_fundamentals_method(cls) -> bool:
    """fundamentals ⇔ 存在 get_financials 或 get_fundamental* 方法。"""
    return any(
        attr == 'get_financials' or attr.startswith('get_fundamental')
        for attr in dir(cls)
        if callable(getattr(cls, attr))
    )


def expected_capability(cls, capability: str) -> bool:
    """能力 -> 实际方法存在性的机械映射（与 capabilities.py docstring 规则一致）。"""
    if capability in SIMPLE_PROBE_METHODS:
        return hasattr(cls, SIMPLE_PROBE_METHODS[capability])
    if capability == 'daily':
        # daily ⇔ 覆盖 _fetch_raw_data 且方法体非"仅 raise"占位
        return _overrides(cls, '_fetch_raw_data') and not _method_only_raises(
            cls, '_fetch_raw_data'
        )
    if capability in ('main_indices', 'market_stats'):
        # ⇔ 子类真实覆盖（仅继承 BaseFetcher 默认实现不算）
        return _overrides(cls, f'get_{capability}')
    if capability == 'fundamentals':
        return _has_fundamentals_method(cls)
    raise AssertionError(f"未知能力: {capability}")


# ---------------------------------------------------------------------------
# 1. 矩阵 vs 内省守卫
# ---------------------------------------------------------------------------

class TestMatrixVsIntrospection:
    """矩阵声明的能力必须与实际方法存在性逐点一致。"""

    def test_matrix_covers_all_registered_fetchers(self):
        """矩阵条目与已注册 fetcher 类集合精确一致。"""
        assert set(CAPABILITY_MATRIX) == {cls.__name__ for cls in FETCHER_CLASSES}

    def test_matrix_fields_self_consistent(self):
        """条目的 fetcher 字段等于键名；市场/能力取值在枚举内。"""
        for name, entry in CAPABILITY_MATRIX.items():
            assert entry.fetcher == name
            assert entry.markets <= set(MARKETS)
            assert entry.capabilities <= set(CAPABILITIES)
            assert isinstance(entry.markets, frozenset)
            assert isinstance(entry.capabilities, frozenset)

    @pytest.mark.parametrize('cls', FETCHER_CLASSES, ids=lambda c: c.__name__)
    @pytest.mark.parametrize('capability', CAPABILITIES)
    def test_capability_matches_method_presence(self, cls, capability):
        """矩阵能力 ⇔ 实际方法存在性（按机械映射规则推导）。"""
        matrix_value = capability in CAPABILITY_MATRIX[cls.__name__].capabilities
        actual_value = expected_capability(cls, capability)
        assert matrix_value == actual_value, (
            f"{cls.__name__}.{capability}: 矩阵={matrix_value} "
            f"!= 内省={actual_value}"
        )


# ---------------------------------------------------------------------------
# 2. 矩阵 vs 盘点 1.2 表一致性
# ---------------------------------------------------------------------------

# 00_data_inventory.md §1.2 覆盖矩阵（市场列，逐格硬编码）
INVENTORY_1_2_MARKETS = {
    'EfinanceFetcher': {'cn'},
    'AkshareFetcher': {'cn', 'hk'},
    'TushareFetcher': {'cn', 'hk'},
    'PytdxFetcher': {'cn'},
    'BaostockFetcher': {'cn'},
    'YfinanceFetcher': {'cn', 'hk', 'us'},
    'LongbridgeFetcher': {'hk', 'us'},
    'BinanceFetcher': {'crypto'},
    'OKXFetcher': {'crypto'},
    'TickFlowFetcher': {'cn', 'hk', 'us'},
}

# 00_data_inventory.md §1.2 覆盖矩阵（数据类型列）。
# 列映射: 日K->daily, 实时->realtime_quote, 基本面->fundamentals,
#         筹码->chip_distribution, 指数->main_indices,
#         板块排名->sector_rankings, 股票列表->stock_list
# 取值约定: ✅/✅(注记) -> True；❌ -> False；⚠️（契约违反）-> False
INVENTORY_1_2_DATATYPES = {
    'EfinanceFetcher': {
        'daily': True, 'realtime_quote': True, 'fundamentals': True,
        'chip_distribution': False, 'main_indices': True,
        'sector_rankings': True, 'stock_list': False,
    },
    'AkshareFetcher': {
        'daily': True, 'realtime_quote': True, 'fundamentals': True,
        'chip_distribution': True, 'main_indices': False,
        'sector_rankings': False, 'stock_list': False,
    },
    'TushareFetcher': {
        'daily': True, 'realtime_quote': True, 'fundamentals': True,
        'chip_distribution': True, 'main_indices': True,
        'sector_rankings': True, 'stock_list': True,
    },
    'PytdxFetcher': {
        'daily': True, 'realtime_quote': False,  # 1.2 ⚠️返回dict -> 计 False
        'fundamentals': False, 'chip_distribution': False,
        'main_indices': False, 'sector_rankings': False, 'stock_list': False,
    },
    'BaostockFetcher': {
        'daily': True, 'realtime_quote': False, 'fundamentals': False,
        'chip_distribution': False, 'main_indices': False,
        'sector_rankings': False, 'stock_list': True,
    },
    'YfinanceFetcher': {
        'daily': True, 'realtime_quote': True, 'fundamentals': False,
        'chip_distribution': False, 'main_indices': True,
        'sector_rankings': False, 'stock_list': False,
    },
    'LongbridgeFetcher': {
        'daily': True, 'realtime_quote': True,
        'fundamentals': True,  # 1.2 ✅(衍生)
        'chip_distribution': False, 'main_indices': False,
        'sector_rankings': False, 'stock_list': False,
    },
    'BinanceFetcher': {
        'daily': True, 'realtime_quote': False, 'fundamentals': False,
        'chip_distribution': False, 'main_indices': False,
        'sector_rankings': False, 'stock_list': False,
    },
    'OKXFetcher': {
        'daily': True, 'realtime_quote': False, 'fundamentals': False,
        'chip_distribution': False, 'main_indices': False,
        'sector_rankings': False, 'stock_list': False,
    },
    'TickFlowFetcher': {
        'daily': True,  # 1.2 ✅(独立格式)
        'realtime_quote': True, 'fundamentals': True,  # 基本面 1.2 ✅(付费档)
        'chip_distribution': False, 'main_indices': True,
        'sector_rankings': False, 'stock_list': True,
    },
}

_SECTOR_RANKINGS_INHERIT_NOTE = (
    '继承 BaseFetcher 默认 get_sector_rankings（返回 None），hasattr 探针恒真；'
    '矩阵与被替换探针逐点一致故记 True，默认实现不产生真实数据'
)

# 矩阵与 1.2 表的已确认偏差（键: (fetcher, capability)）。
# 新增/消除偏差必须同步更新本表与矩阵条目的 note。
DOCUMENTED_DEVIATIONS = {
    ('PytdxFetcher', 'realtime_quote'): (
        '1.2 ⚠️：get_realtime_quote 方法存在但返回原生 dict，'
        '违反 UnifiedRealtimeQuote 契约；矩阵按方法存在性记 True，Phase 3 收敛'
    ),
    ('EfinanceFetcher', 'fundamentals'): (
        '1.2 ✅但无 get_financials/get_fundamental* 方法（仅 get_base_info），'
        '矩阵记 False'
    ),
    ('AkshareFetcher', 'fundamentals'): (
        '1.2 ✅但基本面经 AkshareFundamentalAdapter 旁路提供（manager 持有），'
        'fetcher 无 get_fundamental* 方法，矩阵记 False'
    ),
    ('TushareFetcher', 'fundamentals'): (
        '1.2 ✅但无 get_financials/get_fundamental* 方法，矩阵记 False'
    ),
    ('LongbridgeFetcher', 'fundamentals'): (
        '1.2 ✅(衍生)但无 get_financials/get_fundamental* 方法，矩阵记 False'
    ),
    ('AkshareFetcher', 'main_indices'): (
        '1.2 指数❌为过期记录：代码存在真实 get_main_indices 覆盖，矩阵记 True'
    ),
    ('TickFlowFetcher', 'daily'): (
        '1.2 ✅(独立格式)：_fetch_raw_data 无条件 raise，'
        '日K走 get_klines list-of-dicts 独立格式，矩阵记 False，Phase 3 收编'
    ),
    ('TickFlowFetcher', 'realtime_quote'): (
        '1.2 ✅：实时仅批量 get_realtime_quotes（复数），'
        '无单票 get_realtime_quote，矩阵记 False，Phase 3 适配'
    ),
    ('TickFlowFetcher', 'stock_list'): (
        '1.2 股票列表✅对应 get_symbol_list（矩阵 symbol_list 能力），'
        '非 get_stock_list，故 stock_list 记 False'
    ),
    ('AkshareFetcher', 'sector_rankings'): (
        '1.2 ❌为过期记录：代码存在真实 get_sector_rankings 覆盖，矩阵记 True'
    ),
    ('PytdxFetcher', 'sector_rankings'): _SECTOR_RANKINGS_INHERIT_NOTE,
    ('BaostockFetcher', 'sector_rankings'): _SECTOR_RANKINGS_INHERIT_NOTE,
    ('YfinanceFetcher', 'sector_rankings'): _SECTOR_RANKINGS_INHERIT_NOTE,
    ('LongbridgeFetcher', 'sector_rankings'): _SECTOR_RANKINGS_INHERIT_NOTE,
    ('BinanceFetcher', 'sector_rankings'): _SECTOR_RANKINGS_INHERIT_NOTE,
    ('OKXFetcher', 'sector_rankings'): _SECTOR_RANKINGS_INHERIT_NOTE,
    ('TickFlowFetcher', 'sector_rankings'): _SECTOR_RANKINGS_INHERIT_NOTE,
}


class TestInventoryConsistency:
    """矩阵与 00_data_inventory.md §1.2 覆盖矩阵的一致性。"""

    def test_markets_match_inventory_exactly(self):
        """markets 与 1.2 表市场列逐格一致。"""
        for name, expected_markets in INVENTORY_1_2_MARKETS.items():
            assert CAPABILITY_MATRIX[name].markets == frozenset(expected_markets), (
                f"{name}.markets={sorted(CAPABILITY_MATRIX[name].markets)} "
                f"!= 1.2 表 {sorted(expected_markets)}"
            )

    def test_matrix_fetcher_set_matches_inventory(self):
        """矩阵覆盖的 fetcher 集合与 1.2 表（10 个）精确一致。"""
        assert set(CAPABILITY_MATRIX) == set(INVENTORY_1_2_MARKETS)

    def test_datatypes_consistent_allowing_documented_deviations(self):
        """datatypes 与 1.2 表一致，偏差集合精确等于 DOCUMENTED_DEVIATIONS。"""
        actual_deviations = set()
        for name, expectations in INVENTORY_1_2_DATATYPES.items():
            entry = CAPABILITY_MATRIX[name]
            for capability, inventory_value in expectations.items():
                matrix_value = capability in entry.capabilities
                if matrix_value != inventory_value:
                    actual_deviations.add((name, capability))
        undocumented = actual_deviations - set(DOCUMENTED_DEVIATIONS)
        stale = set(DOCUMENTED_DEVIATIONS) - actual_deviations
        assert not undocumented, f"存在未声明的偏差: {undocumented}"
        assert not stale, f"偏差声明已过期（矩阵现已与 1.2 一致）: {stale}"

    def test_deviating_fetchers_carry_notes(self):
        """存在 1.2 偏差的 fetcher 必须在矩阵 note 中留有约束说明。"""
        deviating_fetchers = {name for name, _ in DOCUMENTED_DEVIATIONS}
        for name in deviating_fetchers:
            assert CAPABILITY_MATRIX[name].note, (
                f"{name} 与 1.2 表存在偏差但 note 为空"
            )


# ---------------------------------------------------------------------------
# 3. 替换等价性：旧 hasattr 表达式 == 新矩阵查询
# ---------------------------------------------------------------------------

# 被替换的探针点: (位置描述, 旧 hasattr 方法名, 新能力名)
REPLACED_PROBE_SITES = [
    ('base.py 实时行情循环 efinance 探针', 'get_realtime_quote', 'realtime_quote'),
    ('base.py 实时行情循环 akshare_em 探针', 'get_realtime_quote', 'realtime_quote'),
    ('base.py 实时行情循环 akshare_sina 探针', 'get_realtime_quote', 'realtime_quote'),
    ('base.py 实时行情循环 tencent 探针', 'get_realtime_quote', 'realtime_quote'),
    ('base.py 实时行情循环 tushare 探针', 'get_realtime_quote', 'realtime_quote'),
    ('base.py _try_fetcher_quote 探针', 'get_realtime_quote', 'realtime_quote'),
    ('base.py get_chip_distribution 探针', 'get_chip_distribution', 'chip_distribution'),
    ('base.py get_stock_name 探针', 'get_stock_name', 'stock_name'),
    ('base.py get_belong_boards 探针', 'get_belong_board', 'belong_board'),
    ('base.py batch_get_stock_names 探针', 'get_stock_list', 'stock_list'),
    ('base.py _get_sector_rankings_with_meta 探针', 'get_sector_rankings', 'sector_rankings'),
    ('symbol_list_service.py _try_tushare_stock_list 探针', 'get_stock_list', 'stock_list'),
    ('symbol_list_service.py _try_baostock_stock_list 探针', 'get_stock_list', 'stock_list'),
    ('symbol_list_service.py _try_tickflow_symbols 探针', 'get_symbol_list', 'symbol_list'),
]


class TestReplacementEquivalence:
    """每个被替换探针点：旧 hasattr 表达式 == 新矩阵查询（全部 fetcher 类）。"""

    @pytest.mark.parametrize(
        'site, method_name, capability',
        REPLACED_PROBE_SITES,
        ids=[s[0] for s in REPLACED_PROBE_SITES],
    )
    def test_old_hasattr_equals_new_supports(self, site, method_name, capability):
        for cls in FETCHER_CLASSES:
            old = hasattr(cls, method_name)
            new = supports(cls, capability)
            assert old == new, (
                f"{site}: {cls.__name__} hasattr({method_name})={old} "
                f"!= supports({capability})={new}"
            )

    def test_symbol_list_service_full_expressions(self):
        """symbol_list_service 三处替换保持完整布尔表达式等价（含未改动的 name 检查）。"""
        for cls in FETCHER_CLASSES:
            assert (
                cls.name == "TushareFetcher" and hasattr(cls, "get_stock_list")
            ) == (
                cls.name == "TushareFetcher" and supports(cls, "stock_list")
            )
            assert (
                cls.name == "BaostockFetcher" and hasattr(cls, "get_stock_list")
            ) == (
                cls.name == "BaostockFetcher" and supports(cls, "stock_list")
            )
            assert (
                cls.name == "TickFlowFetcher" and hasattr(cls, "get_symbol_list")
            ) == (
                cls.name == "TickFlowFetcher" and supports(cls, "symbol_list")
            )

    def test_supports_accepts_instance_class_and_string(self):
        """supports() 接受实例 / 类 / 类名字符串，三者结果一致。"""
        for cls in FETCHER_CLASSES:
            for capability in CAPABILITIES:
                assert supports(cls, capability) == supports(cls.__name__, capability)

    def test_unknown_fetcher_returns_false(self):
        """未知 fetcher 名防御性返回 False（与 hasattr 探测缺失方法语义一致）。"""
        for capability in CAPABILITIES:
            assert supports("NoSuchFetcher", capability) is False
        assert fetchers_supporting('daily')  # 矩阵查询自身可用

    def test_market_filter(self):
        """market 参数按矩阵 markets 元数据过滤。"""
        assert supports('TushareFetcher', 'daily', market='cn') is True
        assert supports('TushareFetcher', 'daily', market='us') is False
        assert supports('BinanceFetcher', 'daily', market='crypto') is True
        assert supports('BinanceFetcher', 'daily', market='cn') is False
        # 未知 fetcher 即使不带 market 也为 False
        assert supports('NoSuchFetcher', 'daily', market='cn') is False

    def test_fetchers_supporting(self):
        """fetchers_supporting 返回具备能力的 fetcher 类名列表。"""
        assert set(fetchers_supporting('realtime_quote')) == {
            'EfinanceFetcher', 'AkshareFetcher', 'TushareFetcher',
            'PytdxFetcher', 'YfinanceFetcher', 'LongbridgeFetcher',
        }
        assert set(fetchers_supporting('symbol_list')) == {'TickFlowFetcher'}
        assert set(fetchers_supporting('daily', market='crypto')) == {
            'BinanceFetcher', 'OKXFetcher',
        }
        assert fetchers_supporting('realtime_quote', market='crypto') == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
