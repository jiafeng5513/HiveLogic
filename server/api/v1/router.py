# -*- coding: utf-8 -*-
"""
===================================
API v1 路由聚合
===================================

职责：
1. 聚合 v1 版本的所有 endpoint 路由
2. 统一添加 /api/v1 前缀
"""

from fastapi import APIRouter

from api.v1.endpoints import analysis, auth, history, stocks, backtest, system_config, agent, usage, portfolio, news, market, cache, news_crawler, admin, client_auth, user_profile, proactive_messages

# 创建 v1 版本主路由
router = APIRouter(prefix="/api/v1")

router.include_router(
    auth.router,
    prefix="/auth",
    tags=["Auth"]
)

router.include_router(
    agent.router,
    prefix="/agent",
    tags=["Agent"]
)

router.include_router(
    analysis.router,
    prefix="/analysis",
    tags=["Analysis"]
)

router.include_router(
    history.router,
    prefix="/history",
    tags=["History"]
)

router.include_router(
    stocks.router,
    prefix="/stocks",
    tags=["Stocks"]
)

router.include_router(
    backtest.router,
    prefix="/backtest",
    tags=["Backtest"]
)

router.include_router(
    system_config.router,
    prefix="/system",
    tags=["SystemConfig"]
)

router.include_router(
    usage.router,
    prefix="/usage",
    tags=["Usage"]
)

router.include_router(
    portfolio.router,
    prefix="/portfolio",
    tags=["Portfolio"]
)

router.include_router(
    news.router,
    prefix="/news",
    tags=["News"]
)

router.include_router(
    market.router,
    prefix="/market",
    tags=["Market"]
)

router.include_router(
    cache.router,
    prefix="/cache",
    tags=["Cache"]
)

router.include_router(
    news_crawler.router,
    prefix="/news-crawler",
    tags=["NewsCrawler"]
)

router.include_router(
    admin.router,
    prefix="/admin",
    tags=["Admin"]
)

router.include_router(
    client_auth.router,
    prefix="/client-auth",
    tags=["ClientAuth"]
)

router.include_router(
    user_profile.router,
    prefix="/user-profile",
    tags=["UserProfile"]
)

router.include_router(
    proactive_messages.router,
    prefix="/proactive-messages",
    tags=["ProactiveMessages"]
)
