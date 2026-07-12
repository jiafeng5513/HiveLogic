# -*- coding: utf-8 -*-
"""
===================================
机会发现引擎 (Opportunity Scanner) — Phase E.3
===================================

职责：
1. 每日盘后定时执行"机会扫描"
2. 全市场快照筛选异动标的（涨跌幅 / 放量 / 金额排名）
3. 对 top N 标的执行 autonomous 深度分析
4. 结合用户画像个性化排序后存入 ProactiveMessage 表
5. 未来推送通道接入后，转发"今日值得关注"推送

调度：
- 由 scheduler 注册为命名每日任务（如 18:30 盘后执行）
- 触发时间由 config.agent_opportunity_scan_time 控制

筛选逻辑：
- 涨幅榜 top N（排除 ST / 退市）
- 跌幅榜 top N（超跌反弹机会）
- 放量榜 top N（量价齐升）
- 金额榜 top N（大资金关注）
- 合并去重后取 top N 深度分析
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from src.services.anomaly_monitor import AnomalyType, Severity
from src.services.anomaly_monitor import AnomalyEvent  # re-export for event bus publish

logger = logging.getLogger(__name__)

# 默认参数
_DEFAULT_TOP_N = 10
_DEFAULT_RANK_POOL = 30  # 每个榜单取多少候选
_DEFAULT_MIN_AMOUNT = 1e8  # 最小成交额（过滤低流动性标的，1亿）

# 排除的前缀（ST / 退市 / 低流动性）
_EXCLUDE_PREFIXES = ("ST", "*ST", "N", "C", "退")


# ======================================================================
# OpportunityScanner
# ======================================================================

class OpportunityScanner:
    """盘后机会扫描引擎 — 全市场快照 → top N 深度分析。"""

    def __init__(
        self,
        *,
        top_n: int = _DEFAULT_TOP_N,
        rank_pool: int = _DEFAULT_RANK_POOL,
        min_amount: float = _DEFAULT_MIN_AMOUNT,
    ):
        self._top_n = top_n
        self._rank_pool = rank_pool
        self._min_amount = min_amount
        logger.info(
            "[OpportunityScanner] 初始化 (top_n=%d, rank_pool=%d, min_amount=%.0f)",
            top_n, rank_pool, min_amount,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_and_analyze(self) -> int:
        """执行一轮完整的机会扫描 + 深度分析。

        Returns:
            生成的主动消息数。
        """
        logger.info("[OpportunityScanner] 开始盘后机会扫描")

        # 1. 获取全市场快照
        all_snapshots = self._fetch_all_snapshots()
        if not all_snapshots:
            logger.warning("[OpportunityScanner] 无市场快照数据，跳过")
            return 0

        logger.info(
            "[OpportunityScanner] 快照总数: %d", len(all_snapshots)
        )

        # 2. 筛选候选标的
        candidates = self._select_candidates(all_snapshots)
        if not candidates:
            logger.info("[OpportunityScanner] 无候选标的，跳过")
            return 0

        logger.info(
            "[OpportunityScanner] 候选标的: %d 个 (将深度分析 top %d)",
            len(candidates), min(self._top_n, len(candidates)),
        )

        # 3. 对 top N 执行深度分析
        top_candidates = candidates[: self._top_n]
        messages_created = 0

        for candidate in top_candidates:
            try:
                created = self._analyze_and_store(candidate)
                if created:
                    messages_created += 1
            except Exception as exc:
                logger.warning(
                    "[OpportunityScanner] 分析 %s 失败: %s",
                    candidate.get("symbol", "?"), exc,
                )

        logger.info(
            "[OpportunityScanner] 扫描完成: %d 个主动消息已生成",
            messages_created,
        )
        return messages_created

    # ------------------------------------------------------------------
    # 数据获取
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_all_snapshots() -> List[Dict[str, Any]]:
        """从 market_snapshot 表获取全部市场的快照数据。"""
        try:
            from src.services.market_collector import get_market_collector
            collector = get_market_collector()

            all_rows: List[Dict[str, Any]] = []
            for market in ("cn_stock", "cn_etf", "hk_stock", "us_stock", "crypto"):
                try:
                    rows = collector.get_market_snapshots(market)
                    for r in rows:
                        r["market"] = market
                    all_rows.extend(rows)
                except Exception as exc:
                    logger.debug(
                        "[OpportunityScanner] 获取 %s 快照失败: %s",
                        market, exc,
                    )
            return all_rows
        except Exception as exc:
            logger.error("[OpportunityScanner] 获取市场快照失败: %s", exc)
            return []

    # ------------------------------------------------------------------
    # 候选筛选
    # ------------------------------------------------------------------

    def _select_candidates(
        self, snapshots: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """从全市场快照中筛选候选标的。

        策略：合并涨幅榜 + 跌幅榜 + 放量榜 + 金额榜，去重后按综合分排序。
        """
        # 过滤无效数据
        valid = []
        for s in snapshots:
            symbol = (s.get("symbol") or "").strip()
            name = (s.get("name") or "").strip()
            if not symbol:
                continue
            # 排除 ST / 退市
            if any(name.startswith(prefix) for prefix in _EXCLUDE_PREFIXES):
                continue
            change_pct = _safe_float(s.get("change_percent"))
            amount = _safe_float(s.get("amount"))
            volume = _safe_float(s.get("volume"))
            if change_pct is None or amount is None:
                continue
            # 过滤低流动性
            if amount < self._min_amount:
                continue
            valid.append({
                "symbol": symbol,
                "name": name,
                "market": s.get("market", ""),
                "price": _safe_float(s.get("price")) or 0.0,
                "change_percent": change_pct,
                "volume": volume or 0.0,
                "amount": amount,
                "turnover_high": _safe_float(s.get("high")) or 0.0,
                "turnover_low": _safe_float(s.get("low")) or 0.0,
            })

        if not valid:
            return []

        # 各榜单 top pool
        gainers = self._rank_by(valid, "change_percent", reverse=True)
        losers = self._rank_by(valid, "change_percent", reverse=False)
        volume_leaders = self._rank_by(valid, "volume", reverse=True)
        amount_leaders = self._rank_by(valid, "amount", reverse=True)

        # 合并去重 + 综合评分
        seen: Set[str] = set()
        scored: List[Tuple[Dict[str, Any], float]] = []

        for rank_list in (gainers, losers, volume_leaders, amount_leaders):
            for rank_idx, item in enumerate(rank_list):
                sym = item["symbol"]
                if sym in seen:
                    continue
                seen.add(sym)
                # 综合分：排名越靠前分越高（4 个榜单各取 pool，最高分 = 4*pool）
                score = (self._rank_pool - rank_idx)
                scored.append((item, float(score)))

        # 按综合分降序
        scored.sort(key=lambda x: x[1], reverse=True)
        candidates = [item for item, _ in scored]

        # 标注入选原因
        top_symbols = {item["symbol"] for item in candidates[: self._top_n * 2]}
        for item in candidates:
            reasons: List[str] = []
            if item in gainers[: self._rank_pool]:
                reasons.append(f"涨幅榜 ({'+' if item['change_percent'] >= 0 else ''}{item['change_percent']:.2f}%)")
            if item in losers[: self._rank_pool]:
                reasons.append(f"跌幅榜 ({item['change_percent']:.2f}%)")
            if item in volume_leaders[: self._rank_pool]:
                reasons.append(f"放量榜 (量 {item['volume']:,.0f})")
            if item in amount_leaders[: self._rank_pool]:
                reasons.append(f"金额榜 (额 {item['amount']:,.0f})")
            item["reasons"] = reasons

        return candidates

    def _rank_by(
        self,
        items: List[Dict[str, Any]],
        key: str,
        *,
        reverse: bool = True,
    ) -> List[Dict[str, Any]]:
        """按 key 排序，返回 top rank_pool。"""
        sorted_items = sorted(
            items,
            key=lambda x: x.get(key, 0) or 0,
            reverse=reverse,
        )
        return sorted_items[: self._rank_pool]

    # ------------------------------------------------------------------
    # 深度分析 + 存储
    # ------------------------------------------------------------------

    def _analyze_and_store(self, candidate: Dict[str, Any]) -> bool:
        """对单个候选标的执行深度分析并存储结果。

        Returns:
            是否成功生成主动消息。
        """
        symbol = candidate["symbol"]
        name = candidate["name"]

        # 构造分析 prompt
        prompt = self._build_prompt(candidate)

        # 执行深度分析
        result = self._run_analysis(prompt)
        if result is None:
            return False

        content, summary, signal, confidence = self._extract_result(result)

        # 存储主动消息
        return self._store_message(
            candidate=candidate,
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

    # ------------------------------------------------------------------
    # Prompt 构造
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(candidate: Dict[str, Any]) -> str:
        """构造深度分析 prompt。"""
        reasons_text = "；".join(candidate.get("reasons", [])) or "综合排名靠前"

        prompt = f"""【盘后机会扫描 — 深度分析】

今日市场扫描发现此标的表现突出，请进行深度分析。

标的：{candidate['name'] or candidate['symbol']} ({candidate['symbol']})
市场：{candidate.get('market', '')}
当前价：¥{candidate.get('price', 0):.2f}
涨跌幅：{candidate['change_percent']:+.2f}%
成交量：{candidate.get('volume', 0):,.0f}
成交额：¥{candidate.get('amount', 0):,.0f}
日内高/低：¥{candidate.get('turnover_high', 0):.2f} / ¥{candidate.get('turnover_low', 0):.2f}
入选原因：{reasons_text}

请深度分析：
1. 今日异动原因分析（基本面/技术面/资金面/消息面）
2. 后续走势研判（短期 + 中期）
3. 风险提示
4. 建议操作（买入/卖出/持有/观察）及置信度（0-1）

请给出结构化分析结论。"""
        return prompt

    # ------------------------------------------------------------------
    # 深度分析执行
    # ------------------------------------------------------------------

    @staticmethod
    def _run_analysis(prompt: str) -> Optional[Dict[str, Any]]:
        """调用 agent executor 执行深度分析（quick 模式）。"""
        try:
            from src.agent.factory import build_agent_executor
            from src.config import get_config

            config = get_config()
            executor = build_agent_executor(config=config, mode="quick")

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
            logger.error("[OpportunityScanner] AI 分析执行失败: %s", exc)
            return None

    # ------------------------------------------------------------------
    # 结果提取（复用 ProactiveAnalyzer 的逻辑）
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_result(
        result: Dict[str, Any],
    ) -> tuple[str, str, str, float]:
        """从分析结果中提取 content / summary / signal / confidence。"""
        content = (result.get("content") or "").strip()

        dashboard = result.get("dashboard")
        signal = ""
        confidence = 0.0
        summary = ""

        if dashboard and isinstance(dashboard, dict):
            decision = dashboard.get("decision") or {}
            if isinstance(decision, dict):
                signal = str(
                    decision.get("signal") or decision.get("action") or ""
                ).lower()
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

        if not summary and content:
            summary = content[:80].replace("\n", " ")
            if len(content) > 80:
                summary += "..."

        return content, summary, signal, confidence

    # ------------------------------------------------------------------
    # 存储
    # ------------------------------------------------------------------

    @staticmethod
    def _store_message(
        candidate: Dict[str, Any],
        content: str,
        summary: str,
        signal: str,
        confidence: float,
        extra_context: Dict[str, Any],
    ) -> bool:
        """存储机会扫描结果到 ProactiveMessage 表。"""
        try:
            from src.storage import DatabaseManager
            from src.models.proactive_message import ProactiveMessage

            context = {
                "market": candidate.get("market", ""),
                "price": candidate.get("price", 0),
                "change_percent": candidate.get("change_percent", 0),
                "volume": candidate.get("volume", 0),
                "amount": candidate.get("amount", 0),
                "reasons": candidate.get("reasons", []),
                **extra_context,
            }

            # 严重程度根据涨跌幅判断
            change_pct = candidate.get("change_percent", 0)
            if abs(change_pct) >= 8.0:
                severity = Severity.CRITICAL
            elif abs(change_pct) >= 5.0:
                severity = Severity.WARNING
            else:
                severity = Severity.INFO

            db = DatabaseManager.get_instance()
            with db.session_scope() as session:
                msg = ProactiveMessage(
                    message_type="opportunity",
                    symbol=candidate["symbol"],
                    symbol_name=candidate["name"],
                    trigger_type="opportunity_scan",
                    trigger_severity=severity.value,
                    trigger_summary=(
                        f"{candidate['name'] or candidate['symbol']} "
                        f"{'+' if change_pct >= 0 else ''}{change_pct:.2f}% "
                        f"额 ¥{candidate.get('amount', 0):,.0f}"
                    ),
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
                "[OpportunityScanner] 机会消息已存储 id=%s symbol=%s signal=%s",
                msg_id, candidate["symbol"], signal,
            )
            return True
        except Exception as exc:
            logger.error(
                "[OpportunityScanner] 存储机会消息失败: %s", exc
            )
            return False


# ======================================================================
# 单例 + 调度入口
# ======================================================================

_scanner_instance: Optional[OpportunityScanner] = None
_scanner_lock = __import__("threading").Lock()


def get_opportunity_scanner(config=None) -> Optional[OpportunityScanner]:
    """根据配置获取 OpportunityScanner 单例。

    若配置未启用，返回 None。
    """
    global _scanner_instance

    if config is None:
        from src.config import get_config
        config = get_config()

    if not getattr(config, "agent_opportunity_scan_enabled", False):
        return None

    with _scanner_lock:
        if _scanner_instance is None:
            _scanner_instance = OpportunityScanner(
                top_n=getattr(config, "agent_opportunity_scan_top_n", _DEFAULT_TOP_N),
            )
        return _scanner_instance


def run_opportunity_scan() -> int:
    """调度入口：执行一轮盘后机会扫描。

    Returns:
        生成的主动消息数。
    """
    scanner = get_opportunity_scanner()
    if scanner is None:
        logger.debug("[OpportunityScanner] 未启用，跳过扫描")
        return 0

    return scanner.scan_and_analyze()


# ======================================================================
# 辅助函数
# ======================================================================

def _safe_float(val: Any) -> Optional[float]:
    """安全转 float，失败返回 None。"""
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None
