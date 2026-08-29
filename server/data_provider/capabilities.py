# -*- coding: utf-8 -*-
"""
===================================
Fetcher 能力矩阵 (Capability Matrix)
===================================

市场数据网关收敛计划 Phase 1 第 1 项：
以显式声明的能力矩阵替代数据层的 hasattr() 能力探测
（base.py / symbol_list_service.py 中的探针点已全部改为矩阵查询）。

矩阵内容推导规则（能力粒度与"被探测的方法名"对齐，保证替换后行为逐点一致；
tests/test_capabilities.py 的守卫测试对以下规则做机械强制）：

1. 简单方法探测（⇔ hasattr(cls, 方法名)，含继承）：
   - realtime_quote    ⇔ get_realtime_quote
   - chip_distribution ⇔ get_chip_distribution
   - stock_name        ⇔ get_stock_name
   - belong_board      ⇔ get_belong_board
   - stock_list        ⇔ get_stock_list
   - symbol_list       ⇔ get_symbol_list
2. daily ⇔ 子类覆盖 _fetch_raw_data 且方法体非"仅 raise"占位。
   TickFlowFetcher._fetch_raw_data 无条件 raise DataFetchError
   （P0 仅支持 market review 端点），故 daily=False；
   其日K走 get_klines 独立 list-of-dicts 格式，Phase 3 收编。
3. main_indices / market_stats ⇔ 子类真实覆盖 get_main_indices /
   get_market_stats（仅继承 BaseFetcher 默认实现不算）。
4. sector_rankings ⇔ hasattr(cls, 'get_sector_rankings')：BaseFetcher 提供
   默认实现（返回 None），全部 fetcher 继承为 True——与被替换的探针
   （base.py 原 2586 行 `hasattr(fetcher, 'get_sector_rankings')`）保持逐点
   一致；真实覆盖仅 Efinance / Akshare / Tushare。
5. fundamentals ⇔ 存在 get_financials 或 get_fundamental* 方法。

markets 为声明性元数据，与盘点文档 00_data_inventory.md §1.2 覆盖矩阵
逐格一致；datatypes 与 §1.2 的已确认偏差记录在各条目 note 及
tests/test_capabilities.py 的 DOCUMENTED_DEVIATIONS 中。

已知契约偏差（Phase 3 处理）：
- PytdxFetcher.get_realtime_quote 返回原生 dict，违反 UnifiedRealtimeQuote 契约
- TickFlowFetcher 实时仅批量 get_realtime_quotes（复数），无单票方法
- TickFlowFetcher 日K为 list-of-dicts 独立格式，不走 BaseFetcher 管线

本模块不 import data_provider 内任何模块（无循环依赖）。
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

MARKETS = ('cn', 'hk', 'us', 'crypto')

# 能力粒度与"被探测的方法名"对齐，保证替换后行为逐点一致
CAPABILITIES = ('daily', 'realtime_quote', 'chip_distribution', 'stock_name',
                'belong_board', 'stock_list', 'symbol_list', 'sector_rankings',
                'main_indices', 'market_stats', 'fundamentals')


@dataclass(frozen=True)
class FetcherCapability:
    fetcher: str                 # 类名，如 'TushareFetcher'
    markets: frozenset           # 覆盖市场（来自盘点 1.2，声明性元数据）
    capabilities: frozenset      # 具备的能力（必须与实际方法存在性一致）
    note: str = ''               # 认证/付费分档/契约偏差等约束声明


# 继承 BaseFetcher 默认 get_sector_rankings（返回 None）带来的恒真能力，
# 见模块 docstring 规则 4；真实覆盖仅 Efinance / Akshare / Tushare。
_INHERITED_SECTOR_RANKINGS = 'sector_rankings'

CAPABILITY_MATRIX: Dict[str, FetcherCapability] = {
    'EfinanceFetcher': FetcherCapability(
        fetcher='EfinanceFetcher',
        markets=frozenset({'cn'}),
        capabilities=frozenset({
            'daily', 'realtime_quote', 'belong_board',
            _INHERITED_SECTOR_RANKINGS, 'main_indices', 'market_stats',
        }),
        note='1.2 标基本面✅但无 get_financials/get_fundamental* 方法'
             '（仅 get_base_info），fundamentals=False',
    ),
    'AkshareFetcher': FetcherCapability(
        fetcher='AkshareFetcher',
        markets=frozenset({'cn', 'hk'}),
        capabilities=frozenset({
            'daily', 'realtime_quote', 'chip_distribution',
            _INHERITED_SECTOR_RANKINGS, 'main_indices', 'market_stats',
        }),
        note='基本面经 AkshareFundamentalAdapter 旁路提供（manager 持有），'
             'fetcher 无 get_fundamental* 方法，fundamentals=False；'
             '1.2 指数❌为过期记录，代码存在真实 get_main_indices 覆盖',
    ),
    'TushareFetcher': FetcherCapability(
        fetcher='TushareFetcher',
        markets=frozenset({'cn', 'hk'}),
        capabilities=frozenset({
            'daily', 'realtime_quote', 'chip_distribution', 'stock_name',
            'stock_list', _INHERITED_SECTOR_RANKINGS, 'main_indices',
            'market_stats',
        }),
        note='需 TUSHARE_TOKEN（未配置时不可用、优先级降为 2）；'
             '1.2 标基本面✅但无 get_fundamental* 方法，fundamentals=False',
    ),
    'PytdxFetcher': FetcherCapability(
        fetcher='PytdxFetcher',
        markets=frozenset({'cn'}),
        capabilities=frozenset({
            'daily', 'realtime_quote', 'stock_name',
            _INHERITED_SECTOR_RANKINGS,
        }),
        note='get_realtime_quote 返回原生 dict，违反 UnifiedRealtimeQuote 契约'
             '（盘点 1.2 ⚠️），Phase 3 收敛',
    ),
    'BaostockFetcher': FetcherCapability(
        fetcher='BaostockFetcher',
        markets=frozenset({'cn'}),
        capabilities=frozenset({
            'daily', 'stock_name', 'stock_list', _INHERITED_SECTOR_RANKINGS,
        }),
        note='匿名登录；无实时报价能力',
    ),
    'YfinanceFetcher': FetcherCapability(
        fetcher='YfinanceFetcher',
        markets=frozenset({'cn', 'hk', 'us'}),
        capabilities=frozenset({
            'daily', 'realtime_quote', _INHERITED_SECTOR_RANKINGS,
            'main_indices',
        }),
        note='sector_rankings 继承 BaseFetcher 默认实现（返回 None），'
             '探针恒真但无真实数据',
    ),
    'LongbridgeFetcher': FetcherCapability(
        fetcher='LongbridgeFetcher',
        markets=frozenset({'hk', 'us'}),
        capabilities=frozenset({
            'daily', 'realtime_quote', 'stock_name',
            _INHERITED_SECTOR_RANKINGS,
        }),
        note='需 3 个 API key；1.2 标基本面✅(衍生)但无 get_fundamental* 方法，'
             'fundamentals=False',
    ),
    'BinanceFetcher': FetcherCapability(
        fetcher='BinanceFetcher',
        markets=frozenset({'crypto'}),
        capabilities=frozenset({'daily', _INHERITED_SECTOR_RANKINGS}),
        note='API key 可选（公开行情免 key）',
    ),
    'OKXFetcher': FetcherCapability(
        fetcher='OKXFetcher',
        markets=frozenset({'crypto'}),
        capabilities=frozenset({'daily', _INHERITED_SECTOR_RANKINGS}),
        note='API key 可选（公开行情免 key）',
    ),
    'TickFlowFetcher': FetcherCapability(
        fetcher='TickFlowFetcher',
        markets=frozenset({'cn', 'hk', 'us'}),
        capabilities=frozenset({
            'symbol_list', _INHERITED_SECTOR_RANKINGS, 'main_indices',
            'market_stats', 'fundamentals',
        }),
        note='需 TICKFLOW_API_KEY；日K/实时为独立格式：_fetch_raw_data 无条件 '
             'raise（daily=False，get_klines 独立格式，Phase 3 收编），实时仅批量 '
             'get_realtime_quotes 无单票 get_realtime_quote（realtime_quote=False，'
             'Phase 3 适配）；get_financials 需付费档（Expert）；'
             '不在 DataFetcherManager 默认列表（priority=99）',
    ),
}


def _resolve_fetcher_name(fetcher_or_name) -> str:
    """从实例 / 类 / 类名字符串解析 fetcher 类名。"""
    if isinstance(fetcher_or_name, str):
        return fetcher_or_name
    if isinstance(fetcher_or_name, type):
        return fetcher_or_name.__name__
    return type(fetcher_or_name).__name__


def supports(fetcher_or_name, capability: str, market: Optional[str] = None) -> bool:
    """
    查询 fetcher 是否具备某能力（可选限定市场）。

    Args:
        fetcher_or_name: fetcher 实例、类或类名字符串（如 'TushareFetcher'）
        capability: CAPABILITIES 中的能力名
        market: 可选，MARKETS 中的市场名；给定时不覆盖该市场则返回 False

    Returns:
        bool；未知 fetcher 名返回 False（与 hasattr 探测缺失方法的语义一致）
    """
    entry = CAPABILITY_MATRIX.get(_resolve_fetcher_name(fetcher_or_name))
    if entry is None:
        return False
    if capability not in entry.capabilities:
        return False
    if market is not None and market not in entry.markets:
        return False
    return True


def fetchers_supporting(capability: str, market: Optional[str] = None) -> List[str]:
    """
    列出具备某能力（可选限定市场）的全部 fetcher 类名。

    Args:
        capability: CAPABILITIES 中的能力名
        market: 可选，MARKETS 中的市场名

    Returns:
        fetcher 类名列表（按矩阵声明顺序）
    """
    return [
        name
        for name, entry in CAPABILITY_MATRIX.items()
        if capability in entry.capabilities
        and (market is None or market in entry.markets)
    ]
