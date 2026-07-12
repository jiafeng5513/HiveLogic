# -*- coding: utf-8 -*-
"""
hivelogic_data — 沙箱内只读数据访问助手

此模块随沙箱镜像内置，供 AI 生成的代码 import 使用。
提供对服务端 SQLite 缓存数据库的**只读**访问，无需写 SQL。

用法（沙箱内 AI 生成的代码）::

    from hivelogic_data import load_kline, load_stock_info
    df = load_kline("600519", days=365)
    print(df.tail())

安全约束:
    - 所有连接以 ``immutable=1`` 打开，禁止任何写操作
    - 路径固定为 ``/data/`` 下的缓存文件，无法访问其他文件
    - 无网络库可用，数据不会出境
"""

from __future__ import annotations

import os
import sqlite3
from typing import Optional

import pandas as pd

# ---------------------------------------------------------------------------
# 路径解析 — 沙箱内缓存数据由 docker-compose 以只读卷挂载到 /data
# ---------------------------------------------------------------------------
_DATA_DIR = os.environ.get("SANDBOX_DATA_DIR", "/data")
_MARKET_CACHE_DB = os.path.join(_DATA_DIR, "market_cache.db")
_STOCK_ANALYSIS_DB = os.path.join(_DATA_DIR, "stock_analysis.db")


def _connect_readonly(db_path: str) -> sqlite3.Connection:
    """以只读模式打开 SQLite 连接。

    使用 ``immutable=1`` 让 SQLite 假设文件不会被修改，避免任何写锁尝试。
    如果文件不存在则抛 FileNotFoundError，让调用方知道数据未就绪。
    """
    if not os.path.exists(db_path):
        raise FileNotFoundError(
            f"缓存数据库不存在: {db_path}。请确保沙箱已挂载数据卷。"
        )
    # file:path?immutable=1 — 完全只读，不创建 -wal/-journal 文件
    uri = f"file:{db_path}?immutable=1"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# K 线数据
# ---------------------------------------------------------------------------

def load_kline(
    symbol: str,
    interval: str = "daily",
    market: Optional[str] = None,
    days: Optional[int] = None,
) -> pd.DataFrame:
    """加载 K 线数据为 DataFrame。

    依次查询 ``kline_data`` 表（多市场，含 market 列）和 ``kline_cache`` 表
    （A 股专用，无 market 列），取首个有数据的来源。

    Args:
        symbol: 股票代码，如 ``"600519"``、``"000001"``、``"AAPL"``、``"0G/USDT"``
        interval: K 线周期，``"daily"`` / ``"1d"`` / ``"1"`` / ``"5"`` / ``"15"`` / ``"60"``
                  （daily=日线，数字=分钟线）
        market: 市场标识（``"cn"`` / ``"us"`` / ``"hk"`` / ``"crypto_binance"``）。
                为 None 时自动推断（6 位数字开头 → cn，否则尝试 us/hk）。
        days: 最近 N 个交易日，None 表示全部

    Returns:
        DataFrame，列: ``open, high, low, close, volume, amount``
        索引为 ``datetime``。
    """
    # 自动推断市场
    if market is None:
        if symbol.isdigit() and len(symbol) == 6:
            market = "cn"
        elif symbol.isdigit():
            market = "cn"
        else:
            # crypto pairs like "0G/USDT" or US tickers
            if "/" in symbol:
                market = "crypto_binance"
            else:
                market = "us"

    # 归一化 interval: "daily" → "1d" (DB stores "1d")
    interval_map = {"daily": "1d", "1d": "1d", "1": "1", "5": "5", "15": "15", "60": "60"}
    db_interval = interval_map.get(str(interval), str(interval))

    # --- 来源 1: kline_data 表（多市场，含 market 列，timestamp 毫秒）---
    query1 = (
        "SELECT timestamp, open, high, low, close, volume, amount "
        "FROM kline_data WHERE market = ? AND symbol = ? AND interval = ? "
        "ORDER BY timestamp ASC"
    )
    params1: list = [market, symbol, db_interval]

    try:
        with _connect_readonly(_MARKET_CACHE_DB) as conn:
            df = pd.read_sql_query(query1, conn, params=params1)
    except Exception:
        df = pd.DataFrame()

    if not df.empty:
        # 转换时间戳 (kline_data: 毫秒)
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.set_index("datetime").drop(columns=["timestamp"])
        if days is not None and days > 0:
            df = df.tail(days)
        return df

    # --- 来源 2: kline_cache 表（A 股专用，无 market 列，time 秒，turnover 替代 amount）---
    query2 = (
        "SELECT time, open, high, low, close, volume, turnover "
        "FROM kline_cache WHERE symbol = ? AND period = ? "
        "ORDER BY time ASC"
    )
    params2: list = [symbol, db_interval]

    try:
        with _connect_readonly(_MARKET_CACHE_DB) as conn:
            df2 = pd.read_sql_query(query2, conn, params=params2)
    except Exception:
        df2 = pd.DataFrame()

    if not df2.empty:
        # 转换时间戳 (kline_cache: 秒) + 列名归一化
        df2["datetime"] = pd.to_datetime(df2["time"], unit="s")
        df2 = df2.rename(columns={"turnover": "amount"})
        df2 = df2.set_index("datetime").drop(columns=["time"])
        if days is not None and days > 0:
            df2 = df2.tail(days)
        return df2

    # 两个表都无数据，返回空 DataFrame
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "amount"])


# ---------------------------------------------------------------------------
# 股票分析历史（来自 stock_analysis.db）
# ---------------------------------------------------------------------------

def load_analysis_history(
    symbol: Optional[str] = None,
    limit: int = 50,
) -> pd.DataFrame:
    """加载历史分析记录（来自 stock_analysis.db）。

    Args:
        symbol: 股票代码过滤，None 表示全部
        limit: 最多返回条数

    Returns:
        DataFrame，包含历次分析的字段（信号、评分、日期等）。
        如果 stock_analysis.db 不存在则返回空 DataFrame。
    """
    if not os.path.exists(_STOCK_ANALYSIS_DB):
        return pd.DataFrame()

    query = "SELECT * FROM analysis_records"
    params: list = []
    if symbol:
        query += " WHERE stock_code = ?"
        params.append(symbol)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    try:
        with _connect_readonly(_STOCK_ANALYSIS_DB) as conn:
            return pd.read_sql_query(query, conn, params=params)
    except sqlite3.OperationalError:
        # 表不存在或 schema 不匹配
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# 便捷工具
# ---------------------------------------------------------------------------

def list_available_symbols(market: Optional[str] = None) -> list[str]:
    """列出缓存中有数据的股票代码（去重）。

    查询 ``kline_data`` 表（按 market 过滤）和 ``kline_cache`` 表（A 股专用，
    无 market 列，仅当 market 为 None 或 "cn" 时纳入）。

    Args:
        market: 市场标识。None 表示全部市场。
    """
    symbols: set[str] = set()
    with _connect_readonly(_MARKET_CACHE_DB) as conn:
        # kline_data 表（含 market 列）
        if market:
            rows = conn.execute(
                "SELECT DISTINCT symbol FROM kline_data WHERE market = ? ORDER BY symbol",
                (market,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT symbol FROM kline_data ORDER BY symbol"
            ).fetchall()
        symbols.update(r["symbol"] for r in rows)

        # kline_cache 表（A 股专用，无 market 列）
        # 仅在未指定 market 或 market="cn" 时纳入，避免混淆
        if market is None or market == "cn":
            try:
                rows2 = conn.execute(
                    "SELECT DISTINCT symbol FROM kline_cache ORDER BY symbol"
                ).fetchall()
                symbols.update(r["symbol"] for r in rows2)
            except sqlite3.OperationalError:
                pass  # kline_cache 表可能不存在

    return sorted(symbols)


def db_info() -> dict:
    """返回缓存数据库基本信息（表名 + 行数），供 AI 探索数据时使用。"""
    info: dict = {"market_cache": {}, "stock_analysis": {}}
    if os.path.exists(_MARKET_CACHE_DB):
        with _connect_readonly(_MARKET_CACHE_DB) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            for t in tables:
                count = conn.execute(f"SELECT COUNT(*) FROM \"{t['name']}\"").fetchone()[0]
                info["market_cache"][t["name"]] = count
    if os.path.exists(_STOCK_ANALYSIS_DB):
        try:
            with _connect_readonly(_STOCK_ANALYSIS_DB) as conn:
                tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                for t in tables:
                    count = conn.execute(f"SELECT COUNT(*) FROM \"{t['name']}\"").fetchone()[0]
                    info["stock_analysis"][t["name"]] = count
        except sqlite3.OperationalError:
            pass
    info["data_dir"] = _DATA_DIR
    return info


__all__ = ["load_kline", "load_analysis_history", "list_available_symbols", "db_info"]
