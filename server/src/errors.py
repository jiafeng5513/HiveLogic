# -*- coding: utf-8 -*-
"""
===================================
统一数据网关异常族 (GatewayError Family)
===================================

为行情数据网关（data_provider）与未来新闻管道（src/search/providers）
提供共享的异常治理基类，作为网关收敛计划的公共契约层。

设计要点：
1. GatewayError: 统一基类，携带可选 source（数据源名）/ datatype（数据类型）上下文
2. classify_exception: 将裸异常（TimeoutError / ConnectionError / HTTP 状态码等）
   映射到统一异常族，全程不抛出新异常
3. 零依赖：仅通过鸭子类型（属性探测）与类名/消息文本匹配识别异常，
   永不导入 requests / httpx 等第三方库
"""

import json
from typing import Optional


class GatewayError(Exception):
    """
    统一数据网关异常基类

    携带可选的上下文字段：
    - source: 数据源名（如 "akshare" / "tushare" / "tickflow"）
    - datatype: 数据类型（如 "kline" / "quote" / "stock_list"）

    __str__ 仅当存在上下文时追加 "[source=..., datatype=...]" 后缀，
    无上下文时与原生 Exception 行为完全一致。
    """

    def __init__(self, *args, source: Optional[str] = None, datatype: Optional[str] = None):
        self.source = source
        self.datatype = datatype
        super().__init__(*args)

    def __str__(self) -> str:
        base = super().__str__()
        parts = []
        if self.source is not None:
            parts.append(f"source={self.source}")
        if self.datatype is not None:
            parts.append(f"datatype={self.datatype}")
        if not parts:
            return base
        suffix = f"[{', '.join(parts)}]"
        return f"{base} {suffix}" if base else suffix


class GatewayTimeoutError(GatewayError):
    """网关超时异常：连接/读取超时"""
    pass


class SourceUnavailableError(GatewayError):
    """数据源不可用异常：连接失败 / 5xx / 熔断断开"""
    pass


class BadResponseError(GatewayError):
    """响应格式错误：数据缺失 / 契约违反 / 解析失败"""
    pass


class RateLimitedError(GatewayError):
    """速率限制异常：HTTP 429 / 配额耗尽"""
    pass


class AuthFailedError(GatewayError):
    """
    认证失败异常：HTTP 401 / 403

    语义信号：调用方应永久跳过该数据源（不再重试、不计入临时故障）。
    """
    pass


def _extract_http_status(exc: BaseException) -> Optional[int]:
    """
    鸭子类型提取 HTTP 状态码。

    依次探测 exc.response.status_code（requests/httpx 风格）与
    exc.status_code（部分 SDK 风格），均不存在时返回 None。
    """
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None) if response is not None else None
    if status is None:
        status = getattr(exc, "status_code", None)
    return status if isinstance(status, int) else None


def classify_exception(exc: BaseException, *, source: Optional[str] = None,
                       datatype: Optional[str] = None) -> GatewayError:
    """
    将常见裸异常映射到统一异常族（纯函数，自身不抛出异常）。

    映射规则（按优先级）：
    - 已是 GatewayError 成员 -> 原样透传
    - TimeoutError 或类名含 "Timeout" -> GatewayTimeoutError
    - ConnectionError 或类名含 "Connect" -> SourceUnavailableError
    - HTTP 401/403（response.status_code 或类名/消息文本）-> AuthFailedError
    - HTTP 429（同上）-> RateLimitedError
    - json.JSONDecodeError / KeyError / ValueError -> BadResponseError
    - 其余 -> BadResponseError
    """
    # 1. 已是统一异常族成员：原样透传
    if isinstance(exc, GatewayError):
        return exc

    message = str(exc).strip()
    name = type(exc).__name__

    # 2. 超时
    if isinstance(exc, TimeoutError) or "Timeout" in name:
        return GatewayTimeoutError(message or "网关请求超时", source=source, datatype=datatype)

    # 3. 连接失败 / 源不可用
    if isinstance(exc, ConnectionError) or "Connect" in name:
        return SourceUnavailableError(message or "数据源连接失败", source=source, datatype=datatype)

    # 4. HTTP 状态码识别（最明确的权限/限流信号）
    status = _extract_http_status(exc)
    if status in (401, 403):
        return AuthFailedError(message or f"HTTP {status} 认证失败", source=source, datatype=datatype)
    if status == 429:
        return RateLimitedError(message or "HTTP 429 速率限制", source=source, datatype=datatype)

    # 5. 类名/消息文本兜底识别权限与限流
    lowered = message.lower()
    if ("401" in message or "403" in message
            or "unauthorized" in lowered or "forbidden" in lowered
            or "Unauthorized" in name or "Forbidden" in name or "Auth" in name):
        return AuthFailedError(message or "数据源认证失败", source=source, datatype=datatype)
    if ("429" in message or "too many requests" in lowered
            or "RateLimit" in name or "TooManyRequests" in name):
        return RateLimitedError(message or "数据源速率限制", source=source, datatype=datatype)

    # 6. 数据/契约类错误
    if isinstance(exc, (json.JSONDecodeError, KeyError, ValueError)):
        return BadResponseError(message or "响应数据格式错误", source=source, datatype=datatype)

    # 7. 兜底：未知异常按响应错误处理
    return BadResponseError(message or f"未知网关错误 ({name})", source=source, datatype=datatype)
