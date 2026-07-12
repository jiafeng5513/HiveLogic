# -*- coding: utf-8 -*-
"""
Vision tools — 服务端生成 K 线/分时截图，供 vision agent "看图"。

Phase C.2 核心工具:
- capture_kline_chart: 用 matplotlib 生成 K 线截图（含成交量、均线标注），返回 base64 PNG
- capture_intraday_chart: 分时图截图（基于实时行情 + 最近日 K）

设计要点:
  1. 不依赖 mplfinance（未安装），用 matplotlib 原生绘制蜡烛图
  2. 数据来源: DataFetcherManager.get_daily_data()（与 data_tools 一致）
  3. 返回 base64 PNG，可直接嵌入 OpenAI vision 消息:
     {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
  4. category="vision": 与 data/analysis/search/code 并列
  5. 不需要 requires_approval — 看图是只读操作，无副作用
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any, Dict, List, Optional

from src.agent.tools.registry import ToolDefinition, ToolParameter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# matplotlib 后端隔离 — 确保无显示器环境可用
# ---------------------------------------------------------------------------

def _ensure_agg_backend() -> None:
    """强制使用 Agg 后端（线程安全、无 GUI 依赖）。仅初始化一次。"""
    import matplotlib
    if matplotlib.get_backend().lower() != "agg":
        matplotlib.use("Agg", force=True)


_ensure_agg_backend()


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _fetch_daily_df(stock_code: str, days: int):
    """复用 data_tools 的 DataFetcherManager 获取日 K DataFrame。"""
    from data_provider import DataFetcherManager
    manager = DataFetcherManager()
    df, source = manager.get_daily_data(stock_code, days=days)
    return df, source


def _df_to_base64_png(
    df,
    stock_code: str,
    *,
    with_volume: bool = True,
    with_ma: bool = True,
    ma_periods: tuple = (5, 10, 20),
    title_suffix: str = "",
) -> str:
    """将 OHLCV DataFrame 渲染为 K 线截图，返回 base64 PNG 字符串。

    布局: 上图 K 线 + 均线，下图成交量。
    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import pandas as pd
    import numpy as np

    if df is None or df.empty:
        raise ValueError("Empty DataFrame, cannot render chart")

    # 标准化列名
    required = {"date", "open", "high", "low", "close", "volume"}
    if not required.issubset(set(df.columns)):
        # 尝试小写化
        df = df.rename(columns={c: str(c).lower() for c in df.columns})
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing columns: {missing}")

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    # 限制行数避免图过密
    max_bars = 120
    if len(df) > max_bars:
        df = df.tail(max_bars).reset_index(drop=True)

    n = len(df)
    x = np.arange(n)

    fig_height = 8 if with_volume else 6
    fig, axes = plt.subplots(
        2 if with_volume else 1,
        1,
        figsize=(14, fig_height),
        gridspec_kw={"height_ratios": [3, 1]} if with_volume else None,
        sharex=True,
    )
    if not with_volume:
        ax_price = axes
    else:
        ax_price = axes[0]
        ax_vol = axes[1]

    # --- 蜡烛图 ---
    up = df["close"] >= df["open"]
    down = ~up

    # 上涨蜡烛（红色，A股惯例）
    ax_price.vlines(x[up], df["low"][up], df["high"][up], color="#d62728", linewidth=0.8)
    ax_price.bar(
        x[up],
        (df["close"][up] - df["open"][up]).clip(lower=0),
        bottom=df["open"][up],
        width=0.6,
        color="#d62728",
        edgecolor="#d62728",
    )
    # 下跌蜡烛（绿色）
    ax_price.vlines(x[down], df["low"][down], df["high"][down], color="#2ca02c", linewidth=0.8)
    ax_price.bar(
        x[down],
        (df["open"][down] - df["close"][down]).clip(lower=0),
        bottom=df["close"][down],
        width=0.6,
        color="#2ca02c",
        edgecolor="#2ca02c",
    )

    # --- 均线 ---
    if with_ma:
        ma_colors = {"ma5": "#ff9900", "ma10": "#9966cc", "ma20": "#00bfff"}
        for period in ma_periods:
            col = f"ma{period}"
            ma_values = df["close"].rolling(window=period, min_periods=1).mean()
            color = ma_colors.get(col, None)
            ax_price.plot(x, ma_values, label=col.upper(), linewidth=1.2, color=color)

        ax_price.legend(loc="upper left", fontsize=9)

    # --- 成交量 ---
    if with_volume:
        vol_colors = np.where(up, "#d62728", "#2ca02c")
        ax_vol.bar(x, df["volume"], width=0.6, color=vol_colors, alpha=0.7)
        ax_vol.set_ylabel("Volume", fontsize=10)

    # --- 坐标轴 / 标题 ---
    ax_price.set_title(f"{stock_code} {title_suffix}".strip(), fontsize=13, fontweight="bold")
    ax_price.set_ylabel("Price", fontsize=10)
    ax_price.grid(True, alpha=0.3)

    # X 轴日期标签（稀疏显示）
    tick_step = max(1, n // 10)
    tick_positions = x[::tick_step]
    tick_labels = df["date"].dt.strftime("%m-%d").iloc[::tick_step].tolist()
    ax_price.set_xticks(tick_positions)
    ax_price.set_xticklabels(tick_labels, rotation=30, ha="right", fontsize=8)

    # 最新价标注
    last_idx = n - 1
    last_close = df["close"].iloc[last_idx]
    last_date = df["date"].iloc[last_idx].strftime("%Y-%m-%d")
    ax_price.annotate(
        f"{last_close:.2f}",
        xy=(last_idx, last_close),
        xytext=(last_idx + 1, last_close),
        fontsize=10,
        color="#d62728" if up.iloc[-1] else "#2ca02c",
        fontweight="bold",
    )

    fig.tight_layout()

    # --- 导出 base64 ---
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    buf.close()
    return b64


# ---------------------------------------------------------------------------
# 工具处理器
# ---------------------------------------------------------------------------

def _handle_capture_kline_chart(
    stock_code: str,
    days: int = 60,
    with_volume: bool = True,
    with_ma: bool = True,
) -> dict:
    """生成股票日 K 线截图，返回 base64 PNG。

    用于 vision agent "看图"分析 K 线形态。包含蜡烛图、成交量、MA5/MA10/MA20 均线。
    遵循 A 股颜色惯例（红涨绿跌）。

    返回:
        - ``image_base64``: base64 编码的 PNG 图片
        - ``image_data_url``: 可直接嵌入 vision LLM 的 data URL
        - ``bars``: 实际渲染的 K 线根数
        - ``date_range``: 渲染的日期范围
    """
    try:
        df, source = _fetch_daily_df(stock_code, days=days)
    except Exception as e:
        logger.warning("[VisionTool] capture_kline_chart fetch failed for %s: %s", stock_code, e)
        return {
            "error": f"获取 {stock_code} 历史数据失败: {e}",
            "image_base64": "",
            "bars": 0,
        }

    if df is None or df.empty:
        return {
            "error": f"无 {stock_code} 历史数据",
            "image_base64": "",
            "bars": 0,
        }

    try:
        import pandas as pd
        df_copy = df.copy()
        if "date" in df_copy.columns:
            df_copy["date"] = pd.to_datetime(df_copy["date"])
            date_range = f"{df_copy['date'].min().strftime('%Y-%m-%d')} ~ {df_copy['date'].max().strftime('%Y-%m-%d')}"
        else:
            date_range = "unknown"

        b64 = _df_to_base64_png(
            df,
            stock_code,
            with_volume=with_volume,
            with_ma=with_ma,
            title_suffix=f"({days}D)",
        )

        return {
            "image_base64": b64,
            "image_data_url": f"data:image/png;base64,{b64}",
            "bars": len(df),
            "date_range": date_range,
            "source": source,
            "format": "png",
        }
    except Exception as e:
        logger.error("[VisionTool] chart rendering failed for %s: %s", stock_code, e, exc_info=True)
        return {
            "error": f"图表渲染失败: {e}",
            "image_base64": "",
            "bars": 0,
        }


def _handle_capture_intraday_chart(stock_code: str) -> dict:
    """生成股票分时图截图，返回 base64 PNG。

    基于实时行情 + 最近 5 日日 K 构建分时走势图。
    （注: 当前数据源无分钟级 API，用实时价 + 近 5 日走势近似展示盘中状态。）

    返回:
        - ``image_base64``: base64 PNG
        - ``image_data_url``: data URL
        - ``current_price``: 当前价
    """
    try:
        from data_provider import DataFetcherManager
        manager = DataFetcherManager()

        # 实时行情
        quote = manager.get_realtime_quote(stock_code)
        # 近 5 日数据作为走势背景
        df, source = manager.get_daily_data(stock_code, days=5)

        if df is None or df.empty:
            return {
                "error": f"无 {stock_code} 近期数据用于分时图",
                "image_base64": "",
            }

        import matplotlib.pyplot as plt
        import pandas as pd
        import numpy as np

        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        fig, ax = plt.subplots(figsize=(12, 5))

        # 绘制最近 5 日收盘价折线
        x = np.arange(len(df))
        ax.plot(x, df["close"], marker="o", linewidth=1.8, color="#1f77b4", label="Close")

        # 标注每日收盘价
        for i, row in df.iterrows():
            ax.annotate(
                f"{row['close']:.2f}",
                xy=(i, row["close"]),
                xytext=(0, 8),
                textcoords="offset points",
                fontsize=8,
                ha="center",
                color="#333",
            )

        # 若有实时价，标记在图末尾
        current_price = None
        if quote is not None:
            current_price = quote.price
            ax.axhline(
                y=current_price,
                color="#d62728",
                linestyle="--",
                linewidth=1,
                alpha=0.6,
                label=f"Realtime: {current_price:.2f}",
            )

        # X 轴日期
        tick_labels = df["date"].dt.strftime("%m-%d").tolist()
        ax.set_xticks(x)
        ax.set_xticklabels(tick_labels, rotation=30, ha="right", fontsize=9)

        # 涨跌幅 Y 轴辅助
        if len(df) >= 2:
            base = df["close"].iloc[0]
            ax2 = ax.twinx()
            y_min, y_max = ax.get_ylim()
            if base > 0:
                ax2.set_ylim(
                    (y_min - base) / base * 100,
                    (y_max - base) / base * 100,
                )
            ax2.set_ylabel("Change %", fontsize=9, color="#888")

        ax.set_title(f"{stock_code} Recent Trend (5D)", fontsize=12, fontweight="bold")
        ax.set_ylabel("Price", fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper left", fontsize=9)

        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        buf.close()

        return {
            "image_base64": b64,
            "image_data_url": f"data:image/png;base64,{b64}",
            "current_price": current_price,
            "source": source,
            "format": "png",
        }
    except Exception as e:
        logger.error("[VisionTool] intraday chart failed for %s: %s", stock_code, e, exc_info=True)
        return {
            "error": f"分时图生成失败: {e}",
            "image_base64": "",
        }


# ---------------------------------------------------------------------------
# 工具定义
# ---------------------------------------------------------------------------

capture_kline_chart_tool = ToolDefinition(
    name="capture_kline_chart",
    description=(
        "生成股票日 K 线截图（含成交量、MA5/MA10/MA20 均线），返回 base64 PNG 图片。"
        "用于视觉分析 K 线形态（头肩顶、双底、突破等）。"
        "颜色遵循 A 股惯例（红涨绿跌）。"
        "返回的 image_data_url 可直接用于 vision 模型看图。"
    ),
    parameters=[
        ToolParameter(
            name="stock_code",
            type="string",
            description="股票代码，例如 '600519'（A股）、'AAPL'（美股）",
        ),
        ToolParameter(
            name="days",
            type="integer",
            description="获取最近 N 个交易日的数据（默认 60，最多 120）",
            required=False,
            default=60,
        ),
        ToolParameter(
            name="with_volume",
            type="boolean",
            description="是否包含成交量副图（默认 true）",
            required=False,
            default=True,
        ),
        ToolParameter(
            name="with_ma",
            type="boolean",
            description="是否标注 MA5/MA10/MA20 均线（默认 true）",
            required=False,
            default=True,
        ),
    ],
    handler=_handle_capture_kline_chart,
    category="vision",
)

capture_intraday_chart_tool = ToolDefinition(
    name="capture_intraday_chart",
    description=(
        "生成股票分时走势截图，返回 base64 PNG 图片。"
        "基于实时行情 + 最近 5 日收盘价走势，展示盘中价格状态。"
        "返回的 image_data_url 可直接用于 vision 模型看图。"
    ),
    parameters=[
        ToolParameter(
            name="stock_code",
            type="string",
            description="股票代码，例如 '600519'",
        ),
    ],
    handler=_handle_capture_intraday_chart,
    category="vision",
)

ALL_VISION_TOOLS: List[ToolDefinition] = [
    capture_kline_chart_tool,
    capture_intraday_chart_tool,
]
