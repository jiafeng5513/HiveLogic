# -*- coding: utf-8 -*-
"""
===================================
行情数据规范化规则 (Normalization Rules)
===================================

市场数据网关收敛计划 Phase 1 第 4 项：规范化规则文档化 + 落地。
本模块是全部规范化规则的唯一实现落点，fetcher 不再各自内联规则。

规则总览
--------

1. pct_chg（涨跌幅，单位 %）
   - 源直给优先：tushare（pct_chg）、efinance（涨跌幅）、baostock（pctChg）、
     akshare 东财路径（涨跌幅）直接使用源值，本模块不参与。
   - 本地计算时（yfinance / pytdx / akshare 新浪·腾讯·美股路径）一律走
     compute_pct_chg()：close.pct_change()*100，**首行保持 NaN**，禁止 fillna(0)
   （首行 0 是"无涨跌"的假信号，会污染统计与策略输入）。
   - 调用点原有的 round() 精度保持不变（在调用点执行）。

2. volume（成交量）——基准量纲：股（shares）
   - 已是股：tushare A股（fetcher 内 ×100）、tushare 港股、baostock、
     yfinance、akshare 新浪路径（stock_zh_a_daily）、akshare 美股路径
     （stock_us_daily）、binance/okx/longbridge。本模块不参与。
   - 手→股转换（hands_to_shares，×100）应用于东方财富系 A股路径：
     akshare stock_zh_a_hist / fund_etf_hist_em / stock_zh_a_hist_tx、
     efinance get_quote_history（股票与 ETF 同一接口）。
   - **量纲待确认（未转换）**：akshare stock_hk_hist（东财港股）、pytdx 日K。
     两处源量纲缺乏确证，贸然 ×100 有静默放大 100 倍的风险，保持原值，
     待有实证（与权威源同日对比）后再收敛。
   - 既定契约差异：实时行情层 UnifiedRealtimeQuote.volume 单位为**手**
     （见 realtime_types.py），日K层为**股**。两层量纲不同是有意保留的
     现状（realtime schema 变更影响 API 消费方，不在本期范围）。

3. amount（成交额）——本地币种，不折算
   - 各市场保持本地币种：A股=CNY、港股=HKD、美股=USD、加密=计价币种。
   - 通过 market_currency() 提供币种标记；不引入汇率折算（避免汇率
     数据源依赖与历史汇率对齐问题）。
   - yfinance 与 akshare 美股的 amount 为估算值（volume×close），语义
     与源直给不同，属已知偏差（见盘点文档 1.3）。

已知下游影响
------------
- kline_data 缓存中本变更前写入的 efinance/akshare 东财系 A股 volume 为
  手量纲，新写入为股量纲，缓存失效/刷新前同一代码可能存在混合量纲。
  缓存清理由 Phase 2（KlineStore）统一处理。
"""

from typing import Union

import pandas as pd

from .base import _market_tag
from .binance_fetcher import is_crypto_code

# 日K volume 基准量纲：股
VOLUME_BASE_UNIT = 'shares'

# amount 基准：本地币种（不折算）
AMOUNT_BASE = 'local_currency'

# 市场 -> 币种
_MARKET_CURRENCY = {'cn': 'CNY', 'hk': 'HKD', 'us': 'USD'}

# 加密代码中的已知计价币种（与 binance_fetcher.is_crypto_code 的 quote 集合对齐；
# 按特异性降序匹配，避免 USD 先于 USDT 命中）
_CRYPTO_QUOTE_SUFFIXES = ('USDT', 'USDC', 'BUSD', 'USD', 'BTC', 'ETH', 'BNB')


def compute_pct_chg(close: pd.Series) -> pd.Series:
    """
    本地计算涨跌幅（%）：close.pct_change() * 100。

    首行保持 NaN（无前值可比对），**禁止 fillna(0)**——首行 0 是假信号。
    调用点如需保留原有显示精度，自行 .round()。
    """
    return close.pct_change() * 100


def hands_to_shares(volume: Union[pd.Series, float, int]) -> Union[pd.Series, float, int]:
    """
    成交量 手 -> 股（×100）。

    仅用于东方财富系 A股日K路径（akshare stock_zh_a_hist / fund_etf_hist_em /
    stock_zh_a_hist_tx、efinance get_quote_history），其他路径勿用。
    支持标量与 pandas Series。
    """
    return volume * 100


def market_currency(code: str) -> str:
    """
    返回代码所属市场的本地币种标记：CNY / HKD / USD / 加密计价币种。

    - A股 -> 'CNY'，港股 -> 'HKD'，美股 -> 'USD'
    - 加密 -> 解析计价币种：'BTC-USD' -> 'USD'，'BTCUSDT' -> 'USDT'，
      'ETHUSDC' -> 'USDC'；无法解析时回退 'USD'
    """
    if is_crypto_code(code):
        upper = (code or '').strip().upper()
        if '-' in upper:
            return upper.rsplit('-', 1)[1] or 'USD'
        for suffix in _CRYPTO_QUOTE_SUFFIXES:
            if upper.endswith(suffix):
                return suffix
        return 'USD'
    return _MARKET_CURRENCY[_market_tag(code)]
