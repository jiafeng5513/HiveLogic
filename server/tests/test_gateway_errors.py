# -*- coding: utf-8 -*-
"""
统一数据网关异常族 (src/errors.py) + data_provider 桥接 单元测试

测试场景:
1. 异常族继承关系: 5 个子类均继承 GatewayError，上下文字段与 __str__ 行为
2. 向后兼容桥接: DataFetchError / RateLimitError / DataSourceUnavailableError 双重继承
3. classify_exception: 裸异常 -> 统一异常族映射（零依赖鸭子类型识别）
4. 导入完整性: data_provider.base / tickflow_fetcher 可正常导入（无循环导入）
"""

import os
import sys
import json

import pytest

# 确保 backend 目录在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ==================== 异常族继承关系测试 ====================


class TestGatewayErrorFamily:
    """测试统一异常族继承关系与上下文字段"""

    def test_all_subclasses_of_gateway_error(self):
        """测试 5 个子类均为 GatewayError 子类"""
        from src.errors import (
            GatewayError, GatewayTimeoutError, SourceUnavailableError,
            BadResponseError, RateLimitedError, AuthFailedError,
        )
        assert issubclass(GatewayTimeoutError, GatewayError)
        assert issubclass(SourceUnavailableError, GatewayError)
        assert issubclass(BadResponseError, GatewayError)
        assert issubclass(RateLimitedError, GatewayError)
        assert issubclass(AuthFailedError, GatewayError)

    def test_context_defaults_to_none(self):
        """测试上下文字段默认为 None 且存为实例属性"""
        from src.errors import GatewayError
        err = GatewayError("失败")
        assert err.source is None
        assert err.datatype is None

    def test_str_appends_context_when_present(self):
        """测试 __str__ 有上下文时追加 source/datatype"""
        from src.errors import GatewayError
        err = GatewayError("获取失败", source="akshare", datatype="kline")
        text = str(err)
        assert "获取失败" in text
        assert "akshare" in text
        assert "kline" in text

    def test_str_unchanged_without_context(self):
        """测试 __str__ 无上下文时与原生 Exception 一致"""
        from src.errors import GatewayError
        err = GatewayError("纯消息")
        assert str(err) == "纯消息"


# ==================== data_provider 桥接兼容性测试 ====================


class TestDataProviderBridge:
    """测试 data_provider 异常桥接到统一异常族的向后兼容性"""

    def test_bridge_inheritance(self):
        """测试桥接后的双重继承关系"""
        from data_provider.base import (
            DataFetchError, RateLimitError, DataSourceUnavailableError,
        )
        from src.errors import GatewayError, RateLimitedError, SourceUnavailableError
        assert issubclass(DataFetchError, GatewayError)
        assert issubclass(RateLimitError, DataFetchError)
        assert issubclass(RateLimitError, RateLimitedError)
        assert issubclass(DataSourceUnavailableError, DataFetchError)
        assert issubclass(DataSourceUnavailableError, SourceUnavailableError)

    def test_rate_limit_caught_as_data_fetch_error(self):
        """测试 RateLimitError 可被 except DataFetchError 捕获（原语义）"""
        from data_provider.base import DataFetchError, RateLimitError
        with pytest.raises(DataFetchError):
            raise RateLimitError("限流")

    def test_rate_limit_caught_as_rate_limited_error(self):
        """测试 RateLimitError 可被 except RateLimitedError 捕获（新语义）"""
        from data_provider.base import RateLimitError
        from src.errors import RateLimitedError
        with pytest.raises(RateLimitedError):
            raise RateLimitError("限流")

    def test_unavailable_caught_as_data_fetch_error(self):
        """测试 DataSourceUnavailableError 可被 except DataFetchError 捕获（原语义）"""
        from data_provider.base import DataFetchError, DataSourceUnavailableError
        with pytest.raises(DataFetchError):
            raise DataSourceUnavailableError("源不可用")

    def test_unavailable_caught_as_source_unavailable(self):
        """测试 DataSourceUnavailableError 可被 except SourceUnavailableError 捕获（新语义）"""
        from data_provider.base import DataSourceUnavailableError
        from src.errors import SourceUnavailableError
        with pytest.raises(SourceUnavailableError):
            raise DataSourceUnavailableError("源不可用")

    def test_message_preserved(self):
        """测试桥接后异常消息与原生行为一致"""
        from data_provider.base import RateLimitError
        err = RateLimitError("Tushare 配额超限")
        assert str(err) == "Tushare 配额超限"


# ==================== classify_exception 映射测试 ====================


class TestClassifyException:
    """测试 classify_exception 裸异常映射"""

    def test_timeout_error(self):
        """测试 TimeoutError -> GatewayTimeoutError"""
        from src.errors import classify_exception, GatewayTimeoutError
        result = classify_exception(TimeoutError("连接超时"))
        assert isinstance(result, GatewayTimeoutError)

    def test_timeout_by_class_name(self):
        """测试类名含 Timeout 的第三方异常 -> GatewayTimeoutError（不导入 requests/httpx）"""
        from src.errors import classify_exception, GatewayTimeoutError

        class HttpReadTimeout(Exception):
            pass

        result = classify_exception(HttpReadTimeout("read timed out"))
        assert isinstance(result, GatewayTimeoutError)

    def test_connection_error(self):
        """测试 ConnectionError -> SourceUnavailableError"""
        from src.errors import classify_exception, SourceUnavailableError
        result = classify_exception(ConnectionError("连接被拒绝"))
        assert isinstance(result, SourceUnavailableError)

    def test_http_401_and_403(self):
        """测试带 response.status_code 401/403 的异常 -> AuthFailedError"""
        from src.errors import classify_exception, AuthFailedError

        class FakeResponse:
            def __init__(self, status_code):
                self.status_code = status_code

        class FakeHTTPError(Exception):
            def __init__(self, status_code):
                super().__init__(f"HTTP {status_code}")
                self.response = FakeResponse(status_code)

        assert isinstance(classify_exception(FakeHTTPError(401)), AuthFailedError)
        assert isinstance(classify_exception(FakeHTTPError(403)), AuthFailedError)

    def test_http_429(self):
        """测试带 response.status_code 429 的异常 -> RateLimitedError"""
        from src.errors import classify_exception, RateLimitedError

        class FakeResponse:
            status_code = 429

        class FakeHTTPError(Exception):
            def __init__(self):
                super().__init__("HTTP 429")
                self.response = FakeResponse()

        assert isinstance(classify_exception(FakeHTTPError()), RateLimitedError)

    def test_json_decode_error(self):
        """测试 json.JSONDecodeError -> BadResponseError"""
        from src.errors import classify_exception, BadResponseError
        try:
            json.loads("{invalid json")
            pytest.fail("应抛出 JSONDecodeError")
        except json.JSONDecodeError as e:
            result = classify_exception(e)
        assert isinstance(result, BadResponseError)

    def test_key_error_and_value_error(self):
        """测试 KeyError / ValueError -> BadResponseError"""
        from src.errors import classify_exception, BadResponseError
        assert isinstance(classify_exception(KeyError("missing")), BadResponseError)
        assert isinstance(classify_exception(ValueError("bad value")), BadResponseError)

    def test_gateway_error_passthrough(self):
        """测试已是 GatewayError 的异常原样透传"""
        from src.errors import classify_exception, RateLimitedError
        err = RateLimitedError("已限流", source="tushare")
        assert classify_exception(err) is err

    def test_generic_exception(self):
        """测试未知异常兜底 -> BadResponseError"""
        from src.errors import classify_exception, BadResponseError
        result = classify_exception(Exception("未知错误"))
        assert isinstance(result, BadResponseError)

    def test_context_attached_when_provided(self):
        """测试提供 source/datatype 时附加到映射结果"""
        from src.errors import classify_exception, GatewayTimeoutError
        result = classify_exception(
            TimeoutError("超时"), source="sina", datatype="quote"
        )
        assert isinstance(result, GatewayTimeoutError)
        assert result.source == "sina"
        assert result.datatype == "quote"


# ==================== 导入完整性测试 ====================


class TestImports:
    """测试既有导入路径仍然可用（传递验证无循环导入）"""

    def test_base_exceptions_import(self):
        """测试 data_provider.base 三个异常类可正常导入"""
        from data_provider.base import (
            DataFetchError, RateLimitError, DataSourceUnavailableError,
        )
        assert DataFetchError is not None
        assert RateLimitError is not None
        assert DataSourceUnavailableError is not None

    def test_tickflow_fetcher_import(self):
        """测试 TickFlowFetcher 可正常导入（传递验证无循环导入）"""
        from data_provider.tickflow_fetcher import TickFlowFetcher
        assert TickFlowFetcher is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
