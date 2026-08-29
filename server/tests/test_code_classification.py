# -*- coding: utf-8 -*-
"""
股票代码分类 canonical 实现 + fetcher 收敛等价性测试

测试场景:
1. base.py canonical 帮助函数行为锚定:
   normalize_stock_code / _is_us_market / _is_hk_market / _is_etf_code /
   _market_tag / is_bse_code / is_st_stock / is_kc_cy_stock / canonical_stock_code
2. 已收敛 fetcher 私有副本与 canonical 实现的等价性:
   - akshare_fetcher._is_us_code (别名) == us_index_mapping.is_us_stock_code
   - akshare_fetcher.is_hk_stock_code (别名) == base._is_hk_market
   - akshare_fetcher 不再定义私有 _is_hk_code
   - longbridge_fetcher 不再定义私有 _is_us_code，改用 base._is_us_market
   - yfinance_fetcher.YfinanceFetcher 不再定义私有 _is_us_stock 方法
3. data_provider 包级导出 (is_us_index_code / is_us_stock_code /
   is_hk_stock_code / is_crypto_code) 保持可用且语义不变
"""

import os
import sys

import pytest

# 确保 backend 目录在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data_provider import base  # noqa: E402
from data_provider.us_index_mapping import is_us_stock_code, is_us_index_code  # noqa: E402


# 共享语料（约 40 个代表性代码）:
# A股 / ETF / 港股 / 美股 / 指数 / 加密 / 北交所 / 边界情况
SHARED_CORPUS = [
    # A股
    "600519", "000001", "300750", "688981", "920748",
    # ETF
    "510300", "159915", "588000",
    # 港股
    "HK00700", "00700.HK", "1810.HK", "09988",
    # 美股
    "AAPL", "aapl", "TSLA", "BRK.B",
    # 指数
    ".INX", ".DJI", ".IXIC", "SPX",
    # 加密
    "BTC-USD", "BTCUSDT",
    # 北交所
    "430047", "830799",
    # 边界情况: 空串 / 空白填充
    "", "  600519  ", " 510300 ",
    # 前缀/后缀/大小写变体
    "600519.SH", "SH600519", "sh600519", "000001.SZ", "BJ920748",
    "920748.BJ", "hk00700", "00700", "700.HK", "HK01810", "0700.HK",
    "510300.SH", "brk.b", " aaPl ",
    # 指数别名与纯数字边界
    "DJI", "VIX", "12345", "123456", "60051",
]

# None 安全的语料（仅用于签名允许 None 的 canonical 实现）
NONE_SAFE_CORPUS = SHARED_CORPUS + [None]


# ==================== canonical 帮助函数行为锚定 ====================


class TestNormalizeStockCode:
    """测试 normalize_stock_code 的标准化行为"""

    def test_plain_codes_unchanged(self):
        """纯数字代码保持不变"""
        from data_provider.base import normalize_stock_code
        assert normalize_stock_code("600519") == "600519"
        assert normalize_stock_code("000001") == "000001"
        assert normalize_stock_code("920748") == "920748"
        assert normalize_stock_code("09988") == "09988"

    def test_strip_exchange_prefix(self):
        """剥离 SH/SZ/BJ 前缀（大小写不敏感）"""
        from data_provider.base import normalize_stock_code
        assert normalize_stock_code("SH600519") == "600519"
        assert normalize_stock_code("sh600519") == "600519"
        assert normalize_stock_code("SZ000001") == "000001"
        assert normalize_stock_code("BJ920748") == "920748"

    def test_strip_exchange_suffix(self):
        """剥离 .SH/.SZ/.SS/.BJ 后缀"""
        from data_provider.base import normalize_stock_code
        assert normalize_stock_code("600519.SH") == "600519"
        assert normalize_stock_code("000001.SZ") == "000001"
        assert normalize_stock_code("600519.SS") == "600519"
        assert normalize_stock_code("920748.BJ") == "920748"

    def test_hk_canonical_prefix_form(self):
        """港股归一为 HK + 5 位数字的前缀形式"""
        from data_provider.base import normalize_stock_code
        assert normalize_stock_code("HK00700") == "HK00700"
        assert normalize_stock_code("hk00700") == "HK00700"
        assert normalize_stock_code("HK700") == "HK00700"
        assert normalize_stock_code("00700.HK") == "HK00700"
        assert normalize_stock_code("1810.HK") == "HK01810"
        assert normalize_stock_code("700.HK") == "HK00700"

    def test_hk_overlength_digits_not_normalized(self):
        """HK 后超过 5 位数字时不做港股归一"""
        from data_provider.base import normalize_stock_code
        assert normalize_stock_code("HK123456") == "HK123456"
        assert normalize_stock_code("123456.HK") == "123456.HK"

    def test_us_ticker_case_preserved(self):
        """美股代码保持原始大小写（不做 upper 归一）"""
        from data_provider.base import normalize_stock_code
        assert normalize_stock_code("AAPL") == "AAPL"
        assert normalize_stock_code("aapl") == "aapl"
        assert normalize_stock_code("BRK.B") == "BRK.B"

    def test_whitespace_and_empty(self):
        """空白填充被剥离，空串原样返回"""
        from data_provider.base import normalize_stock_code
        assert normalize_stock_code("  600519  ") == "600519"
        assert normalize_stock_code("") == ""

    def test_unrecognized_passthrough(self):
        """未识别的形式原样透传"""
        from data_provider.base import normalize_stock_code
        assert normalize_stock_code(".INX") == ".INX"
        assert normalize_stock_code("BTC-USD") == "BTC-USD"
        assert normalize_stock_code("SPX") == "SPX"


class TestIsUsMarket:
    """测试 _is_us_market（美股股票 + 美股指数）"""

    def test_us_stocks(self):
        """美股股票代码（大小写不敏感、支持 BRK.B 与空白填充）"""
        assert base._is_us_market("AAPL") is True
        assert base._is_us_market("aapl") is True
        assert base._is_us_market(" aaPl ") is True
        assert base._is_us_market("TSLA") is True
        assert base._is_us_market("BRK.B") is True
        assert base._is_us_market("brk.b") is True

    def test_us_indices_and_aliases(self):
        """美股指数及其别名均判定为美股"""
        assert base._is_us_market("SPX") is True
        assert base._is_us_market("DJI") is True
        assert base._is_us_market("IXIC") is True
        assert base._is_us_market("VIX") is True
        assert base._is_us_market("NASDAQ") is True
        assert base._is_us_market("^GSPC") is True

    def test_non_us_codes(self):
        """A股/港股/ETF/加密/点号指数均不是美股"""
        for code in ["600519", "000001", "920748", "510300", "HK00700",
                     "00700.HK", "09988", "BTC-USD", "BTCUSDT",
                     ".INX", ".DJI", ".IXIC", "AAPL.US", ""]:
            assert base._is_us_market(code) is False, code

    def test_none_safe(self):
        """None 输入返回 False"""
        assert base._is_us_market(None) is False


class TestIsHkMarket:
    """测试 _is_hk_market 港股判定"""

    def test_hk_prefix_and_suffix_forms(self):
        """HK 前缀与 .HK 后缀形式（1-5 位数字）"""
        for code in ["HK00700", "hk00700", "HK700", "HK01810",
                     "00700.HK", "1810.HK", "700.HK", "0700.HK",
                     "HK0", "0.HK"]:
            assert base._is_hk_market(code) is True, code

    def test_five_digit_plain_codes(self):
        """纯 5 位数字视为港股"""
        assert base._is_hk_market("00700") is True
        assert base._is_hk_market("09988") is True
        assert base._is_hk_market("12345") is True
        assert base._is_hk_market("00000") is True

    def test_non_hk_codes(self):
        """6 位数字、非数字 .HK、超长数字等均不是港股"""
        for code in ["600519", "510300", "123456", "AAPL.HK",
                     "123456.HK", ".HK", "HK123456", "AAPL", ""]:
            assert base._is_hk_market(code) is False, code

    def test_none_safe(self):
        """None 输入返回 False"""
        assert base._is_hk_market(None) is False


class TestIsEtfCode:
    """测试 _is_etf_code（A 股 ETF 保守规则）"""

    def test_etf_prefixes(self):
        """51/52/56/58/15/16/18 前缀的 6 位数字为 ETF"""
        for code in ["510300", "159915", "588000", "510050",
                     "159919", "513500", "560050", "520500", "161725", "180101"]:
            assert base._is_etf_code(code) is True, code

    def test_prefixed_and_suffixed_etf(self):
        """带交易所前缀/后缀及空白填充的 ETF 同样识别"""
        assert base._is_etf_code("510300.SH") is True
        assert base._is_etf_code("SH510300") is True
        assert base._is_etf_code("sh510300") is True
        assert base._is_etf_code("510300.SS") is True
        assert base._is_etf_code(" 510300 ") is True

    def test_non_etf_codes(self):
        """普通股票/北交所/港股/美股/非法形式均不是 ETF"""
        for code in ["600519", "000001", "300750", "688981", "920748",
                     "430047", "830799", "HK00700", "00700", "AAPL",
                     "51ABCD", "510300.", "510300.XX", ""]:
            assert base._is_etf_code(code) is False, code


class TestMarketTag:
    """测试 _market_tag 市场标签"""

    def test_us_tag(self):
        """美股与美股指数标记为 us"""
        assert base._market_tag("AAPL") == "us"
        assert base._market_tag("SPX") == "us"

    def test_hk_tag(self):
        """港股标记为 hk"""
        assert base._market_tag("HK00700") == "hk"
        assert base._market_tag("00700.HK") == "hk"
        assert base._market_tag("09988") == "hk"
        assert base._market_tag("00700") == "hk"

    def test_cn_tag_and_none_safe(self):
        """其余（含空串/None/加密/点号指数）标记为 cn"""
        assert base._market_tag("600519") == "cn"
        assert base._market_tag("510300") == "cn"
        assert base._market_tag("BTC-USD") == "cn"
        assert base._market_tag(".IXIC") == "cn"
        assert base._market_tag("") == "cn"
        assert base._market_tag(None) == "cn"


class TestIsBseCode:
    """测试 is_bse_code 北交所判定"""

    def test_bse_codes(self):
        """92/43/83/87/88/81/82 前缀的 6 位数字为北交所"""
        assert base.is_bse_code("920748") is True
        assert base.is_bse_code("430047") is True
        assert base.is_bse_code("830799") is True
        assert base.is_bse_code("889000") is True
        assert base.is_bse_code("810000") is True
        assert base.is_bse_code("920748.BJ") is True
        assert base.is_bse_code(" 430047 ") is True

    def test_non_bse_codes(self):
        """900 开头（沪市B股）与其他代码不是北交所"""
        assert base.is_bse_code("900901") is False
        assert base.is_bse_code("600519") is False
        assert base.is_bse_code("000001") is False
        assert base.is_bse_code("510300") is False
        assert base.is_bse_code("HK00700") is False

    def test_none_and_empty_safe(self):
        """None/空串返回 False"""
        assert base.is_bse_code(None) is False
        assert base.is_bse_code("") is False


class TestIsStStock:
    """测试 is_st_stock（按名称含 ST 判定）"""

    def test_st_names(self):
        """名称中包含 ST（大小写不敏感）判定为 ST 股"""
        assert base.is_st_stock("ST丹化") is True
        assert base.is_st_stock("*ST 某某") is True
        assert base.is_st_stock("st 测试") is True
        assert base.is_st_stock("A-ST") is True

    def test_non_st_names(self):
        """普通名称不是 ST 股"""
        assert base.is_st_stock("贵州茅台") is False
        assert base.is_st_stock("AAPL") is False

    def test_none_and_empty_safe(self):
        """None/空串返回 False"""
        assert base.is_st_stock(None) is False
        assert base.is_st_stock("") is False


class TestIsKcCyStock:
    """测试 is_kc_cy_stock（科创板/创业板判定）"""

    def test_star_and_chinext(self):
        """688 开头（科创板）与 30 开头（创业板）"""
        assert base.is_kc_cy_stock("688981") is True
        assert base.is_kc_cy_stock("688001") is True
        assert base.is_kc_cy_stock("300750") is True
        assert base.is_kc_cy_stock("301999") is True
        assert base.is_kc_cy_stock("300750.SZ") is True

    def test_non_kc_cy(self):
        """主板/北交所不是科创板/创业板"""
        assert base.is_kc_cy_stock("600519") is False
        assert base.is_kc_cy_stock("000001") is False
        assert base.is_kc_cy_stock("002594") is False
        assert base.is_kc_cy_stock("920748") is False

    def test_none_and_empty_safe(self):
        """None/空串返回 False"""
        assert base.is_kc_cy_stock(None) is False
        assert base.is_kc_cy_stock("") is False


class TestCanonicalStockCode:
    """测试 canonical_stock_code（大小写归一）"""

    def test_uppercase_normalization(self):
        """转大写并剥离空白"""
        from data_provider.base import canonical_stock_code
        assert canonical_stock_code("aapl") == "AAPL"
        assert canonical_stock_code("AAPL") == "AAPL"
        assert canonical_stock_code(" hk00700 ") == "HK00700"
        assert canonical_stock_code("brk.b") == "BRK.B"
        assert canonical_stock_code("600519") == "600519"

    def test_none_and_empty_safe(self):
        """None/空串归一为空串"""
        from data_provider.base import canonical_stock_code
        assert canonical_stock_code(None) == ""
        assert canonical_stock_code("") == ""


# ==================== 已收敛私有副本的等价性测试 ====================


class TestAkshareUsAlias:
    """测试 akshare_fetcher._is_us_code 别名等价于 is_us_stock_code"""

    def test_alias_identity(self):
        """别名与 canonical 实现是同一函数对象"""
        import data_provider.akshare_fetcher as akshare_fetcher
        assert akshare_fetcher._is_us_code is is_us_stock_code

    def test_corpus_equivalence(self):
        """共享语料上别名与 canonical 实现输出一致"""
        import data_provider.akshare_fetcher as akshare_fetcher
        for code in NONE_SAFE_CORPUS:
            assert akshare_fetcher._is_us_code(code) is is_us_stock_code(code), code

    def test_base_deferred_import_path(self):
        """base.py 的延迟导入路径 (from .akshare_fetcher import _is_us_code) 保持可用"""
        from data_provider.akshare_fetcher import _is_us_code as deferred
        assert deferred is is_us_stock_code


class TestAkshareHkConsolidation:
    """测试 akshare_fetcher 港股判定已收敛到 base._is_hk_market"""

    def test_private_def_removed(self):
        """不再定义私有 _is_hk_code"""
        import data_provider.akshare_fetcher as akshare_fetcher
        assert not hasattr(akshare_fetcher, "_is_hk_code")

    def test_alias_identity(self):
        """is_hk_stock_code 与 base._is_hk_market 是同一函数对象"""
        import data_provider.akshare_fetcher as akshare_fetcher
        assert akshare_fetcher.is_hk_stock_code is base._is_hk_market
        assert akshare_fetcher._is_hk_market is base._is_hk_market

    def test_corpus_equivalence(self):
        """共享语料上 is_hk_stock_code 与 base._is_hk_market 输出一致"""
        import data_provider.akshare_fetcher as akshare_fetcher
        for code in NONE_SAFE_CORPUS:
            assert akshare_fetcher.is_hk_stock_code(code) is base._is_hk_market(code), code

    def test_package_export_path(self):
        """包级导出 from data_provider import is_hk_stock_code 保持可用"""
        from data_provider import is_hk_stock_code as pkg_export
        assert pkg_export is base._is_hk_market


class TestLongbridgeUsConsolidation:
    """测试 longbridge_fetcher 美股判定已收敛到 base._is_us_market"""

    def test_private_def_removed(self):
        """不再定义私有 _is_us_code"""
        import data_provider.longbridge_fetcher as longbridge_fetcher
        assert not hasattr(longbridge_fetcher, "_is_us_code")

    def test_canonical_import_identity(self):
        """模块内引用的 _is_us_market 即 base 的 canonical 实现"""
        import data_provider.longbridge_fetcher as longbridge_fetcher
        assert longbridge_fetcher._is_us_market is base._is_us_market

    def test_corpus_equivalence(self):
        """共享语料上调用路径输出与 base._is_us_market 一致"""
        import data_provider.longbridge_fetcher as longbridge_fetcher
        for code in NONE_SAFE_CORPUS:
            assert longbridge_fetcher._is_us_market(code) is base._is_us_market(code), code


class TestYfinanceUsConsolidation:
    """测试 YfinanceFetcher 美股判定已收敛到 is_us_stock_code"""

    def test_private_method_removed(self):
        """不再定义私有 _is_us_stock 方法"""
        from data_provider.yfinance_fetcher import YfinanceFetcher
        assert not hasattr(YfinanceFetcher, "_is_us_stock")

    def test_canonical_call_path(self):
        """yfinance_fetcher 模块内可直接使用 is_us_stock_code，语料行为锚定"""
        import data_provider.yfinance_fetcher as yfinance_fetcher
        for code in NONE_SAFE_CORPUS:
            assert yfinance_fetcher.is_us_stock_code(code) is is_us_stock_code(code), code


class TestPackageExports:
    """测试 data_provider 包级导出语义不变"""

    def test_exports_importable(self):
        """四个导出函数均可从包级导入"""
        from data_provider import (
            is_us_index_code,
            is_us_stock_code as pkg_us_stock,
            is_hk_stock_code as pkg_hk_stock,
            is_crypto_code,
        )
        assert callable(is_us_index_code)
        assert callable(pkg_us_stock)
        assert callable(pkg_hk_stock)
        assert callable(is_crypto_code)

    def test_exports_semantics(self):
        """导出函数的语义锚定（代表性代码）"""
        from data_provider import (
            is_us_index_code,
            is_us_stock_code as pkg_us_stock,
            is_hk_stock_code as pkg_hk_stock,
            is_crypto_code,
        )
        # 美股指数：SPX 是指数但不是股票
        assert is_us_index_code("SPX") is True
        assert pkg_us_stock("SPX") is False
        # 美股股票
        assert pkg_us_stock("AAPL") is True
        assert is_us_index_code("AAPL") is False
        # 港股
        assert pkg_hk_stock("HK00700") is True
        assert pkg_hk_stock("00700.HK") is True
        assert pkg_hk_stock("600519") is False
        # 加密
        assert is_crypto_code("BTC-USDT") is True
        assert is_crypto_code("600519") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
