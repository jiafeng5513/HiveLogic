# -*- coding: utf-8 -*-
"""
===================================
品种列表发现服务
===================================

职责：
1. 统一各市场品种列表获取接口
2. 内存缓存（TTL 1小时）+ SQLite 持久化（TTL 24小时），避免频繁调外部API
3. 为批量下载提供品种列表支持
4. 服务端重启后仍可秒级返回标的列表（满足「开箱即有数据」需求）

支持市场：
- crypto_binance: 通过 Binance exchangeInfo API 获取 USDT 现货交易对
- crypto_okx: 通过 OKX instruments API 获取现货交易对
- cn: 通过 Tushare/Baostock 获取A股列表
- us: 通过 TickFlow 或 YFinance 获取美股列表
- hk: 通过 TickFlow 或 LongBridge 获取港股列表
"""

import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DEFAULT_DB = os.path.join(DEFAULT_CACHE_DIR, "market_cache.db")

# 内存缓存有效期: 1小时（进程内快速命中）
CACHE_TTL_SECONDS = 3600
# DB 缓存有效期: 24小时（进程重启后仍可命中，避免每次重启都打外部 API）
DB_TTL_SECONDS = 86400


class SymbolListService:
    """统一品种列表发现服务"""

    def __init__(self, db_path: str = DEFAULT_DB):
        self._db_path = db_path
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS symbol_list (
                    market      TEXT NOT NULL,
                    symbol      TEXT NOT NULL,
                    name        TEXT DEFAULT '',
                    updated_at  REAL NOT NULL,
                    PRIMARY KEY (market, symbol)
                );
                CREATE INDEX IF NOT EXISTS idx_symbol_list_market
                    ON symbol_list(market);

                CREATE TABLE IF NOT EXISTS symbol_list_meta (
                    market          TEXT PRIMARY KEY,
                    last_refreshed  REAL NOT NULL,
                    count           INTEGER DEFAULT 0
                );
            """)

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_symbols(self, market: str, force_refresh: bool = False) -> List[Dict[str, str]]:
        """
        获取指定市场的全部可下载品种列表。

        读取顺序: 内存缓存 → DB 缓存 → 外部数据源。
        force_refresh=True 时跳过所有缓存，强制从数据源拉取并回写。

        Args:
            market: 市场标识 - "crypto_binance", "crypto_okx", "cn", "us", "hk"
            force_refresh: 是否强制刷新缓存

        Returns:
            品种列表 [{"symbol": "BTCUSDT", "name": "BTC/USDT"}, ...]
        """
        if not force_refresh:
            cached = self._get_cached(market)
            if cached is not None:
                return cached

            db_symbols = self._load_from_db(market)
            if db_symbols is not None:
                self._set_cached(market, db_symbols)
                logger.debug(f"[SymbolListService] {market} 从 DB 加载 {len(db_symbols)} 个品种")
                return db_symbols

        dispatch = {
            "crypto_binance": self._fetch_binance_symbols,
            "crypto_okx": self._fetch_okx_symbols,
            "cn": self._fetch_cn_symbols,
            "us": self._fetch_us_symbols,
            "hk": self._fetch_hk_symbols,
        }

        fetcher = dispatch.get(market)
        if not fetcher:
            logger.warning(f"[SymbolListService] 未知市场: {market}")
            return []

        try:
            symbols = fetcher()
            self._set_cached(market, symbols)
            self._persist_to_db(market, symbols)
            logger.info(f"[SymbolListService] {market} 获取 {len(symbols)} 个品种 (已持久化)")
            return symbols
        except Exception as e:
            logger.error(f"[SymbolListService] {market} 获取品种列表失败: {e}")
            # 最后兜底: 如果 DB 有旧数据（即使过期），返回旧数据比空列表好
            stale = self._load_from_db(market, ignore_ttl=True)
            if stale:
                logger.warning(f"[SymbolListService] {market} 数据源失败，返回 DB 旧数据 ({len(stale)} 个)")
                return stale
            return []

    def get_symbol_count(self, market: str) -> int:
        """获取品种数量（优先用缓存）"""
        symbols = self.get_symbols(market)
        return len(symbols)

    def invalidate_cache(self, market: Optional[str] = None):
        """清除缓存（内存 + DB meta，下次读取将强制从数据源拉取）"""
        with self._lock:
            if market:
                self._cache.pop(market, None)
            else:
                self._cache.clear()
        with self._get_conn() as conn:
            if market:
                conn.execute("DELETE FROM symbol_list_meta WHERE market = ?", (market,))
            else:
                conn.execute("DELETE FROM symbol_list_meta")

    # ==================== 缓存管理 ====================

    def _get_cached(self, market: str) -> Optional[List[Dict[str, str]]]:
        with self._lock:
            entry = self._cache.get(market)
            if entry and time.time() - entry["time"] < CACHE_TTL_SECONDS:
                return entry["data"]
        return None

    def _set_cached(self, market: str, data: List[Dict[str, str]]):
        with self._lock:
            self._cache[market] = {"data": data, "time": time.time()}

    # ==================== DB 持久化 ====================

    def _load_from_db(self, market: str, ignore_ttl: bool = False) -> Optional[List[Dict[str, str]]]:
        """从 DB 加载品种列表。返回 None 表示未命中（无数据或过期）。"""
        try:
            with self._get_conn() as conn:
                meta = conn.execute(
                    "SELECT last_refreshed, count FROM symbol_list_meta WHERE market = ?",
                    (market,),
                ).fetchone()
                if not meta or meta["count"] == 0:
                    return None
                if not ignore_ttl and time.time() - meta["last_refreshed"] > DB_TTL_SECONDS:
                    return None
                rows = conn.execute(
                    "SELECT symbol, name FROM symbol_list WHERE market = ? ORDER BY symbol",
                    (market,),
                ).fetchall()
                return [{"symbol": r["symbol"], "name": r["name"]} for r in rows]
        except sqlite3.Error as e:
            logger.warning(f"[SymbolListService] DB 读取 {market} 失败: {e}")
            return None

    def _persist_to_db(self, market: str, symbols: List[Dict[str, str]]):
        """将品种列表持久化到 DB（全量替换该 market 的记录）"""
        if not symbols:
            return
        now = time.time()
        with self._write_lock:
            with self._get_conn() as conn:
                conn.execute("DELETE FROM symbol_list WHERE market = ?", (market,))
                conn.executemany(
                    "INSERT INTO symbol_list (market, symbol, name, updated_at) VALUES (?, ?, ?, ?)",
                    [(market, s["symbol"], s.get("name", ""), now) for s in symbols],
                )
                conn.execute(
                    """INSERT OR REPLACE INTO symbol_list_meta (market, last_refreshed, count)
                       VALUES (?, ?, ?)""",
                    (market, now, len(symbols)),
                )

    # ==================== Binance ====================

    def _fetch_binance_symbols(self) -> List[Dict[str, str]]:
        """
        获取 Binance 现货 USDT 交易对。
        API: GET https://api.binance.com/api/v3/exchangeInfo
        """
        url = "https://api.binance.com/api/v3/exchangeInfo"
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"[SymbolListService] Binance exchangeInfo 请求失败: {e}")
            raise

        symbols = []
        for item in data.get("symbols", []):
            # 只取 TRADING 状态的 USDT 现货交易对
            if (item.get("status") == "TRADING"
                    and item.get("quoteAsset") == "USDT"
                    and item.get("isSpotTradingAllowed", False)):
                symbol = item["symbol"]  # e.g. "BTCUSDT"
                base = item.get("baseAsset", "")
                symbols.append({
                    "symbol": symbol,
                    "name": f"{base}/USDT",
                })

        # 按交易量排序（如果有权重信息的话，暂按字母排序）
        symbols.sort(key=lambda x: x["symbol"])
        return symbols

    # ==================== OKX ====================

    def _fetch_okx_symbols(self) -> List[Dict[str, str]]:
        """
        获取 OKX 现货交易对。
        API: GET https://www.okx.com/api/v5/public/instruments?instType=SPOT
        """
        url = "https://www.okx.com/api/v5/public/instruments"
        params = {"instType": "SPOT"}
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"[SymbolListService] OKX instruments 请求失败: {e}")
            raise

        symbols = []
        for item in data.get("data", []):
            inst_id = item.get("instId", "")  # e.g. "BTC-USDT"
            state = item.get("state", "")
            quote_ccy = item.get("quoteCcy", "")

            # 只取活跃的 USDT 交易对
            if state == "live" and quote_ccy == "USDT":
                base_ccy = item.get("baseCcy", "")
                symbols.append({
                    "symbol": inst_id,
                    "name": f"{base_ccy}/USDT",
                })

        symbols.sort(key=lambda x: x["symbol"])
        return symbols

    # ==================== A股 ====================

    def _fetch_cn_symbols(self) -> List[Dict[str, str]]:
        """
        获取A股全部上市股票列表。
        优先使用 Tushare，回退到 Baostock。
        """
        # 尝试 Tushare
        symbols = self._try_tushare_stock_list()
        if symbols:
            return symbols

        # 回退到 Baostock
        symbols = self._try_baostock_stock_list()
        if symbols:
            return symbols

        logger.warning("[SymbolListService] A股品种列表获取失败：无可用数据源")
        return []

    def _try_tushare_stock_list(self) -> List[Dict[str, str]]:
        """尝试通过 TushareFetcher 获取A股列表"""
        try:
            from data_provider.base import DataFetcherManager
            mgr = DataFetcherManager()
            fetchers = mgr._get_fetchers_snapshot()

            for f in fetchers:
                if f.name == "TushareFetcher" and hasattr(f, "get_stock_list"):
                    df = f.get_stock_list()
                    if df is not None and not df.empty:
                        symbols = []
                        for _, row in df.iterrows():
                            symbols.append({
                                "symbol": str(row["code"]),
                                "name": str(row.get("name", "")),
                            })
                        return symbols
        except Exception as e:
            logger.debug(f"[SymbolListService] Tushare stock_list failed: {e}")
        return []

    def _try_baostock_stock_list(self) -> List[Dict[str, str]]:
        """尝试通过 BaostockFetcher 获取A股列表"""
        try:
            from data_provider.base import DataFetcherManager
            mgr = DataFetcherManager()
            fetchers = mgr._get_fetchers_snapshot()

            for f in fetchers:
                if f.name == "BaostockFetcher" and hasattr(f, "get_stock_list"):
                    df = f.get_stock_list()
                    if df is not None and not df.empty:
                        symbols = []
                        for _, row in df.iterrows():
                            symbols.append({
                                "symbol": str(row["code"]),
                                "name": str(row.get("name", "")),
                            })
                        return symbols
        except Exception as e:
            logger.debug(f"[SymbolListService] Baostock stock_list failed: {e}")
        return []

    # ==================== 美股 ====================

    def _fetch_us_symbols(self) -> List[Dict[str, str]]:
        """
        获取美股品种列表。
        优先使用 TickFlow，回退到硬编码主要指数/ETF。
        """
        symbols = self._try_tickflow_symbols("us_stock")
        if symbols:
            return symbols

        # 回退: 常见美股指数 + 主要ETF + 大盘股
        logger.info("[SymbolListService] 美股使用默认品种列表")
        return self._get_default_us_symbols()

    def _get_default_us_symbols(self) -> List[Dict[str, str]]:
        """美股默认品种列表（主要指数+ETF+大盘股）"""
        defaults = [
            ("SPY", "SPDR S&P 500 ETF"),
            ("QQQ", "Invesco QQQ Trust"),
            ("DIA", "SPDR Dow Jones ETF"),
            ("IWM", "iShares Russell 2000"),
            ("AAPL", "Apple Inc"),
            ("MSFT", "Microsoft Corp"),
            ("GOOGL", "Alphabet Inc"),
            ("AMZN", "Amazon.com Inc"),
            ("NVDA", "NVIDIA Corp"),
            ("META", "Meta Platforms"),
            ("TSLA", "Tesla Inc"),
            ("BRK.B", "Berkshire Hathaway B"),
            ("JPM", "JPMorgan Chase"),
            ("V", "Visa Inc"),
            ("UNH", "UnitedHealth Group"),
            ("MA", "Mastercard Inc"),
            ("HD", "Home Depot"),
            ("PG", "Procter & Gamble"),
            ("JNJ", "Johnson & Johnson"),
            ("XOM", "Exxon Mobil"),
        ]
        return [{"symbol": s, "name": n} for s, n in defaults]

    # ==================== 港股 ====================

    def _fetch_hk_symbols(self) -> List[Dict[str, str]]:
        """
        获取港股品种列表。
        优先使用 TickFlow，回退到默认列表。
        """
        symbols = self._try_tickflow_symbols("hk_stock")
        if symbols:
            return symbols

        logger.info("[SymbolListService] 港股使用默认品种列表")
        return self._get_default_hk_symbols()

    def _get_default_hk_symbols(self) -> List[Dict[str, str]]:
        """港股默认品种列表（恒生指数成分股 + 主要ETF）"""
        defaults = [
            ("00700", "腾讯控股"),
            ("09988", "阿里巴巴"),
            ("03690", "美团"),
            ("09999", "网易"),
            ("09618", "京东集团"),
            ("01810", "小米集团"),
            ("00941", "中国移动"),
            ("00388", "香港交易所"),
            ("02318", "中国平安"),
            ("00005", "汇丰控股"),
            ("01299", "友邦保险"),
            ("02020", "安踏体育"),
            ("09888", "百度集团"),
            ("01024", "快手"),
            ("00981", "中芯国际"),
            ("02800", "盈富基金"),
            ("03033", "南方恒生科技ETF"),
            ("02269", "药明生物"),
            ("00883", "中国海洋石油"),
            ("01211", "比亚迪"),
        ]
        return [{"symbol": s, "name": n} for s, n in defaults]

    # ==================== TickFlow 通用 ====================

    def _try_tickflow_symbols(self, market_type: str) -> List[Dict[str, str]]:
        """尝试通过 TickFlowFetcher 获取品种列表"""
        try:
            from data_provider.base import DataFetcherManager
            mgr = DataFetcherManager()
            fetchers = mgr._get_fetchers_snapshot()

            for f in fetchers:
                if f.name == "TickFlowFetcher" and hasattr(f, "get_symbol_list"):
                    items = f.get_symbol_list(market_type)
                    if items:
                        symbols = []
                        for item in items:
                            symbols.append({
                                "symbol": str(item.get("symbol", item.get("code", ""))),
                                "name": str(item.get("name", "")),
                            })
                        return symbols
        except Exception as e:
            logger.debug(f"[SymbolListService] TickFlow {market_type} failed: {e}")
        return []


# ==================== 全局单例 ====================

_service_instance: Optional[SymbolListService] = None
_service_lock = threading.Lock()


def get_symbol_list_service() -> SymbolListService:
    """获取全局 SymbolListService 单例"""
    global _service_instance
    if _service_instance is None:
        with _service_lock:
            if _service_instance is None:
                _service_instance = SymbolListService()
    return _service_instance
