# -*- coding: utf-8 -*-
"""
===================================
市场数据 API 端点 (标的浏览器)
===================================

职责：
1. 提供市场类型列表接口
2. 提供标的列表接口 (支持分类和搜索)
3. 提供统一 K 线数据接口 (兼容 TradingView DataFeed)
4. 提供批量实时行情接口

路由前缀: /api/v1/market
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from api.v1.schemas.market import (
    MarketTypesResponse,
    MarketType,
    SymbolListResponse,
    SymbolInfo,
    SymbolSearchResponse,
    KLineResponse,
    MarketKLineData,
    RealtimeResponse,
    RealtimeQuoteItem,
    MarketTypeEnum,
    DataSourceEnum,
    WatchlistItem,
    WatchlistResponse,
    WatchlistAddRequest,
    WatchlistReorderRequest,
    BrowserDataItem,
    BrowserDataResponse,
    IndexQuoteItem,
    IndicesResponse,
)
from src.services.market_gateway import MarketGateway
from src.services.watchlist import WatchlistService
from src.services.entitlement import enforce_data_request, record_api_usage

logger = logging.getLogger(__name__)

router = APIRouter()

# 延迟初始化网关实例
_gateway: Optional[MarketGateway] = None


def _get_gateway() -> MarketGateway:
    """获取 MarketGateway 单例"""
    global _gateway
    if _gateway is None:
        _gateway = MarketGateway()
    return _gateway


# ==================== 市场类型 ====================

@router.get(
    "/types",
    response_model=MarketTypesResponse,
    summary="获取支持的市场类型列表",
    description="返回所有启用的市场类型，如虚拟货币、A股、ETF等",
)
def get_market_types():
    """获取支持的市场类型列表"""
    gateway = _get_gateway()
    raw_types = gateway.get_market_types()
    types = [
        MarketType(
            type=MarketTypeEnum(mt["type"]),
            name=mt["name"],
            description=mt.get("description", ""),
            data_source=DataSourceEnum(mt["data_source"]),
            icon=mt.get("icon", ""),
            enabled=mt.get("enabled", True),
        )
        for mt in raw_types
    ]
    return MarketTypesResponse(types=types)


# ==================== 标的列表 ====================

@router.get(
    "/symbols",
    response_model=SymbolListResponse,
    summary="获取标的列表",
    description="获取指定市场类型的标的列表。首次请求会从数据源拉取并缓存，后续请求读取缓存",
)
def get_symbols(
    request: Request,
    type: str = Query(..., description="市场类型: crypto, cn_stock, cn_etf, cn_futures"),
    refresh: bool = Query(False, description="是否强制刷新缓存"),
):
    """获取指定市场类型的标的列表"""
    enforce_data_request(request, market_type=type)
    gateway = _get_gateway()
    raw_symbols = gateway.get_symbols(type, force_refresh=refresh)

    symbols = []
    for s in raw_symbols:
        extra = s.get("extra", {})
        if isinstance(extra, str):
            import json
            try:
                extra = json.loads(extra)
            except (json.JSONDecodeError, TypeError):
                extra = {}

        # 推断 market_type 枚举
        try:
            mt = MarketTypeEnum(type)
        except ValueError:
            mt = MarketTypeEnum.CN_STOCK

        # 推断 data_source 枚举
        try:
            ds = DataSourceEnum(s.get("data_source", "akshare"))
        except ValueError:
            ds = DataSourceEnum.AKSHARE

        symbols.append(
            SymbolInfo(
                symbol=s.get("symbol", ""),
                name=s.get("name", ""),
                market_type=mt,
                exchange=s.get("exchange", ""),
                data_source=ds,
                base_currency=s.get("currency", ""),
                status=s.get("status", "trading"),
                current_price=extra.get("price") if isinstance(extra, dict) else None,
                change_percent=extra.get("change_pct") if isinstance(extra, dict) else None,
            )
        )

    return SymbolListResponse(
        market_type=type,
        total=len(symbols),
        symbols=symbols,
    )


# ==================== 标的搜索 ====================

@router.get(
    "/symbols/search",
    response_model=SymbolSearchResponse,
    summary="搜索标的",
    description="根据代码或名称搜索标的 (模糊匹配)，搜索范围为已缓存的标的",
)
def search_symbols(
    q: str = Query(..., min_length=1, max_length=50, description="搜索关键词 (代码或名称)"),
    type: str = Query("", description="限定市场类型 (可选)"),
):
    """搜索标的"""
    gateway = _get_gateway()
    raw_results = gateway.search_symbols(q, type)

    symbols = []
    for s in raw_results:
        extra = s.get("extra_json", "{}")
        if isinstance(extra, str):
            import json
            try:
                extra = json.loads(extra)
            except (json.JSONDecodeError, TypeError):
                extra = {}

        # 从缓存结果中的 market_type 字段读取
        raw_mt = s.get("market_type", "cn_stock")
        try:
            mt = MarketTypeEnum(raw_mt)
        except ValueError:
            mt = MarketTypeEnum.CN_STOCK

        try:
            ds = DataSourceEnum(s.get("data_source", "akshare"))
        except ValueError:
            ds = DataSourceEnum.AKSHARE

        symbols.append(
            SymbolInfo(
                symbol=s.get("symbol", ""),
                name=s.get("name", ""),
                market_type=mt,
                exchange=s.get("exchange", ""),
                data_source=ds,
                base_currency=s.get("currency", ""),
                status=s.get("status", "trading"),
                current_price=extra.get("price") if isinstance(extra, dict) else None,
                change_percent=extra.get("change_pct") if isinstance(extra, dict) else None,
            )
        )

    return SymbolSearchResponse(
        query=q,
        total=len(symbols),
        symbols=symbols,
    )


# ==================== K 线数据 ====================

@router.get(
    "/kline",
    response_model=KLineResponse,
    summary="获取 K 线数据",
    description="获取指定标的的 K 线数据，兼容 TradingView UDF 格式。时间戳为 Unix 秒",
)
def get_kline(
    request: Request,
    symbol: str = Query(..., description="标的代码 (如 600519, BTC/USDT)"),
    type: str = Query("", description="市场类型 (可选, 自动推断)"),
    period: str = Query("1d", description="K 线周期: 1/5/15/30/60/1h/4h/1d/1w/1M"),
    start: int = Query(0, description="起始 Unix 时间戳 (秒)"),
    end: int = Query(0, description="结束 Unix 时间戳 (秒)"),
    limit: int = Query(300, ge=1, le=1500, description="最大数据条数"),
):
    """获取 K 线数据"""
    gateway = _get_gateway()

    # 推断市场类型
    market_type = type if type else MarketGateway._guess_market_type(symbol)

    # 订阅等级准入：市场 + 周期 + 历史深度（鉴权关闭时自动跳过）
    import time as _time
    history_days = int((_time.time() - start) / 86400) if start > 0 else None
    enforce_data_request(request, market_type=market_type, period=period, history_days=history_days)

    bars, no_data = gateway.get_kline(
        symbol=symbol,
        market_type=market_type,
        period=period,
        start_time=start,
        end_time=end,
        limit=limit,
    )

    kline_data = [
        MarketKLineData(
            time=b["time"],
            open=b["open"],
            high=b["high"],
            low=b["low"],
            close=b["close"],
            volume=b.get("volume"),
            turnover=b.get("turnover"),
        )
        for b in bars
    ]

    record_api_usage(request, endpoint="/market/kline", method="GET", market=market_type)

    return KLineResponse(
        symbol=symbol,
        period=period,
        data=kline_data,
        no_data=no_data,
    )


# ==================== 实时行情 ====================

@router.get(
    "/realtime",
    response_model=RealtimeResponse,
    summary="获取批量实时行情",
    description="获取一组标的的实时行情数据",
)
def get_realtime(
    request: Request,
    symbols: str = Query(..., description="标的代码列表 (逗号分隔, 如 600519,000001)"),
    type: str = Query("", description="市场类型 (可选, 自动推断)"),
):
    """获取批量实时行情"""
    enforce_data_request(request, market_type=type)
    gateway = _get_gateway()

    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        raise HTTPException(status_code=400, detail="symbols 参数不能为空")

    if len(symbol_list) > 50:
        raise HTTPException(status_code=400, detail="一次最多查询 50 个标的")

    raw_quotes = gateway.get_realtime_quotes(symbol_list, type)

    quotes = [
        RealtimeQuoteItem(
            symbol=q.get("symbol", ""),
            name=q.get("name", ""),
            price=q.get("price"),
            change=q.get("change"),
            change_percent=q.get("change_percent"),
            volume=q.get("volume"),
            turnover=q.get("turnover"),
            high=q.get("high"),
            low=q.get("low"),
            open=q.get("open"),
            prev_close=q.get("prev_close"),
            update_time=str(q["update_time"]) if q.get("update_time") is not None else None,
        )
        for q in raw_quotes
    ]

    return RealtimeResponse(quotes=quotes)


# ==================== 自选列表 ====================

_watchlist: Optional[WatchlistService] = None


def _get_watchlist() -> WatchlistService:
    global _watchlist
    if _watchlist is None:
        _watchlist = WatchlistService()
    return _watchlist


@router.get(
    "/watchlist",
    response_model=WatchlistResponse,
    summary="获取自选列表",
)
def get_watchlist():
    svc = _get_watchlist()
    items = svc.get_all()
    return WatchlistResponse(
        total=len(items),
        symbols=[WatchlistItem(**it) for it in items],
    )


@router.post(
    "/watchlist",
    summary="添加到自选",
)
def add_to_watchlist(req: WatchlistAddRequest):
    svc = _get_watchlist()
    added = svc.add(
        symbol=req.symbol,
        name=req.name,
        market_type=req.market_type,
        exchange=req.exchange,
        data_source=req.data_source,
    )
    return {"success": True, "added": added, "symbol": req.symbol}


@router.delete(
    "/watchlist/{symbol}",
    summary="从自选移除",
)
def remove_from_watchlist(symbol: str):
    svc = _get_watchlist()
    removed = svc.remove(symbol)
    return {"success": True, "removed": removed, "symbol": symbol}


@router.get(
    "/watchlist/check/{symbol}",
    summary="检查是否在自选中",
)
def check_watchlist(symbol: str):
    svc = _get_watchlist()
    return {"symbol": symbol, "in_watchlist": svc.contains(symbol)}


@router.put(
    "/watchlist/reorder",
    summary="自选列表排序",
)
def reorder_watchlist(req: WatchlistReorderRequest):
    svc = _get_watchlist()
    svc.reorder(req.symbols)
    return {"success": True}


# ==================== 数据源链健康检查 ====================

@router.get(
    "/datasource/health",
    summary="数据源链健康状态",
    description="返回各数据源的健康状态、失败次数等信息",
)
def get_datasource_health():
    """获取数据源链健康报告"""
    gateway = _get_gateway()
    return gateway.get_chain_health()


@router.post(
    "/datasource/reset",
    summary="重置数据源链状态",
    description="重置数据源链的健康状态，清除失败计数和冷却",
)
def reset_datasource_chain(category: Optional[str] = Query(None, description="指定类别 (如 kline:cn), 空则全部重置")):
    """重置数据源链健康状态"""
    gateway = _get_gateway()
    gateway.reset_chain(category)
    return {"success": True, "category": category or "all"}


# ==================== 财务数据 ====================


@router.get(
    "/financials",
    summary="获取财务数据",
    description="获取标的财务数据 (利润表/资产负债表/现金流/核心指标)",
)
def get_financials(
    symbol: str = Query(..., description="标的代码 (如 600519, AAPL, HK00700)"),
    type: str = Query("metrics", description="报表类型: income | balance | cash_flow | metrics | shares"),
    limit: int = Query(8, description="返回最近几期", ge=1, le=20),
):
    """获取财务数据"""
    import os
    from data_provider.tickflow_fetcher import TickFlowFetcher
    from data_provider.base import DataFetchError

    api_key = os.environ.get("TICKFLOW_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="财务数据需要配置 TICKFLOW_API_KEY (Expert 套餐)")

    fetcher = TickFlowFetcher(api_key=api_key)
    try:
        result = fetcher.get_financials(symbol, report_type=type, limit=limit)
        return result
    except DataFetchError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error("[Market] 财务数据获取失败 (%s/%s): %s", symbol, type, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"财务数据获取失败: {e}")


# ==================== 标的浏览器批量数据 ====================


@router.get(
    "/browser/data",
    response_model=BrowserDataResponse,
    summary="标的浏览器批量数据",
    description="获取标的浏览器所需的批量行情+估值数据，支持排序和筛选",
)
def get_browser_data(
    request: Request,
    type: str = Query("crypto", description="市场类型: crypto, cn_stock, hk_stock, us_stock"),
    sort: str = Query("", description="排序: field:asc/desc (如 total_mv:desc)"),
    filter: str = Query("", description="筛选: field>value,field<value"),
    offset: int = Query(0, ge=0, description="偏移量"),
    limit: int = Query(200, ge=1, le=500, description="返回条数"),
):
    """标的浏览器批量数据接口"""
    from datetime import datetime

    enforce_data_request(request, market_type=type)
    gateway = _get_gateway()

    # 获取标的列表
    raw_symbols = gateway.get_symbols(type, force_refresh=False)

    # 获取实时行情（批量）
    symbol_codes = [s.get("symbol", "") for s in raw_symbols[:limit + offset]]
    quotes_map = {}
    if symbol_codes:
        try:
            batch_size = 50
            for i in range(0, min(len(symbol_codes), offset + limit), batch_size):
                batch = symbol_codes[i:i + batch_size]
                raw_quotes = gateway.get_realtime_quotes(batch, type)
                for q in raw_quotes:
                    quotes_map[q.get("symbol", "")] = q
        except Exception as e:
            logger.warning("[Browser] 批量行情获取部分失败: %s", e)

    # 组装数据
    items = []
    for s in raw_symbols:
        symbol = s.get("symbol", "")
        name = s.get("name", "")
        q = quotes_map.get(symbol, {})
        extra = s.get("extra", {})
        if isinstance(extra, str):
            import json as json_mod
            try:
                extra = json_mod.loads(extra)
            except (ValueError, TypeError):
                extra = {}

        price = q.get("price") or (extra.get("price") if isinstance(extra, dict) else None)
        change_pct = q.get("change_percent") or (extra.get("change_pct") if isinstance(extra, dict) else None)

        item = BrowserDataItem(
            symbol=symbol,
            name=name,
            price=price,
            change_pct=change_pct,
            volume=q.get("volume"),
            turnover=q.get("turnover"),
            volume_ratio=q.get("volume_ratio") or (extra.get("volume_ratio") if isinstance(extra, dict) else None),
            turnover_rate=q.get("turnover_rate") or (extra.get("turnover_rate") if isinstance(extra, dict) else None),
            amplitude=q.get("amplitude") or (extra.get("amplitude") if isinstance(extra, dict) else None),
            total_mv=extra.get("total_mv") if isinstance(extra, dict) else None,
            circ_mv=extra.get("circ_mv") if isinstance(extra, dict) else None,
            pe_ratio=extra.get("pe_ratio") if isinstance(extra, dict) else None,
            pb_ratio=extra.get("pb_ratio") if isinstance(extra, dict) else None,
            high=q.get("high"),
            low=q.get("low"),
            open=q.get("open"),
            prev_close=q.get("prev_close"),
            high_24h=q.get("high") if type == "crypto" else None,
            low_24h=q.get("low") if type == "crypto" else None,
            exchange=s.get("exchange"),
            data_source=s.get("data_source"),
        )
        items.append(item)

    total = len(items)

    # 服务端筛选
    if filter:
        for cond in filter.split(","):
            cond = cond.strip()
            if not cond:
                continue
            try:
                if ">=" in cond:
                    field, val = cond.split(">=", 1)
                    field = field.strip()
                    val = float(val.strip())
                    items = [it for it in items if getattr(it, field, None) is not None and getattr(it, field) >= val]
                elif "<=" in cond:
                    field, val = cond.split("<=", 1)
                    field = field.strip()
                    val = float(val.strip())
                    items = [it for it in items if getattr(it, field, None) is not None and getattr(it, field) <= val]
                elif ">" in cond:
                    field, val = cond.split(">", 1)
                    field = field.strip()
                    val = float(val.strip())
                    items = [it for it in items if getattr(it, field, None) is not None and getattr(it, field) > val]
                elif "<" in cond:
                    field, val = cond.split("<", 1)
                    field = field.strip()
                    val = float(val.strip())
                    items = [it for it in items if getattr(it, field, None) is not None and getattr(it, field) < val]
            except (ValueError, AttributeError):
                continue

    # 服务端排序
    if sort:
        parts = sort.split(":")
        sort_field = parts[0].strip()
        sort_dir = parts[1].strip() if len(parts) > 1 else "desc"
        reverse = sort_dir == "desc"
        items.sort(
            key=lambda it: (getattr(it, sort_field, None) is None, getattr(it, sort_field, None) or 0),
            reverse=reverse,
        )

    # 分页
    paged = items[offset:offset + limit]

    return BrowserDataResponse(
        total=total,
        data=paged,
        updated_at=datetime.now().isoformat(),
    )


# ==================== 宏观指数 (首页) ====================


@router.get(
    "/indices",
    response_model=IndicesResponse,
    summary="获取宏观指数行情",
    description="获取首页显示的宏观指数实时行情数据",
)
def get_indices(
    symbols: str = Query("", description="指数代码列表 (逗号分隔)"),
):
    """获取宏观指数行情"""
    gateway = _get_gateway()

    # 默认指数列表
    default_indices = [
        ("000001.SH", "上证综指", "cn_stock"),
        ("399001.SZ", "深证成指", "cn_stock"),
        ("399006.SZ", "创业板指", "cn_stock"),
        ("HSI", "恒生指数", "hk_stock"),
        ("^IXIC", "纳斯达克", "us_stock"),
        ("^DJI", "道琼斯", "us_stock"),
        ("BTCUSDT", "BTC/USDT", "crypto"),
        ("ETHUSDT", "ETH/USDT", "crypto"),
    ]

    # 需要通过 yfinance 获取的指数 (TickFlow 不支持这些符号)
    YF_INDEX_MAP = {
        "HSI": "^HSI",
        "^IXIC": "^IXIC",
        "^DJI": "^DJI",
    }

    if symbols:
        requested = [s.strip() for s in symbols.split(",") if s.strip()]
    else:
        requested = [idx[0] for idx in default_indices]

    quotes = []
    for symbol, name, market_type in default_indices:
        if symbol not in requested:
            continue
        try:
            # 对港股/美股指数使用 yfinance 直接获取
            if symbol in YF_INDEX_MAP:
                q = _fetch_index_via_yfinance(symbol, name, YF_INDEX_MAP[symbol])
                if q:
                    quotes.append(q)
                else:
                    quotes.append(IndexQuoteItem(symbol=symbol, name=name))
            else:
                raw_quotes = gateway.get_realtime_quotes([symbol], market_type)
                if raw_quotes:
                    q = raw_quotes[0]
                    quotes.append(IndexQuoteItem(
                        symbol=symbol,
                        name=name,
                        price=q.get("price"),
                        change=q.get("change"),
                        change_percent=q.get("change_percent"),
                        sparkline=None,
                    ))
                else:
                    quotes.append(IndexQuoteItem(symbol=symbol, name=name))
        except Exception as e:
            logger.warning("[Indices] 获取指数 %s 失败: %s", symbol, e)
            quotes.append(IndexQuoteItem(symbol=symbol, name=name))

    return IndicesResponse(quotes=quotes)


def _fetch_index_via_yfinance(symbol: str, name: str, yf_code: str) -> Optional[IndexQuoteItem]:
    """通过 yfinance 获取单个指数行情"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(yf_code)
        hist = ticker.history(period='2d')
        if hist.empty:
            return None
        today_row = hist.iloc[-1]
        prev_row = hist.iloc[-2] if len(hist) > 1 else today_row
        price = float(today_row['Close'])
        prev_close = float(prev_row['Close'])
        change = price - prev_close
        change_pct = (change / prev_close) * 100 if prev_close else 0
        return IndexQuoteItem(
            symbol=symbol,
            name=name,
            price=price,
            change=change,
            change_percent=change_pct,
            sparkline=None,
        )
    except Exception as e:
        logger.warning("[Indices] yfinance 获取 %s 失败: %s", symbol, e)
        return None
