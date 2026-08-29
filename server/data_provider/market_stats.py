# -*- coding: utf-8 -*-
"""
===================================
市场涨跌统计共享实现 (calc_market_stats)
===================================

为 tushare / efinance / akshare 三个 fetcher 的 get_market_stats
提供唯一共享实现（市场数据网关收敛计划 Phase 1，行为冻结）。

契约（与合并前三份复制粘贴版本逐字节一致，除下方注明的 bug 修复）：
1. 列名候选解析: next((c for c in [...] if c in df.columns), None)，首个命中即短路
2. 涨跌幅比例: is_bse_code -> 30% / is_kc_cy_stock -> 20% /
   is_st_stock -> 5% / 其余 10%（均基于去除前缀的纯数字代码判断）
3. 涨跌停价: np.floor(pre_close * (1 ± ratio) * 100 + 0.5) / 100.0（四舍五入到分）
4. 行过滤: 最新价/昨收为 NaN 或 '-'、成交额为 0 的行跳过（停牌）
5. total_amount = 成交额全列求和 / 1e8（含被过滤行的成交额）

相对原三份复制粘贴版本的 bug 修复（行为保持）：
- zip 循环变量改名 row_*，消除与列名变量（code_col/name_col/...）的命名冲突
- 候选列表去除重复字面量（'name','name' / '最新价','最新价' /
  '成交额','成交额' 等；next() 短路语义下重复项本就不可达，去重不改变解析结果）
- 五个必需列任一新解析为 None 时记录 warning 并返回 None；
  原实现 df[None] 抛 KeyError，由调用方 except Exception 吞掉后同样返回 None，
  对外结果等价，此处显式化
"""

import logging
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from .base import is_bse_code, is_kc_cy_stock, is_st_stock, normalize_stock_code

logger = logging.getLogger(__name__)


def calc_market_stats(df: pd.DataFrame) -> Optional[Dict[str, Any]]:
    """从行情 DataFrame 计算涨跌统计。"""
    df = df.copy()

    # 1. 提取基础比对数据：最新价、昨收
    # 兼容不同接口返回的列名 sina/em efinance tushare xtdata
    code_col = next((c for c in ['代码', '股票代码', 'ts_code','stock_code'] if c in df.columns), None)
    name_col = next((c for c in ['名称', '股票名称','name'] if c in df.columns), None)
    close_col = next((c for c in ['最新价', 'close','lastPrice'] if c in df.columns), None)
    pre_close_col = next((c for c in ['昨收', '昨日收盘', 'pre_close','lastClose'] if c in df.columns), None)
    amount_col = next((c for c in ['成交额', 'amount'] if c in df.columns), None)

    # 任一必需列缺失：显式返回 None（原实现 df[None] 抛 KeyError 由调用方吞掉，结果等价）
    if any(col is None for col in (code_col, name_col, close_col, pre_close_col, amount_col)):
        logger.warning(
            f"[market_stats] 行情数据缺少必需列，无法统计: "
            f"code={code_col}, name={name_col}, close={close_col}, "
            f"pre_close={pre_close_col}, amount={amount_col}, columns={list(df.columns)}"
        )
        return None

    limit_up_count = 0
    limit_down_count = 0
    up_count = 0
    down_count = 0
    flat_count = 0

    for row_code, row_name, row_price, row_pre_close, row_amount in zip(
        df[code_col], df[name_col], df[close_col], df[pre_close_col], df[amount_col]
    ):

        # 停牌过滤 efinance 的停牌数据有时候会缺失价格显示为 '-'，em 显示为none
        if pd.isna(row_price) or pd.isna(row_pre_close) or row_price in ['-'] or row_pre_close in ['-'] or row_amount == 0:
            continue

        # em、efinance 为str 需要转换为float
        row_price = float(row_price)
        row_pre_close = float(row_pre_close)

        # 获取去除前缀的纯数字代码
        pure_code = normalize_stock_code(str(row_code))

        # A. 确定每只股票的涨跌幅比例 (使用纯数字代码判断)
        if is_bse_code(pure_code):
            ratio = 0.30
        elif is_kc_cy_stock(pure_code): #pure_code.startswith(('688', '30')):
            ratio = 0.20
        elif is_st_stock(row_name): #'ST' in str_name:
            ratio = 0.05
        else:
            ratio = 0.10

        # B. 严格按照 A 股规则计算涨跌停价：昨收 * (1 ± 比例) -> 四舍五入保留2位小数
        limit_up_price = np.floor(row_pre_close * (1 + ratio) * 100 + 0.5) / 100.0
        limit_down_price = np.floor(row_pre_close * (1 - ratio) * 100 + 0.5) / 100.0

        limit_up_price_Tolerance = round(abs(row_pre_close * (1 + ratio) - limit_up_price), 10)
        limit_down_price_Tolerance = round(abs(row_pre_close * (1 - ratio) - limit_down_price), 10)

        # C. 精确比对
        if row_price > 0 :
            is_limit_up = (row_price > 0) and (abs(row_price - limit_up_price) <= limit_up_price_Tolerance)
            is_limit_down = (row_price > 0) and (abs(row_price - limit_down_price) <= limit_down_price_Tolerance)

            if is_limit_up:
                limit_up_count += 1
            if is_limit_down:
                limit_down_count += 1

            if row_price > row_pre_close:
                up_count += 1
            elif row_price < row_pre_close:
                down_count += 1
            else:
                flat_count += 1

    # 统计数量
    stats = {
        'up_count': up_count,
        'down_count': down_count,
        'flat_count': flat_count,
        'limit_up_count': limit_up_count,
        'limit_down_count': limit_down_count,
        'total_amount': 0.0,
    }

    # 成交额统计
    if amount_col and amount_col in df.columns:
        df[amount_col] = pd.to_numeric(df[amount_col], errors='coerce')
        stats['total_amount'] = (df[amount_col].sum() / 1e8)

    return stats
