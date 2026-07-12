# -*- coding: utf-8 -*-
"""
DecisionTracker — Phase D.1 决策结果跟踪与验证服务。

职责：
1. 扫描到达验证窗口但尚未验证的 DecisionLog 记录。
2. 从 StockDaily 表查询决策时刻与 N 日后的收盘价。
3. 计算收益率、实际方向、偏差分、胜/负/平结果。
4. 回写 DecisionLog（多窗口：1 日 / 5 日 / 20 日）。

验证逻辑：
- 主验证窗口 = 5 个交易日（actual_return_pct / outcome / deviation_score）。
- 辅助窗口 = 1 日（return_1d_pct）与 20 日（return_20d_pct），仅记录不参与主 outcome 判定。
- 偏差分定义：buy 信号 → +return_pct（涨得越多越准）；sell 信号 → -return_pct（跌得越多越准）；
  hold 信号 → -|return_pct|（不涨不跌最准）。范围 [-1, 1]，0 = 完全准确。
- outcome 判定（5 日窗口）：
  - buy/strong_buy: return >= +2% → win; return <= -2% → loss; 否则 neutral
  - sell/strong_sell: return <= -2% → win; return >= +2% → loss; 否则 neutral
  - hold: |return| < 2% → win; 否则 neutral

定时触发：由 scheduler 每日调用 ``verify_pending_decisions()``。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import List, Optional

from src.agent.reflection.models import DecisionLog
from src.agent.reflection.repository import ReflectionRepository
from src.agent.reflection.service import ReflectionService
from src.storage import DatabaseManager

logger = logging.getLogger(__name__)

# 验证窗口（交易日近似为自然日 + buffer，因 StockDaily 仅含交易日数据）
_PRIMARY_WINDOW_DAYS = 5  # 主验证窗口
_1D_WINDOW_DAYS = 1
_20D_WINDOW_DAYS = 20

# outcome 判定阈值
_OUTCOME_THRESHOLD_PCT = 2.0  # ±2%

# 单次扫描最多验证多少条（防止积压时一次性跑太久）
_BATCH_LIMIT = 200


class DecisionTracker:
    """决策验证跟踪器 — 定时回看决策结果。"""

    def __init__(
        self,
        repository: Optional[ReflectionRepository] = None,
        service: Optional[ReflectionService] = None,
    ):
        if repository is not None and service is not None:
            self._repo = repository
            self._service = service
        else:
            db = DatabaseManager.get_instance()
            self._repo = repository or ReflectionRepository(db.session_scope)
            self._service = service or ReflectionService(self._repo)

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def verify_pending_decisions(self) -> int:
        """扫描并验证所有到期的未验证决策。

        Returns:
            本次成功验证的决策条数。
        """
        verified_count = 0

        # 20 日窗口是最大窗口，只要 created_at + 20d <= now 就可以一次性算出所有窗口。
        # 但为避免数据不足时跳过主验证，我们分窗口独立处理：
        # 1. 先处理 5 日主窗口（主 outcome）
        # 2. 再补充 1 日 / 20 日辅助字段（仅对已通过主验证的记录）
        primary_candidates = self._service.get_pending_verifications(
            window_days=_PRIMARY_WINDOW_DAYS, limit=_BATCH_LIMIT
        )

        logger.info(
            "[DecisionTracker] 发现 %d 条待主验证决策（%d 日窗口）",
            len(primary_candidates),
            _PRIMARY_WINDOW_DAYS,
        )

        for decision in primary_candidates:
            try:
                self._verify_primary_window(decision)
                verified_count += 1
            except Exception as exc:
                logger.warning(
                    "[DecisionTracker] 主验证失败 decision_id=%s: %s",
                    decision.id,
                    exc,
                )

        # 补充辅助窗口字段（1 日 / 20 日）—— 对已验证但辅助字段为空的记录
        self._backfill_auxiliary_windows()

        logger.info(
            "[DecisionTracker] 本次验证完成，成功 %d 条", verified_count
        )
        return verified_count

    # -----------------------------------------------------------------
    # Internal: primary window (5-day outcome)
    # -----------------------------------------------------------------

    def _verify_primary_window(self, decision: DecisionLog) -> None:
        """对单条决策执行 5 日窗口主验证。"""
        if not decision.stock_code or not decision.created_at:
            return

        decision_date = decision.created_at.date()
        end_date = decision_date + timedelta(days=_PRIMARY_WINDOW_DAYS * 2)  # 自然日 buffer

        prices = self._fetch_prices(
            decision.stock_code, decision_date, end_date
        )
        if len(prices) < 2:
            # 数据不足，跳过（下次再扫）
            logger.debug(
                "[DecisionTracker] decision_id=%s 价格数据不足 (%d 条)，跳过",
                decision.id,
                len(prices),
            )
            return

        entry_price = prices[0].close  # 决策日收盘价
        # 第 5 个交易日（如果不足 5 日，取最后一个）
        exit_idx = min(_PRIMARY_WINDOW_DAYS, len(prices) - 1)
        exit_price = prices[exit_idx].close

        if entry_price <= 0:
            return

        return_pct = (exit_price - entry_price) / entry_price * 100.0
        actual_direction = self._classify_direction(return_pct)
        deviation_score = self._compute_deviation(decision.signal, return_pct)
        outcome = self._classify_outcome(decision.signal, return_pct)

        # 同时计算 1 日收益（如果数据足够）
        return_1d: Optional[float] = None
        if len(prices) >= 2:
            return_1d = (prices[1].close - entry_price) / entry_price * 100.0

        # 20 日收益（如果数据足够）
        return_20d: Optional[float] = None
        if len(prices) > _PRIMARY_WINDOW_DAYS:
            idx_20d = min(_20D_WINDOW_DAYS, len(prices) - 1)
            if idx_20d > exit_idx:
                return_20d = (prices[idx_20d].close - entry_price) / entry_price * 100.0

        self._service.update_verification(
            decision_id=decision.id,
            actual_return_pct=round(return_pct, 4),
            actual_direction=actual_direction,
            deviation_score=round(deviation_score, 4),
            outcome=outcome,
            return_1d_pct=round(return_1d, 4) if return_1d is not None else None,
            return_20d_pct=round(return_20d, 4) if return_20d is not None else None,
        )

        logger.info(
            "[DecisionTracker] decision_id=%s signal=%s return=%.2f%% outcome=%s",
            decision.id,
            decision.signal,
            return_pct,
            outcome,
        )

    # -----------------------------------------------------------------
    # Internal: auxiliary windows backfill
    # -----------------------------------------------------------------

    def _backfill_auxiliary_windows(self) -> None:
        """对已主验证但缺 1 日/20 日辅助字段的记录补全。

        策略：查询 20 日窗口已到、verified_at 非空、但 return_20d_pct 为 NULL 的记录。
        get_pending_verifications 过滤 verified_at IS NULL，无法复用，
        因此直接走 repository 的底层查询。
        """
        try:
            db = DatabaseManager.get_instance()
            cutoff_20d = datetime.now() - timedelta(days=_20D_WINDOW_DAYS)

            with db.session_scope() as session:
                from src.agent.reflection.models import DecisionLog as _DL

                rows = (
                    session.query(_DL)
                    .filter(
                        _DL.created_at <= cutoff_20d,
                        _DL.verified_at.isnot(None),
                        _DL.return_20d_pct.is_(None),
                    )
                    .order_by(_DL.created_at.asc())
                    .limit(_BATCH_LIMIT)
                    .all()
                )

                if not rows:
                    return

                logger.info(
                    "[DecisionTracker] 补全 %d 条辅助窗口字段", len(rows)
                )

                for decision in rows:
                    try:
                        self._backfill_single(session, decision)
                    except Exception as exc:
                        logger.debug(
                            "[DecisionTracker] 补全失败 decision_id=%s: %s",
                            decision.id,
                            exc,
                        )
                session.commit()
        except Exception as exc:
            logger.warning(
                "[DecisionTracker] _backfill_auxiliary_windows 失败: %s", exc
            )

    def _backfill_single(self, session, decision: DecisionLog) -> None:
        """补全单条记录的 1 日/20 日辅助字段。"""
        if not decision.stock_code or not decision.created_at:
            return

        decision_date = decision.created_at.date()
        end_date = decision_date + timedelta(days=_20D_WINDOW_DAYS * 2)
        prices = self._fetch_prices(decision.stock_code, decision_date, end_date)
        if len(prices) < 2:
            return

        entry_price = prices[0].close
        if entry_price <= 0:
            return

        if decision.return_1d_pct is None and len(prices) >= 2:
            decision.return_1d_pct = round(
                (prices[1].close - entry_price) / entry_price * 100.0, 4
            )

        if decision.return_20d_pct is None:
            idx_20d = min(_20D_WINDOW_DAYS, len(prices) - 1)
            if idx_20d > 0:
                decision.return_20d_pct = round(
                    (prices[idx_20d].close - entry_price) / entry_price * 100.0, 4
                )

    # -----------------------------------------------------------------
    # Internal: price lookup
    # -----------------------------------------------------------------

    def _fetch_prices(self, stock_code: str, start_date: date, end_date: date):
        """从 StockDaily 表查询日期范围内的日线数据（按日期升序）。"""
        db = DatabaseManager.get_instance()
        return db.get_data_range(stock_code, start_date, end_date)

    # -----------------------------------------------------------------
    # Internal: classification helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _classify_direction(return_pct: float) -> str:
        """分类实际方向：up/down/flat。阈值 ±0.5%。"""
        if return_pct > 0.5:
            return "up"
        if return_pct < -0.5:
            return "down"
        return "flat"

    @staticmethod
    def _compute_deviation(signal: str, return_pct: float) -> float:
        """计算偏差分 [-1, 1]，0 = 完全准确。

        - buy/strong_buy: 偏差 = +return_pct / 100（涨得越多越准，最大 1.0）
        - sell/strong_sell: 偏差 = -return_pct / 100（跌得越多越准）
        - hold: 偏差 = -|return_pct| / 100（不涨不跌最准）
        """
        normalized = return_pct / 100.0
        sig = (signal or "").strip().lower()
        if sig in ("buy", "strong_buy"):
            return max(-1.0, min(1.0, normalized))
        if sig in ("sell", "strong_sell"):
            return max(-1.0, min(1.0, -normalized))
        # hold or unknown
        return max(-1.0, min(1.0, -abs(normalized)))

    @staticmethod
    def _classify_outcome(signal: str, return_pct: float) -> str:
        """分类胜负：win/loss/neutral。阈值 ±2%。"""
        sig = (signal or "").strip().lower()
        threshold = _OUTCOME_THRESHOLD_PCT

        if sig in ("buy", "strong_buy"):
            if return_pct >= threshold:
                return "win"
            if return_pct <= -threshold:
                return "loss"
            return "neutral"

        if sig in ("sell", "strong_sell"):
            if return_pct <= -threshold:
                return "win"
            if return_pct >= threshold:
                return "loss"
            return "neutral"

        # hold: |return| < 2% → win（预测不动且确实没动）
        if abs(return_pct) < threshold:
            return "win"
        return "neutral"
