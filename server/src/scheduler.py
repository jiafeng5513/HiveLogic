# -*- coding: utf-8 -*-
"""
===================================
定时调度模块
===================================

职责：
1. 支持每日定时执行股票分析
2. 支持定时执行大盘复盘
3. 优雅处理信号，确保可靠退出
4. 支持多个命名每日任务（各自独立触发时间）+ 漏跑自愈（catch-up）

依赖：
- schedule: 轻量级定时任务库
"""

import logging
import os
import re
import signal
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_DEFAULT_DB = os.path.join(_DEFAULT_CACHE_DIR, "market_cache.db")


class GracefulShutdown:
    """
    优雅退出处理器

    捕获 SIGTERM/SIGINT 信号，确保任务完成后再退出
    """

    def __init__(self):
        self.shutdown_requested = False
        self._lock = threading.Lock()

        # 注册信号处理器
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """信号处理函数"""
        with self._lock:
            if not self.shutdown_requested:
                logger.info(f"收到退出信号 ({signum})，等待当前任务完成...")
                self.shutdown_requested = True

    @property
    def should_shutdown(self) -> bool:
        """检查是否应该退出"""
        with self._lock:
            return self.shutdown_requested


class Scheduler:
    """
    定时任务调度器

    基于 schedule 库实现，支持：
    - 每日定时执行
    - 启动时立即执行
    - 优雅退出
    """

    def __init__(
        self,
        schedule_time: str = "18:00",
        schedule_time_provider: Optional[Callable[[], str]] = None,
        db_path: str = _DEFAULT_DB,
    ):
        """
        初始化调度器

        Args:
            schedule_time: 每日执行时间，格式 "HH:MM"
            db_path: scheduler_task_log 表所在 SQLite 路径
        """
        try:
            import schedule
            self.schedule = schedule
        except ImportError:
            logger.error("schedule 库未安装，请执行: pip install schedule")
            raise ImportError("请安装 schedule 库: pip install schedule")

        self.schedule_time = schedule_time
        self._schedule_time_provider = schedule_time_provider
        self.shutdown_handler = GracefulShutdown()
        self._task_callback: Optional[Callable] = None
        self._daily_job: Optional[Any] = None
        self._background_tasks: List[Dict[str, Any]] = []
        self._named_jobs: Dict[str, Dict[str, Any]] = {}
        self._db_path = db_path
        self._db_lock = threading.Lock()
        self._running = False
        self._bg_thread: Optional[threading.Thread] = None
        self._init_task_log_table()

    def _init_task_log_table(self):
        """初始化 scheduler_task_log 表（记录每个命名任务的最近成功时间，供 catch-up 判断）"""
        try:
            os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
            with self._get_conn() as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS scheduler_task_log (
                        task_name       TEXT PRIMARY KEY,
                        last_success_at REAL NOT NULL,
                        last_duration   REAL DEFAULT 0,
                        last_count      INTEGER DEFAULT 0,
                        last_error      TEXT DEFAULT '',
                        last_run_at     REAL DEFAULT 0
                    );
                """)
        except sqlite3.Error as e:
            logger.warning("[Scheduler] 初始化 task_log 表失败: %s", e)

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _record_task_success(self, task_name: str, duration: float, count: int = 0):
        """记录任务成功（catch-up 依据）"""
        now = time.time()
        with self._db_lock:
            try:
                with self._get_conn() as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO scheduler_task_log
                           (task_name, last_success_at, last_duration, last_count, last_error, last_run_at)
                           VALUES (?, ?, ?, ?, '', ?)""",
                        (task_name, now, duration, count, now),
                    )
            except sqlite3.Error as e:
                logger.warning("[Scheduler] 记录任务成功 %s 失败: %s", task_name, e)

    def _record_task_failure(self, task_name: str, error: str):
        """记录任务失败（仅更新 last_error + last_run_at，不更新 last_success_at）"""
        now = time.time()
        with self._db_lock:
            try:
                with self._get_conn() as conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO scheduler_task_log
                           (task_name, last_success_at, last_duration, last_count, last_error, last_run_at)
                           VALUES (
                               ?,
                               COALESCE((SELECT last_success_at FROM scheduler_task_log WHERE task_name = ?), 0),
                               COALESCE((SELECT last_duration FROM scheduler_task_log WHERE task_name = ?), 0),
                               COALESCE((SELECT last_count FROM scheduler_task_log WHERE task_name = ?), 0),
                               ?,
                               ?
                           )""",
                        (task_name, task_name, task_name, task_name, error[:500], now),
                    )
            except sqlite3.Error as e:
                logger.warning("[Scheduler] 记录任务失败 %s 失败: %s", task_name, e)

    def _get_last_success(self, task_name: str) -> Optional[float]:
        """获取任务最近成功时间戳，无记录返回 None"""
        with self._db_lock:
            try:
                with self._get_conn() as conn:
                    row = conn.execute(
                        "SELECT last_success_at FROM scheduler_task_log WHERE task_name = ?",
                        (task_name,),
                    ).fetchone()
                    return row["last_success_at"] if row else None
            except sqlite3.Error:
                return None

    def get_task_status(self) -> List[Dict[str, Any]]:
        """获取所有命名任务的状态（供管理面板展示）"""
        with self._db_lock:
            try:
                with self._get_conn() as conn:
                    rows = conn.execute(
                        "SELECT task_name, last_success_at, last_duration, last_count, last_error, last_run_at FROM scheduler_task_log ORDER BY task_name"
                    ).fetchall()
                    return [dict(r) for r in rows]
            except sqlite3.Error as e:
                logger.warning("[Scheduler] 读取任务状态失败: %s", e)
                return []

    def set_daily_task(self, task: Callable, run_immediately: bool = True):
        """
        设置每日定时任务

        Args:
            task: 要执行的任务函数（无参数）
            run_immediately: 是否在设置后立即执行一次
        """
        self._task_callback = task
        if not self._configure_daily_task(self.schedule_time):
            raise ValueError(f"无效的定时执行时间: {self.schedule_time!r}")

        if run_immediately:
            logger.info("立即执行一次任务...")
            self._safe_run_task()

    @staticmethod
    def _is_valid_schedule_time(schedule_time: str) -> bool:
        """Validate time string in HH:MM 24-hour format."""
        candidate = (schedule_time or "").strip()
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", candidate):
            return False
        return True

    def _cancel_daily_job(self) -> None:
        """Remove the currently registered daily job if one exists."""
        if self._daily_job is None:
            return

        if hasattr(self.schedule, "cancel_job"):
            self.schedule.cancel_job(self._daily_job)
        else:  # pragma: no cover - compatibility fallback
            jobs = getattr(self.schedule, "jobs", None)
            if isinstance(jobs, list) and self._daily_job in jobs:
                jobs.remove(self._daily_job)

        self._daily_job = None

    def _configure_daily_task(self, schedule_time: str) -> bool:
        """(Re)register the daily job at the requested time."""
        candidate = (schedule_time or "").strip()
        if not self._is_valid_schedule_time(candidate):
            logger.warning(
                "检测到无效的定时执行时间 %r，继续沿用当前时间 %s",
                schedule_time,
                self.schedule_time,
            )
            return False

        previous_time = self.schedule_time
        self._cancel_daily_job()
        self._daily_job = self.schedule.every().day.at(candidate).do(self._safe_run_task)
        self.schedule_time = candidate

        if previous_time == candidate:
            logger.info("已设置每日定时任务，执行时间: %s", self.schedule_time)
        else:
            logger.info(
                "检测到 SCHEDULE_TIME 变更，已将每日定时任务从 %s 更新为 %s",
                previous_time,
                self.schedule_time,
            )
        return True

    def _refresh_daily_schedule_if_needed(self) -> None:
        """Reload daily schedule time from the latest runtime config if needed."""
        if self._task_callback is None or self._schedule_time_provider is None:
            return

        try:
            latest_schedule_time = (self._schedule_time_provider() or "").strip()
        except Exception as exc:  # pragma: no cover - defensive branch
            logger.warning("读取最新 SCHEDULE_TIME 失败，继续沿用 %s: %s", self.schedule_time, exc)
            return

        if not latest_schedule_time or latest_schedule_time == self.schedule_time:
            return

        if self._configure_daily_task(latest_schedule_time):
            logger.info("更新后的下次执行时间: %s", self._get_next_run_time())

    def _safe_run_task(self):
        """安全执行任务（带异常捕获）"""
        if self._task_callback is None:
            return

        try:
            logger.info("=" * 50)
            logger.info(f"定时任务开始执行 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info("=" * 50)

            self._task_callback()

            logger.info(f"定时任务执行完成 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        except Exception as e:
            logger.exception(f"定时任务执行失败: {e}")

    # ==================== 命名每日任务（多任务 + catch-up） ====================

    def add_named_daily_task(
        self,
        name: str,
        schedule_time: str,
        task: Callable,
        run_catchup_on_start: bool = True,
    ) -> bool:
        """
        注册一个命名的每日定时任务。每个任务独立配置触发时间，互不干扰。

        Args:
            name: 任务唯一名称（用于 catch-up 追踪与状态查询）
            schedule_time: 触发时间 "HH:MM"（24小时制）
            task: 无参任务函数
            run_catchup_on_start: 若 True，调度器启动时检查该任务今天是否应跑未跑，若是则补跑

        Returns:
            True 表示注册成功
        """
        if not self._is_valid_schedule_time(schedule_time):
            logger.warning("[Scheduler] 命名任务 %s 时间无效: %r", name, schedule_time)
            return False

        if name in self._named_jobs:
            self._cancel_named_job(name)

        job = self.schedule.every().day.at(schedule_time).do(
            self._safe_run_named_task, name=name
        )
        self._named_jobs[name] = {
            "job": job,
            "time": schedule_time,
            "task": task,
            "run_catchup_on_start": run_catchup_on_start,
        }
        logger.info("[Scheduler] 已注册命名任务: %s @ %s", name, schedule_time)
        return True

    def _cancel_named_job(self, name: str):
        """取消一个命名任务"""
        entry = self._named_jobs.pop(name, None)
        if not entry:
            return
        job = entry["job"]
        if hasattr(self.schedule, "cancel_job"):
            self.schedule.cancel_job(job)
        else:
            jobs = getattr(self.schedule, "jobs", None)
            if isinstance(jobs, list) and job in jobs:
                jobs.remove(job)

    def _safe_run_named_task(self, name: str):
        """安全执行命名任务（带异常捕获 + 成功/失败记录）"""
        entry = self._named_jobs.get(name)
        if not entry:
            logger.warning("[Scheduler] 命名任务 %s 未注册", name)
            return
        task = entry["task"]
        start = time.time()
        try:
            logger.info("=" * 50)
            logger.info("[Scheduler] 命名任务 %s 开始 - %s", name, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            result = task()
            duration = time.time() - start
            count = result if isinstance(result, int) else 0
            self._record_task_success(name, duration, count)
            logger.info("[Scheduler] 命名任务 %s 完成 (%.1fs)", name, duration)
        except Exception as e:
            self._record_task_failure(name, str(e))
            logger.exception("[Scheduler] 命名任务 %s 失败: %s", name, e)

    def run_catch_up(self):
        """
        补跑漏跑任务。对每个命名任务：
          1. 读取 last_success_at（上次成功时间戳）
          2. 计算今天该任务的触发时间戳
          3. 若 now >= 今天触发时间 且 last_success_at < 今天触发时间，说明今天应跑未跑，补跑
          4. 若 last_success_at 为 None（从未跑过），也补跑一次
        幂等保证：任务自身必须做 upsert（如 kline_data 的 UNIQUE 约束），重复跑不会产生脏数据。
        """
        now = time.time()
        today = datetime.now().strftime("%Y-%m-%d")
        for name, entry in self._named_jobs.items():
            if not entry.get("run_catchup_on_start"):
                continue
            schedule_time = entry["time"]
            today_trigger_str = f"{today} {schedule_time}"
            try:
                today_trigger_ts = datetime.strptime(today_trigger_str, "%Y-%m-%d %H:%M").timestamp()
            except ValueError:
                continue
            if now < today_trigger_ts:
                logger.debug("[Scheduler] catch-up: %s 今天触发时间未到 (%s)", name, today_trigger_str)
                continue
            last_success = self._get_last_success(name)
            if last_success is None:
                logger.info("[Scheduler] catch-up: %s 从未运行过，立即补跑", name)
            elif last_success < today_trigger_ts:
                logger.info(
                    "[Scheduler] catch-up: %s 上次成功于 %s，今天触发 %s 未跑，补跑",
                    name,
                    datetime.fromtimestamp(last_success).strftime("%Y-%m-%d %H:%M:%S"),
                    today_trigger_str,
                )
            else:
                continue
            self._safe_run_named_task(name)

    def add_background_task(
        self,
        task: Callable,
        interval_seconds: int,
        run_immediately: bool = False,
        name: Optional[str] = None,
    ) -> None:
        """Register a periodic background task executed inside the scheduler loop.

        Note: The scheduler loop polls every 30 seconds, so *interval_seconds*
        below 30 will be clamped to 30 to avoid promising unreachable precision.
        """
        clamped_interval = max(30, int(interval_seconds))
        if int(interval_seconds) < 30:
            logger.warning(
                "后台任务 %s 请求间隔 %ds，但调度循环每 30s 轮询一次，已自动调整为 30s",
                name or getattr(task, "__name__", "background_task"),
                interval_seconds,
            )
        entry = {
            "task": task,
            "interval_seconds": clamped_interval,
            "last_run": 0.0,
            "name": name or getattr(task, "__name__", "background_task"),
            "thread": None,
            "running": False,
        }
        if not run_immediately:
            entry["last_run"] = time.time()
        self._background_tasks.append(entry)
        logger.info(
            "已注册后台任务: %s（间隔 %s 秒，立即执行=%s）",
            entry["name"],
            entry["interval_seconds"],
            run_immediately,
        )
        if run_immediately:
            self._start_background_task(entry)

    def _start_background_task(self, entry: Dict[str, Any]) -> bool:
        """Start one background task in a dedicated daemon thread."""
        worker = entry.get("thread")
        if worker is not None and worker.is_alive():
            return False

        def _runner() -> None:
            try:
                logger.info("后台任务开始执行: %s", entry["name"])
                entry["task"]()
            except Exception as exc:
                logger.exception("后台任务执行失败 [%s]: %s", entry["name"], exc)
            finally:
                entry["running"] = False
                entry["thread"] = None

        entry["last_run"] = time.time()
        entry["running"] = True
        worker = threading.Thread(
            target=_runner,
            daemon=True,
            name=f"scheduler-bg-{entry['name']}",
        )
        entry["thread"] = worker
        worker.start()
        return True

    def _run_background_tasks(self) -> None:
        """Execute any background tasks whose interval has elapsed."""
        if not self._background_tasks:
            return

        now = time.time()
        for entry in self._background_tasks:
            worker = entry.get("thread")
            if worker is not None and worker.is_alive():
                continue
            if entry.get("running"):
                entry["running"] = False
                entry["thread"] = None
            if now - entry["last_run"] < entry["interval_seconds"]:
                continue
            self._start_background_task(entry)

    def run(self):
        """
        运行调度器主循环

        阻塞运行，直到收到退出信号
        """
        self._running = True
        logger.info("调度器开始运行...")
        logger.info(f"下次执行时间: {self._get_next_run_time()}")

        while self._running and not self.shutdown_handler.should_shutdown:
            self._refresh_daily_schedule_if_needed()
            self.schedule.run_pending()
            self._run_background_tasks()
            time.sleep(30)  # 每30秒检查一次

            # 每小时打印一次心跳
            if datetime.now().minute == 0 and datetime.now().second < 30:
                logger.info(f"调度器运行中... 下次执行: {self._get_next_run_time()}")

        logger.info("调度器已停止")

    def run_in_background(self, run_catchup: bool = True) -> bool:
        """
        在后台 daemon 线程中启动调度器主循环（供 FastAPI lifespan 调用）。

        Args:
            run_catchup: 启动前是否先执行一次 catch-up 补跑漏跑任务

        Returns:
            True 表示已启动（或已在运行）
        """
        if self._running:
            return True
        if run_catchup:
            try:
                self.run_catch_up()
            except Exception as e:
                logger.exception("[Scheduler] catch-up 执行失败: %s", e)
        self._bg_thread = threading.Thread(
            target=self.run,
            daemon=True,
            name="hivelogic-scheduler",
        )
        self._bg_thread.start()
        logger.info("[Scheduler] 已在后台线程启动")
        return True

    def _get_next_run_time(self) -> str:
        """获取下次执行时间"""
        jobs = self.schedule.get_jobs()
        if jobs:
            next_run = min(job.next_run for job in jobs)
            return next_run.strftime('%Y-%m-%d %H:%M:%S')
        return "未设置"

    def stop(self):
        """停止调度器"""
        self._running = False


def run_with_schedule(
    task: Callable,
    schedule_time: str = "18:00",
    run_immediately: bool = True,
    background_tasks: Optional[List[Dict[str, Any]]] = None,
    schedule_time_provider: Optional[Callable[[], str]] = None,
):
    """
    便捷函数：使用定时调度运行任务

    Args:
        task: 要执行的任务函数
        schedule_time: 每日执行时间
        run_immediately: 是否立即执行一次
        background_tasks: 可选的后台任务定义列表。每项为一个字典，
            需包含 `task` 与 `interval_seconds`，可选包含 `name`
            和 `run_immediately`。`interval_seconds` 单位为秒。
        schedule_time_provider: 可选的时间提供器；调度器每轮检查前会读取，
            当返回值变化时自动重建 daily job。
    """
    scheduler = Scheduler(
        schedule_time=schedule_time,
        schedule_time_provider=schedule_time_provider,
    )
    for entry in background_tasks or []:
        scheduler.add_background_task(
            task=entry["task"],
            interval_seconds=entry["interval_seconds"],
            run_immediately=entry.get("run_immediately", False),
            name=entry.get("name"),
        )
    scheduler.set_daily_task(task, run_immediately=run_immediately)
    scheduler.run()


if __name__ == "__main__":
    # 测试定时调度
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
    )

    def test_task():
        print(f"任务执行中... {datetime.now()}")
        time.sleep(2)
        print("任务完成!")

    print("启动测试调度器（按 Ctrl+C 退出）")
    run_with_schedule(test_task, schedule_time="23:59", run_immediately=True)
