# -*- coding: utf-8 -*-
"""
===================================
主动分析触发器 (Proactive Analyzer) — Phase E.2
===================================

职责：
1. 订阅 EventBus 的 "anomaly" 主题，接收异动事件
2. 对异动事件触发轻量版 autonomous 分析（步数上限低）
3. 将 AI 分析结果存入 ProactiveMessage 表
4. 未来推送通道接入后，转发到推送调度器

设计：
- 订阅在 app lifespan 启动时注册
- 分析在独立线程中执行（不阻塞 EventBus 发布线程）
- 轻量分析复用 build_agent_executor，mode="quick"，max_steps 受配置限制
- 同一标的冷却窗口内不重复分析（避免异动风暴）

使用::

    from src.services.proactive_analyzer import get_proactive_analyzer

    analyzer = get_proactive_analyzer()
    analyzer.start()  # 注册 EventBus 订阅
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Any, Dict, List, Optional

from src.services.anomaly_monitor import AnomalyEvent, AnomalyType, Severity
from src.services.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)

# 分析结果冷却：同标的 30 分钟内不重复分析
_ANALYSIS_COOLDOWN_SECONDS = 1800
# 工作队列最大积压
_MAX_QUEUE_SIZE = 100


class ProactiveAnalyzer:
    """异动事件 → 轻量 AI 分析 → 存储主动消息。"""

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        *,
        max_steps: int = 5,
        cooldown_seconds: int = _ANALYSIS_COOLDOWN_SECONDS,
    ):
        self._bus = event_bus or get_event_bus()
        self._max_steps = max_steps
        self._cooldown_seconds = cooldown_seconds

        # 工作队列：异动事件入队，工作线程消费
        self._work_queue: "queue.Queue[AnomalyEvent]" = queue.Queue(
            maxsize=_MAX_QUEUE_SIZE
        )
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False

        # 分析冷却：{symbol: last_analysis_ts}
        self._cooldown_map: Dict[str, float] = {}

        logger.info(
            "[ProactiveAnalyzer] 初始化 (max_steps=%d, cooldown=%ds)",
            max_steps, cooldown_seconds,
        )

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        """注册 EventBus 订阅 + 启动工作线程。"""
        if self._running:
            return

        self._bus.subscribe("anomaly", self._on_anomaly_event)
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="proactive-analyzer",
        )
        self._worker_thread.start()
        logger.info("[ProactiveAnalyzer] 已启动，订阅 anomaly 主题")

    def stop(self) -> None:
        """停止工作线程。"""
        self._running = False
        # 投入哨兵唤醒阻塞的 get
        try:
            self._work_queue.put_nowait(None)  # type: ignore[arg-type]
        except queue.Full:
            pass
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
        self._bus.unsubscribe("anomaly", self._on_anomaly_event)
        logger.info("[ProactiveAnalyzer] 已停止")

    # ------------------------------------------------------------------
    # EventBus 回调
    # ------------------------------------------------------------------

    def _on_anomaly_event(self, event: Any) -> None:
        """EventBus 回调 — 将事件入队（非阻塞）。"""
        if not isinstance(event, AnomalyEvent):
            return

        # 冷却检查
        if not self._should_analyze(event.symbol):
            logger.debug(
                "[ProactiveAnalyzer] %s 在分析冷却中，跳过", event.symbol
            )
            return

        try:
            self._work_queue.put_nowait(event)
        except queue.Full:
            logger.warning(
                "[ProactiveAnalyzer] 工作队列已满，丢弃异动事件 %s",
                event.symbol,
            )

    # ------------------------------------------------------------------
    # 工作线程
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        """消费工作队列，执行轻量分析。"""
        while self._running:
            try:
                event = self._work_queue.get(timeout=10)
            except queue.Empty:
                continue
            if event is None:
                break

            try:
                self._process_event(event)
            except Exception as exc:
                logger.warning(
                    "[ProactiveAnalyzer] 处理异动事件失败 %s: %s",
                    event.symbol, exc,
                )
            finally:
                self._work_queue.task_done()

    # ------------------------------------------------------------------
    # 核心处理
    # ------------------------------------------------------------------

    def _process_event(self, event: AnomalyEvent) -> None:
        """对单个异动事件执行轻量分析并存储结果。"""
        logger.info(
            "[ProactiveAnalyzer] 开始分析 %s (%s)",
            event.symbol, event.anomaly_type.value,
        )

        self._mark_analyzed(event.symbol)

        # 构造分析 prompt
        prompt = self._build_prompt(event)

        # 执行轻量分析
        result = self._run_analysis(prompt)

        if result is None:
            logger.warning(
                "[ProactiveAnalyzer] %s 分析失败，不存储主动消息",
                event.symbol,
            )
            return

        # 提取结论
        content, summary, signal, confidence = self._extract_result(result)

        # 存储主动消息
        self._store_message(
            event=event,
            content=content,
            summary=summary,
            signal=signal,
            confidence=confidence,
            extra_context={
                "analysis_steps": result.get("total_steps", 0),
                "analysis_tokens": result.get("total_tokens", 0),
                "models_used": result.get("model", ""),
            },
        )

        logger.info(
            "[ProactiveAnalyzer] %s 分析完成 signal=%s confidence=%.2f",
            event.symbol, signal, confidence,
        )

    # ------------------------------------------------------------------
    # Prompt 构造
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(event: AnomalyEvent) -> str:
        """根据异动事件构造 AI 分析 prompt。"""
        severity_label = {
            Severity.INFO: "提示",
            Severity.WARNING: "警告",
            Severity.CRITICAL: "严重",
        }.get(event.severity, "提示")

        prompt = f"""【主动分析请求 — 异动监控】

检测到异动，请快速分析原因并给出建议。

标的：{event.name or event.symbol} ({event.symbol})
异动类型：{event.anomaly_type.value}
严重程度：{severity_label}
异动描述：{event.message}
当前值：{event.current_value}
阈值：{event.threshold}
检测时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(event.detected_at))}

请快速分析：
1. 可能的原因（基本面/技术面/资金面/消息面）
2. 短期风险与机会评估
3. 建议操作（买入/卖出/持有/观察）
4. 置信度（0-1）

请简洁回答，控制在 300 字以内。"""
        return prompt

    # ------------------------------------------------------------------
    # 轻量分析执行
    # ------------------------------------------------------------------

    def _run_analysis(self, prompt: str) -> Optional[Dict[str, Any]]:
        """调用 agent executor 执行轻量分析。

        复用 build_agent_executor，mode="quick"。
        在独立线程中同步执行（已在工作线程内）。
        """
        try:
            from src.agent.factory import build_agent_executor
            from src.config import get_config

            config = get_config()
            executor = build_agent_executor(config=config, mode="quick")

            # 限制 max_steps
            if hasattr(executor, "max_steps"):
                executor.max_steps = min(
                    self._max_steps, executor.max_steps
                )

            # 使用 run() 而非 chat()，无需 session 管理
            result = executor.run(prompt)

            return {
                "content": getattr(result, "content", ""),
                "dashboard": getattr(result, "dashboard", None),
                "total_steps": getattr(result, "total_steps", 0),
                "total_tokens": getattr(result, "total_tokens", 0),
                "model": getattr(result, "model", ""),
                "success": getattr(result, "success", False),
            }
        except Exception as exc:
            logger.error("[ProactiveAnalyzer] AI 分析执行失败: %s", exc)
            return None

    # ------------------------------------------------------------------
    # 结果提取
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_result(
        result: Dict[str, Any],
    ) -> tuple[str, str, str, float]:
        """从分析结果中提取 content / summary / signal / confidence。"""
        content = (result.get("content") or "").strip()

        # 尝试从 dashboard 提取结构化信号
        dashboard = result.get("dashboard")
        signal = ""
        confidence = 0.0
        summary = ""

        if dashboard and isinstance(dashboard, dict):
            # dashboard 结构：可能含 decision / signal / confidence
            decision = dashboard.get("decision") or {}
            if isinstance(decision, dict):
                signal = str(decision.get("signal") or decision.get("action") or "").lower()
                conf_raw = decision.get("confidence")
                if conf_raw is not None:
                    try:
                        confidence = float(conf_raw)
                    except (TypeError, ValueError):
                        confidence = 0.0
            summary = str(
                dashboard.get("summary")
                or dashboard.get("conclusion")
                or ""
            )

        # Fallback：从 content 中提取 signal
        if not signal:
            content_lower = content.lower()
            if "买入" in content or "buy" in content_lower:
                signal = "buy"
            elif "卖出" in content or "sell" in content_lower:
                signal = "sell"
            elif "持有" in content or "hold" in content_lower:
                signal = "hold"
            else:
                signal = "watch"

        # Fallback：summary 取 content 前 80 字
        if not summary and content:
            summary = content[:80].replace("\n", " ")
            if len(content) > 80:
                summary += "..."

        return content, summary, signal, confidence

    # ------------------------------------------------------------------
    # 存储
    # ------------------------------------------------------------------

    def _store_message(
        self,
        event: AnomalyEvent,
        content: str,
        summary: str,
        signal: str,
        confidence: float,
        extra_context: Dict[str, Any],
    ) -> None:
        """存储主动消息到 ProactiveMessage 表。"""
        try:
            from src.storage import DatabaseManager
            from src.models.proactive_message import ProactiveMessage

            context = {
                "anomaly_type": event.anomaly_type.value,
                "severity": event.severity.value,
                "current_value": event.current_value,
                "threshold": event.threshold,
                "detected_at": event.detected_at,
                **event.context,
                **extra_context,
            }

            db = DatabaseManager.get_instance()
            with db.session_scope() as session:
                msg = ProactiveMessage(
                    message_type="anomaly_response",
                    symbol=event.symbol,
                    symbol_name=event.name,
                    trigger_type=event.anomaly_type.value,
                    trigger_severity=event.severity.value,
                    trigger_summary=event.message,
                    analysis_content=content,
                    analysis_summary=summary,
                    signal=signal,
                    confidence=confidence,
                    context_json=json.dumps(context, ensure_ascii=False),
                    status="unread",
                )
                session.add(msg)
                session.flush()
                msg_id = msg.id

            logger.info(
                "[ProactiveAnalyzer] 主动消息已存储 id=%s symbol=%s",
                msg_id, event.symbol,
            )
        except Exception as exc:
            logger.error(
                "[ProactiveAnalyzer] 存储主动消息失败: %s", exc
            )

    # ------------------------------------------------------------------
    # 冷却
    # ------------------------------------------------------------------

    def _should_analyze(self, symbol: str) -> bool:
        """检查标的是否在分析冷却窗口内。"""
        last = self._cooldown_map.get(symbol)
        if last is None:
            return True
        return (time.time() - last) >= self._cooldown_seconds

    def _mark_analyzed(self, symbol: str) -> None:
        """记录分析时间。"""
        self._cooldown_map[symbol] = time.time()

        # 清理过期条目
        if len(self._cooldown_map) > 200:
            cutoff = time.time() - self._cooldown_seconds
            expired = [k for k, v in self._cooldown_map.items() if v < cutoff]
            for k in expired:
                self._cooldown_map.pop(k, None)


# ======================================================================
# 单例
# ======================================================================

_analyzer_instance: Optional[ProactiveAnalyzer] = None
_analyzer_lock = threading.Lock()


def get_proactive_analyzer(config=None) -> Optional[ProactiveAnalyzer]:
    """根据配置获取 ProactiveAnalyzer 单例。

    若配置未启用，返回 None。
    """
    global _analyzer_instance

    if config is None:
        from src.config import get_config
        config = get_config()

    if not getattr(config, "agent_proactive_analysis_enabled", False):
        return None

    with _analyzer_lock:
        if _analyzer_instance is None:
            _analyzer_instance = ProactiveAnalyzer(
                max_steps=getattr(config, "agent_proactive_analysis_max_steps", 5),
                cooldown_seconds=_ANALYSIS_COOLDOWN_SECONDS,
            )
        return _analyzer_instance
