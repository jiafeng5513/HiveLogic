# -*- coding: utf-8 -*-
"""
===================================
异动监控引擎 (Anomaly Monitor) — Phase E.1
===================================

职责：
1. 订阅用户自选（watchlist）+ 持仓（portfolio），自动发现监控标的
2. 监控规则（5 维度）：
   a. 价格突破 / 跌破阈值（相对 N 日高/低）
   b. 放量异动（成交量 > N× 均量）
   c. 新闻利空（近期新闻含负面关键词）
   d. 技术形态破位（跌破均线支撑）
   e. 涨跌幅异动（日内涨跌幅超阈值）
3. 复用 L0 全市场快照（DataFetcherManager.get_daily_data）
   + L2 实时流（get_realtime_quote）+ news_service
4. 触发时发布 AnomalyEvent 到 EventBus（内存事件总线）

调度：
- 由 scheduler 注册为后台任务（每 N 分钟轮询）
- 或由 scheduler 命名任务（盘后全量扫描）

设计原则：
- 低延迟：实时行情 + 均量预计算，单标的 < 2s
- 容错：单标的失败不中断整体扫描
- 去重：同一标的同一异动类型在冷却窗口内不重复发布
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from src.services.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


# ======================================================================
# 数据结构
# ======================================================================

class AnomalyType(str, Enum):
    """异动类型。"""
    PRICE_BREAKOUT = "price_breakout"        # 突破 N 日新高
    PRICE_BREAKDOWN = "price_breakdown"      # 跌破 N 日新低
    VOLUME_SPIKE = "volume_spike"            # 放量异动
    NEWS_NEGATIVE = "news_negative"          # 新闻利空
    TECHNICAL_BREAKDOWN = "technical_breakdown"  # 技术破位（跌破均线）
    INTRADAY_SURGE = "intraday_surge"        # 日内大涨
    INTRADAY_PLUNGE = "intraday_plunge"      # 日内大跌


class Severity(str, Enum):
    """严重程度。"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class AnomalyEvent:
    """异动事件 — 发布到 EventBus 的载荷。"""
    symbol: str
    name: str
    anomaly_type: AnomalyType
    severity: Severity
    message: str
    current_value: float = 0.0
    threshold: float = 0.0
    detected_at: float = field(default_factory=time.time)
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "anomaly_type": self.anomaly_type.value,
            "severity": self.severity.value,
            "message": self.message,
            "current_value": self.current_value,
            "threshold": self.threshold,
            "detected_at": self.detected_at,
            "context": self.context,
        }


# ======================================================================
# 默认阈值
# ======================================================================

_DEFAULT_LOOKBACK_DAYS = 20
_DEFAULT_VOLUME_MULTIPLIER = 2.5
_DEFAULT_INTRADAY_PCT = 5.0  # 日内涨跌幅 ±5%
_DEFAULT_NEWS_LOOKBACK_HOURS = 24
_DEFAULT_COOLDOWN_SECONDS = 1800  # 同标的同类型 30 分钟内不重复
_DEFAULT_MA_PERIOD = 20  # 均线周期

# 新闻利空关键词（中文 + 英文）
_NEGATIVE_KEYWORDS = frozenset({
    # 中文
    "暴跌", "闪崩", "跌停", "下挫", "重挫", "大跌", "利空", "亏损",
    "减持", "质押", "爆仓", "违约", "退市", "立案", "处罚", "警示",
    "风险", "下滑", "萎缩", "裁员", "停牌", "问询", "监管",
    # 英文
    "plunge", "crash", "collapse", "downgrade", "loss", "lawsuit",
    "fraud", "investigation", "recall", "bankruptcy", "default",
})


# ======================================================================
# AnomalyMonitor
# ======================================================================

class AnomalyMonitor:
    """异动监控引擎 — 扫描 watchlist + portfolio，发布异动事件。"""

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        *,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
        volume_multiplier: float = _DEFAULT_VOLUME_MULTIPLIER,
        intraday_pct: float = _DEFAULT_INTRADAY_PCT,
        news_lookback_hours: int = _DEFAULT_NEWS_LOOKBACK_HOURS,
        cooldown_seconds: int = _DEFAULT_COOLDOWN_SECONDS,
        ma_period: int = _DEFAULT_MA_PERIOD,
    ):
        self._bus = event_bus or get_event_bus()
        self._lookback_days = lookback_days
        self._volume_multiplier = volume_multiplier
        self._intraday_pct = intraday_pct
        self._news_lookback_hours = news_lookback_hours
        self._cooldown_seconds = cooldown_seconds
        self._ma_period = ma_period

        # 去重冷却：{(symbol, anomaly_type): last_triggered_ts}
        self._cooldown_map: Dict[Tuple[str, str], float] = {}

        logger.info(
            "[AnomalyMonitor] 初始化完成 (lookback=%d天, 量比=%.1f×, 日内阈值=%.1f%%, 冷却=%ds)",
            lookback_days, volume_multiplier, intraday_pct, cooldown_seconds,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_all(self) -> List[AnomalyEvent]:
        """扫描所有监控标的，返回本轮触发的异动事件列表。

        同时将事件发布到 EventBus（topic="anomaly"）。
        """
        symbols = self._get_monitored_symbols()
        if not symbols:
            logger.debug("[AnomalyMonitor] 无监控标的，跳过")
            return []

        logger.info("[AnomalyMonitor] 开始扫描 %d 个标的", len(symbols))

        all_events: List[AnomalyEvent] = []
        for item in symbols:
            symbol = item["symbol"]
            name = item.get("name", "")
            try:
                events = self._check_symbol(symbol, name)
                for evt in events:
                    if self._should_publish(symbol, evt.anomaly_type):
                        all_events.append(evt)
                        self._bus.publish("anomaly", evt)
                        self._mark_published(symbol, evt.anomaly_type)
            except Exception as exc:
                logger.debug(
                    "[AnomalyMonitor] 标的 %s 扫描失败: %s", symbol, exc
                )

        logger.info(
            "[AnomalyMonitor] 扫描完成: %d 标的, %d 异动事件",
            len(symbols), len(all_events),
        )
        return all_events

    # ------------------------------------------------------------------
    # 标的发现
    # ------------------------------------------------------------------

    def _get_monitored_symbols(self) -> List[Dict[str, str]]:
        """合并 watchlist + portfolio 持仓，去重返回。"""
        seen: Set[str] = set()
        result: List[Dict[str, str]] = []

        # 1. Watchlist
        try:
            from src.services.watchlist import WatchlistService
            for item in WatchlistService().get_all():
                sym = item.get("symbol", "").strip()
                if sym and sym not in seen:
                    seen.add(sym)
                    result.append({"symbol": sym, "name": item.get("name", "")})
        except Exception as exc:
            logger.warning("[AnomalyMonitor] 读取 watchlist 失败: %s", exc)

        # 2. Portfolio 持仓
        try:
            from src.services.portfolio_service import PortfolioService
            svc = PortfolioService()
            snapshot = svc.get_portfolio_snapshot()
            for account in snapshot.get("accounts", []):
                for position in account.get("positions", []):
                    sym = (position.get("symbol") or "").strip()
                    if sym and sym not in seen:
                        seen.add(sym)
                        result.append({
                            "symbol": sym,
                            "name": position.get("name", ""),
                        })
        except Exception as exc:
            logger.debug("[AnomalyMonitor] 读取 portfolio 持仓失败: %s", exc)

        return result

    # ------------------------------------------------------------------
    # 单标的检查
    # ------------------------------------------------------------------

    def _check_symbol(self, symbol: str, name: str) -> List[AnomalyEvent]:
        """对单个标的执行全部规则检查。"""
        events: List[AnomalyEvent] = []

        # 获取实时行情
        quote = self._fetch_realtime_quote(symbol)
        # 获取近 N 日日线
        df = self._fetch_daily_data(symbol)

        if quote is not None:
            evt = self._check_intraday_move(symbol, name, quote)
            if evt:
                events.append(evt)

        if df is not None and not df.empty:
            evt = self._check_price_breakout(symbol, name, df, quote)
            if evt:
                events.append(evt)

            evt = self._check_volume_spike(symbol, name, df)
            if evt:
                events.append(evt)

            evt = self._check_technical_breakdown(symbol, name, df, quote)
            if evt:
                events.append(evt)

        # 新闻检查（独立于行情）
        evt = self._check_news_negative(symbol, name)
        if evt:
            events.append(evt)

        return events

    # ------------------------------------------------------------------
    # 规则 1: 日内涨跌幅异动
    # ------------------------------------------------------------------

    def _check_intraday_move(
        self, symbol: str, name: str, quote: Any
    ) -> Optional[AnomalyEvent]:
        """日内涨跌幅超过阈值。"""
        change_pct = float(getattr(quote, "change_percent", 0) or 0)
        if abs(change_pct) < self._intraday_pct:
            return None

        if change_pct > 0:
            atype = AnomalyType.INTRADAY_SURGE
            severity = Severity.WARNING if change_pct >= self._intraday_pct * 2 else Severity.INFO
            msg = f"{name or symbol} 日内大涨 +{change_pct:.2f}%"
        else:
            atype = AnomalyType.INTRADAY_PLUNGE
            severity = Severity.CRITICAL if change_pct <= -self._intraday_pct * 2 else Severity.WARNING
            msg = f"{name or symbol} 日内大跌 {change_pct:.2f}%"

        return AnomalyEvent(
            symbol=symbol,
            name=name,
            anomaly_type=atype,
            severity=severity,
            message=msg,
            current_value=change_pct,
            threshold=self._intraday_pct,
            context={"price": float(getattr(quote, "price", 0) or 0)},
        )

    # ------------------------------------------------------------------
    # 规则 2: 价格突破 / 跌破 N 日高/低
    # ------------------------------------------------------------------

    def _check_price_breakout(
        self, symbol: str, name: str, df: Any, quote: Optional[Any]
    ) -> Optional[AnomalyEvent]:
        """价格突破 N 日新高或跌破 N 日新低。"""
        try:
            # 使用排除今日的最近 N 日（如果数据足够）
            closes = df["close"].iloc[:-1] if len(df) > 1 else df["close"]
            if len(closes) < 5:
                return None

            n_day_high = float(closes.tail(self._lookback_days).max())
            n_day_low = float(closes.tail(self._lookback_days).min())
        except Exception:
            return None

        current_price = 0.0
        if quote is not None:
            current_price = float(getattr(quote, "price", 0) or 0)
        if current_price <= 0 and len(df) > 0:
            current_price = float(df["close"].iloc[-1])
        if current_price <= 0:
            return None

        # 突破新高
        if current_price > n_day_high * 1.0:  # 严格大于
            return AnomalyEvent(
                symbol=symbol,
                name=name,
                anomaly_type=AnomalyType.PRICE_BREAKOUT,
                severity=Severity.INFO,
                message=f"{name or symbol} 突破 {self._lookback_days}日新高 "
                        f"¥{current_price:.2f} (前高 ¥{n_day_high:.2f})",
                current_value=current_price,
                threshold=n_day_high,
                context={"period_days": self._lookback_days},
            )

        # 跌破新低
        if current_price < n_day_low * 1.0:
            return AnomalyEvent(
                symbol=symbol,
                name=name,
                anomaly_type=AnomalyType.PRICE_BREAKDOWN,
                severity=Severity.WARNING,
                message=f"{name or symbol} 跌破 {self._lookback_days}日新低 "
                        f"¥{current_price:.2f} (前低 ¥{n_day_low:.2f})",
                current_value=current_price,
                threshold=n_day_low,
                context={"period_days": self._lookback_days},
            )

        return None

    # ------------------------------------------------------------------
    # 规则 3: 放量异动
    # ------------------------------------------------------------------

    def _check_volume_spike(
        self, symbol: str, name: str, df: Any
    ) -> Optional[AnomalyEvent]:
        """最近一日成交量 > N× 近期均量。"""
        try:
            if "volume" not in df.columns or len(df) < 5:
                return None

            volumes = df["volume"].iloc[:-1] if len(df) > 1 else df["volume"]
            avg_vol = float(volumes.tail(self._lookback_days).mean())
            latest_vol = float(df["volume"].iloc[-1])

            if avg_vol <= 0 or latest_vol <= 0:
                return None

            ratio = latest_vol / avg_vol
            if ratio < self._volume_multiplier:
                return None

            return AnomalyEvent(
                symbol=symbol,
                name=name,
                anomaly_type=AnomalyType.VOLUME_SPIKE,
                severity=Severity.WARNING if ratio >= self._volume_multiplier * 2 else Severity.INFO,
                message=f"{name or symbol} 放量异动: 成交量 {latest_vol:,.0f} "
                        f"({ratio:.1f}× 均量 {avg_vol:,.0f})",
                current_value=latest_vol,
                threshold=avg_vol * self._volume_multiplier,
                context={
                    "avg_volume": avg_vol,
                    "ratio": round(ratio, 2),
                    "multiplier": self._volume_multiplier,
                },
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 规则 4: 技术形态破位（跌破均线支撑）
    # ------------------------------------------------------------------

    def _check_technical_breakdown(
        self, symbol: str, name: str, df: Any, quote: Optional[Any]
    ) -> Optional[AnomalyEvent]:
        """收盘价跌破 N 日均线（支撑破位）。"""
        try:
            if "close" not in df.columns or len(df) < self._ma_period:
                return None

            closes = df["close"]
            ma_value = float(closes.tail(self._ma_period).mean())

            current_price = 0.0
            if quote is not None:
                current_price = float(getattr(quote, "price", 0) or 0)
            if current_price <= 0 and len(df) > 0:
                current_price = float(closes.iloc[-1])
            if current_price <= 0 or ma_value <= 0:
                return None

            # 跌破均线 1% 以上才算破位（避免刚好触碰）
            deviation_pct = (current_price - ma_value) / ma_value * 100.0
            if deviation_pct > -1.0:
                return None

            return AnomalyEvent(
                symbol=symbol,
                name=name,
                anomaly_type=AnomalyType.TECHNICAL_BREAKDOWN,
                severity=Severity.WARNING if deviation_pct <= -3.0 else Severity.INFO,
                message=f"{name or symbol} 跌破 {self._ma_period}日均线支撑 "
                        f"¥{current_price:.2f} (MA{self._ma_period} ¥{ma_value:.2f}, "
                        f"偏离 {deviation_pct:.1f}%)",
                current_value=current_price,
                threshold=ma_value,
                context={
                    "ma_period": self._ma_period,
                    "ma_value": ma_value,
                    "deviation_pct": round(deviation_pct, 2),
                },
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 规则 5: 新闻利空
    # ------------------------------------------------------------------

    def _check_news_negative(
        self, symbol: str, name: str
    ) -> Optional[AnomalyEvent]:
        """近期新闻含利空关键词。"""
        try:
            from src.storage import DatabaseManager
            from src.services.news_service import NewsService

            db = DatabaseManager.get_instance()
            svc = NewsService(db)

            cutoff_hours = self._news_lookback_hours
            days = max(1, cutoff_hours // 24 + 1)

            total, items = svc.get_news_list(
                code=symbol, days=days, page_size=20
            )
            if not items:
                return None

            # 检查最近 cutoff_hours 内的新闻
            cutoff_dt = datetime.now() - timedelta(hours=cutoff_hours)
            negative_items: List[Dict[str, Any]] = []

            for item in items:
                published_str = item.get("published_date", "")
                if not published_str:
                    continue
                try:
                    published = datetime.strptime(
                        published_str, "%Y-%m-%d %H:%M:%S"
                    )
                except (ValueError, TypeError):
                    continue

                if published < cutoff_dt:
                    continue

                text = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
                matched = [kw for kw in _NEGATIVE_KEYWORDS if kw in text]
                if matched:
                    negative_items.append({
                        "title": item.get("title", ""),
                        "matched_keywords": matched[:5],
                        "published_date": published_str,
                    })

            if not negative_items:
                return None

            top = negative_items[0]
            return AnomalyEvent(
                symbol=symbol,
                name=name,
                anomaly_type=AnomalyType.NEWS_NEGATIVE,
                severity=Severity.CRITICAL if len(negative_items) >= 3 else Severity.WARNING,
                message=f"{name or symbol} 近 {cutoff_hours}h 出现 {len(negative_items)} 条利空新闻: "
                        f"「{top['title'][:40]}...」",
                current_value=float(len(negative_items)),
                threshold=1.0,
                context={
                    "negative_items": negative_items[:5],
                    "lookback_hours": cutoff_hours,
                },
            )
        except Exception as exc:
            logger.debug("[AnomalyMonitor] 新闻检查失败 %s: %s", symbol, exc)
            return None

    # ------------------------------------------------------------------
    # 数据获取辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_realtime_quote(symbol: str) -> Optional[Any]:
        """获取实时行情（L2 流降级到轮询）。"""
        try:
            from data_provider import DataFetcherManager
            fm = DataFetcherManager()
            return fm.get_realtime_quote(symbol, log_final_failure=False)
        except Exception:
            return None

    @staticmethod
    def _fetch_daily_data(symbol: str) -> Optional[Any]:
        """获取近 N 日日线数据（L0 快照）。"""
        try:
            from data_provider import DataFetcherManager
            fm = DataFetcherManager()
            result = fm.get_daily_data(symbol, days=_DEFAULT_LOOKBACK_DAYS + 5)
            if result is None:
                return None
            df, _source = result
            return df
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 去重冷却
    # ------------------------------------------------------------------

    def _should_publish(self, symbol: str, anomaly_type: AnomalyType) -> bool:
        """检查是否在冷却窗口内（避免重复发布）。"""
        key = (symbol, anomaly_type.value)
        last_ts = self._cooldown_map.get(key)
        if last_ts is None:
            return True
        return (time.time() - last_ts) >= self._cooldown_seconds

    def _mark_published(self, symbol: str, anomaly_type: AnomalyType) -> None:
        """记录发布时间。"""
        key = (symbol, anomaly_type.value)
        self._cooldown_map[key] = time.time()

        # 清理过期条目（防止 map 无限增长）
        if len(self._cooldown_map) > 500:
            cutoff = time.time() - self._cooldown_seconds
            expired = [k for k, v in self._cooldown_map.items() if v < cutoff]
            for k in expired:
                self._cooldown_map.pop(k, None)


# ======================================================================
# 单例 + 调度入口
# ======================================================================

_monitor_instance: Optional[AnomalyMonitor] = None
_monitor_lock = __import__("threading").Lock()


def get_anomaly_monitor(config=None) -> Optional[AnomalyMonitor]:
    """根据配置获取 AnomalyMonitor 单例。

    若配置未启用，返回 None。
    """
    global _monitor_instance

    if config is None:
        from src.config import get_config
        config = get_config()

    if not getattr(config, "agent_anomaly_monitor_enabled", False):
        return None

    with _monitor_lock:
        if _monitor_instance is None:
            _monitor_instance = AnomalyMonitor(
                lookback_days=getattr(config, "agent_anomaly_lookback_days", _DEFAULT_LOOKBACK_DAYS),
                volume_multiplier=getattr(config, "agent_anomaly_volume_multiplier", _DEFAULT_VOLUME_MULTIPLIER),
                intraday_pct=getattr(config, "agent_anomaly_intraday_pct", _DEFAULT_INTRADAY_PCT),
                news_lookback_hours=getattr(config, "agent_anomaly_news_lookback_hours", _DEFAULT_NEWS_LOOKBACK_HOURS),
                cooldown_seconds=getattr(config, "agent_anomaly_cooldown_seconds", _DEFAULT_COOLDOWN_SECONDS),
                ma_period=getattr(config, "agent_anomaly_ma_period", _DEFAULT_MA_PERIOD),
            )
        return _monitor_instance


def run_anomaly_scan() -> int:
    """调度入口：执行一轮异动扫描，返回触发的异动事件数。"""
    monitor = get_anomaly_monitor()
    if monitor is None:
        logger.debug("[AnomalyMonitor] 未启用，跳过扫描")
        return 0

    events = monitor.check_all()
    return len(events)
