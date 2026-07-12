# -*- coding: utf-8 -*-
"""
===================================
缓存管理 API 端点
===================================

职责：
1. 查询缓存状态
2. 获取时间轴数据
3. 触发缓存下载任务
4. 删除指定范围缓存

路由前缀: /api/v1/cache
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.services.kline_cache_manager import get_kline_cache_manager

logger = logging.getLogger(__name__)
router = APIRouter()


# ==================== Request/Response Models ====================

class CacheStatusResponse(BaseModel):
    """缓存状态响应"""
    total_records: int = 0
    total_size_bytes: int = 0
    total_size_mb: float = 0.0
    markets: dict = Field(default_factory=dict)


class TimelineResponse(BaseModel):
    """时间轴数据响应"""
    segments: list = Field(default_factory=list)


class MarketTimelineSummaryResponse(BaseModel):
    """按市场分组的时间轴摘要"""
    markets: dict = Field(default_factory=dict)


class DownloadRequest(BaseModel):
    """下载任务请求"""
    market: str
    symbol: str
    interval: str = "1d"
    start_time: int  # Unix毫秒时间戳
    end_time: int


class DeleteRangeRequest(BaseModel):
    """删除缓存范围请求"""
    market: str
    symbol: str
    interval: str = "1d"
    start_time: int
    end_time: int


class TaskResponse(BaseModel):
    """任务响应"""
    task_id: str
    status: str = "pending"
    message: str = ""


class TaskStatusResponse(BaseModel):
    """任务状态响应"""
    task_id: str
    market: str = ""
    symbol: str = ""
    interval: str = ""
    start_time: int = 0
    end_time: int = 0
    status: str = ""
    progress: float = 0.0
    error: str = ""


# ==================== Endpoints ====================

@router.get("/status", response_model=CacheStatusResponse)
async def get_cache_status():
    """获取缓存整体状态"""
    try:
        manager = get_kline_cache_manager()
        status = manager.get_cache_status()
        size_bytes = status.get("total_size_bytes", 0)
        return CacheStatusResponse(
            total_records=status.get("total_records", 0),
            total_size_bytes=size_bytes,
            total_size_mb=round(size_bytes / (1024 * 1024), 2),
            markets=status.get("markets", {}),
        )
    except Exception as e:
        logger.error(f"[CacheAPI] 获取缓存状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/timeline", response_model=TimelineResponse)
async def get_timeline(
    market: Optional[str] = Query(None, description="市场标识，如 cn, us, crypto_binance"),
    interval: str = Query("1d", description="K线间隔"),
):
    """获取时间轴数据（用于前端缓存时间轴UI）"""
    try:
        manager = get_kline_cache_manager()
        segments = manager.get_timeline_data(market=market, interval=interval)
        return TimelineResponse(segments=segments)
    except Exception as e:
        logger.error(f"[CacheAPI] 获取时间轴数据失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/timeline/summary", response_model=MarketTimelineSummaryResponse)
async def get_timeline_summary(
    interval: str = Query("1d", description="K线间隔"),
):
    """获取按市场分组的时间轴摘要（多轨道渲染用）"""
    try:
        manager = get_kline_cache_manager()
        summary = manager.get_market_timeline_summary(interval=interval)
        return MarketTimelineSummaryResponse(markets=summary)
    except Exception as e:
        logger.error(f"[CacheAPI] 获取时间轴摘要失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/download", response_model=TaskResponse)
async def trigger_download(req: DownloadRequest):
    """
    触发缓存下载任务。

    创建一个后台下载任务，从数据源获取指定范围的K线数据并缓存到本地。
    """
    try:
        manager = get_kline_cache_manager()
        task_id = manager.create_download_task(
            market=req.market,
            symbol=req.symbol,
            interval=req.interval,
            start_time=req.start_time,
            end_time=req.end_time,
        )

        # TODO: 启动实际的后台下载协程
        # 这里先创建任务记录，实际下载逻辑由后台任务引擎执行

        return TaskResponse(
            task_id=task_id,
            status="pending",
            message=f"下载任务已创建: {req.market}/{req.symbol}/{req.interval}",
        )
    except Exception as e:
        logger.error(f"[CacheAPI] 创建下载任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/range")
async def delete_cache_range(req: DeleteRangeRequest):
    """删除指定范围的缓存数据"""
    try:
        manager = get_kline_cache_manager()
        deleted = manager.delete_range(
            market=req.market,
            symbol=req.symbol,
            interval=req.interval,
            start_time=req.start_time,
            end_time=req.end_time,
        )
        return {
            "deleted_records": deleted,
            "message": f"已删除 {deleted} 条缓存记录",
        }
    except Exception as e:
        logger.error(f"[CacheAPI] 删除缓存失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/progress")
async def get_download_progress(
    task_id: Optional[str] = Query(None, description="任务ID，不传则返回所有任务"),
):
    """查询下载任务进度"""
    try:
        manager = get_kline_cache_manager()

        if task_id:
            status = manager.get_task_status(task_id)
            if status is None:
                raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
            return status
        else:
            return {"tasks": manager.get_all_tasks()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CacheAPI] 查询下载进度失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/download/{task_id}/cancel")
async def cancel_download(task_id: str):
    """取消下载任务"""
    try:
        manager = get_kline_cache_manager()
        success = manager.cancel_task(task_id)
        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"无法取消任务 {task_id}（可能已完成或不存在）",
            )
        return {"message": f"任务 {task_id} 已取消"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CacheAPI] 取消任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/market/{market}")
async def clear_market_cache(market: str):
    """清空指定市场的所有缓存"""
    try:
        manager = get_kline_cache_manager()
        deleted = manager.clear_market(market)
        return {
            "deleted_records": deleted,
            "message": f"已清空市场 {market} 的 {deleted} 条缓存",
        }
    except Exception as e:
        logger.error(f"[CacheAPI] 清空市场缓存失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 品种列表 & 批量下载 ====================

class MarketDownloadRequest(BaseModel):
    """市场级批量下载请求"""
    market: str            # "crypto_binance", "crypto_okx", "cn", "us", "hk"
    interval: str = "1d"
    start_time: int        # Unix毫秒时间戳
    end_time: int


@router.get("/symbols/{market}")
async def get_market_symbols(
    market: str,
    refresh: bool = Query(False, description="是否强制刷新缓存（跳过内存+DB缓存，从数据源重新拉取）"),
):
    """
    获取指定市场的全部可下载品种列表。

    读取顺序：内存缓存 → DB 缓存 → 外部数据源。
    refresh=true 时强制从数据源拉取并回写缓存。
    """
    try:
        from src.services.symbol_list_service import get_symbol_list_service
        service = get_symbol_list_service()
        symbols = service.get_symbols(market, force_refresh=refresh)
        return {
            "market": market,
            "count": len(symbols),
            "symbols": symbols,
        }
    except Exception as e:
        logger.error(f"[CacheAPI] 获取品种列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/download/market")
async def trigger_market_download(req: MarketDownloadRequest):
    """
    触发市场级批量下载。

    获取该市场全部品种列表，为每个品种创建下载子任务。
    采用分批释放策略（每次50个），避免任务堆积。
    """
    try:
        from src.services.symbol_list_service import get_symbol_list_service
        service = get_symbol_list_service()
        symbols_data = service.get_symbols(req.market)

        if not symbols_data:
            raise HTTPException(
                status_code=400,
                detail=f"市场 {req.market} 无可用品种列表",
            )

        symbol_codes = [s["symbol"] for s in symbols_data]

        manager = get_kline_cache_manager()
        batch_id = manager.create_batch_download(
            market=req.market,
            interval=req.interval,
            start_time=req.start_time,
            end_time=req.end_time,
            symbols=symbol_codes,
        )

        return {
            "batch_id": batch_id,
            "market": req.market,
            "total_symbols": len(symbol_codes),
            "message": f"批量下载已创建: {req.market} {len(symbol_codes)} 个品种",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CacheAPI] 创建批量下载失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/batch/{batch_id}/progress")
async def get_batch_progress(batch_id: str):
    """查询批次下载进度"""
    try:
        manager = get_kline_cache_manager()
        progress = manager.get_batch_progress(batch_id)
        if progress is None:
            raise HTTPException(status_code=404, detail=f"批次 {batch_id} 不存在")
        return progress
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CacheAPI] 查询批次进度失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/download/batch/{batch_id}/cancel")
async def cancel_batch_download(batch_id: str):
    """取消整个批次的下载"""
    try:
        manager = get_kline_cache_manager()
        success = manager.cancel_batch(batch_id)
        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"无法取消批次 {batch_id}（不存在）",
            )
        return {"message": f"批次 {batch_id} 已取消"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CacheAPI] 取消批次失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/batches")
async def get_all_batches():
    """获取所有批次状态"""
    try:
        manager = get_kline_cache_manager()
        batches = manager.get_all_batches()
        return {"batches": batches}
    except Exception as e:
        logger.error(f"[CacheAPI] 获取批次列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics")
async def get_cache_metrics():
    """获取 K 线缓存命中率指标"""
    try:
        from src.services.market_gateway import MarketGateway
        gateway = MarketGateway()
        return gateway.get_cache_metrics()
    except Exception as e:
        logger.error(f"[CacheAPI] 获取缓存指标失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/disk-usage")
async def get_disk_usage():
    """获取磁盘使用统计"""
    try:
        from src.services.cache_maintenance import get_cache_maintenance
        maintenance = get_cache_maintenance()
        return maintenance.get_disk_usage()
    except Exception as e:
        logger.error(f"[CacheAPI] 获取磁盘使用统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/maintenance")
async def run_cache_maintenance():
    """触发缓存维护（清理过期数据 + VACUUM）"""
    try:
        from src.services.cache_maintenance import get_cache_maintenance
        maintenance = get_cache_maintenance()
        return maintenance.run_full_cleanup()
    except Exception as e:
        logger.error(f"[CacheAPI] 缓存维护失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/snapshot/{market}")
async def get_market_snapshot(market: str):
    """获取指定市场的最新行情快照（L0）"""
    try:
        from src.services.market_collector import get_market_collector
        collector = get_market_collector()
        snapshots = collector.get_market_snapshots(market)
        return {"market": market, "count": len(snapshots), "snapshots": snapshots}
    except Exception as e:
        logger.error(f"[CacheAPI] 获取快照失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/collector/status")
async def get_collector_status():
    """获取市场采集器状态"""
    try:
        from src.services.market_collector import get_market_collector
        collector = get_market_collector()
        return collector.get_status()
    except Exception as e:
        logger.error(f"[CacheAPI] 获取采集器状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scheduler/status")
async def get_scheduler_status(request: Request):
    """获取调度任务状态"""
    try:
        scheduler = getattr(request.app.state, "scheduler", None)
        if scheduler is None:
            return {"tasks": [], "note": "调度器未启动"}
        return {"tasks": scheduler.get_task_status()}
    except Exception as e:
        logger.error(f"[CacheAPI] 获取调度状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/collector/collect")
async def trigger_collection():
    """手动触发全市场快照采集"""
    try:
        from src.services.market_collector import get_market_collector
        collector = get_market_collector()
        results = collector.collect_all()
        return {"results": results}
    except Exception as e:
        logger.error(f"[CacheAPI] 手动采集失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
