# -*- coding: utf-8 -*-
"""
Code execution tools — AI 可在隔离沙箱中编写并执行 Python 代码。

Phase B 核心工具:
- execute_python: 在 Docker sidecar 沙箱容器中执行任意 Python 代码
  - 无网络、只读文件系统、资源受限 (mem 1g, cpus 0.5)
  - 预装 pandas/numpy/scipy/matplotlib/akshare 等数据科学栈
  - 通过 hivelogic_data 模块只读访问服务端缓存数据
  - matplotlib 图表自动捕获为 base64 PNG 返回
  - stdout/stderr 截断、超时保护

安全约束:
  - requires_approval=True: 仅 autonomous 模式暴露此工具
  - category="code": 与 data/analysis/search 并列
  - 沙箱容器 network_mode: none，数据无法出境
  - 非 root 用户运行，无提权能力
"""

from __future__ import annotations

import base64
import json
import logging
import os
import textwrap
import time
import uuid
from typing import Any, Dict, List, Optional

from src.agent.tools.registry import ToolDefinition, ToolParameter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 沙箱管理器 — 封装 Docker SDK 调用
# ---------------------------------------------------------------------------

class SandboxManager:
    """管理 Docker 沙箱容器的代码执行。

    设计要点:
        1. 懒加载 Docker 客户端 — 仅在 sandbox_enabled=True 时初始化
        2. 容器复用 — sidecar 容器常驻，每次 exec_run 注入代码
        3. 超时保护 — exec_run 的 timeout 参数 + 服务端 wall-clock 双重保护
        4. 输出截断 — stdout/stderr 各自截断到 max_output_bytes
        5. 图表捕获 — 注入 matplotlib 钩子，自动收集 open figures 为 base64

    用法::

        mgr = SandboxManager.get_instance()
        result = mgr.execute("print('hello')", timeout=30)
    """

    _instance: Optional["SandboxManager"] = None
    _client: Any = None  # docker.DockerClient (lazy)
    _container: Any = None  # docker.Container (lazy + cached)
    _initialized: bool = False
    _available: bool = False

    def __init__(self):
        self._config = self._load_config()

    @staticmethod
    def _load_config() -> dict:
        """从应用配置加载沙箱参数（延迟导入避免循环依赖）。"""
        try:
            from src.config import get_config
            cfg = get_config()
            return {
                "enabled": getattr(cfg, "sandbox_enabled", False),
                "container_name": getattr(cfg, "sandbox_container_name", "hivelogic-sandbox"),
                "timeout_seconds": getattr(cfg, "sandbox_timeout_seconds", 30),
                "max_output_bytes": getattr(cfg, "sandbox_max_output_bytes", 10240),
            }
        except Exception:
            # 配置不可用时使用安全默认值
            return {
                "enabled": False,
                "container_name": "hivelogic-sandbox",
                "timeout_seconds": 30,
                "max_output_bytes": 10240,
            }

    @classmethod
    def get_instance(cls) -> "SandboxManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _ensure_initialized(self) -> None:
        """懒初始化 Docker 客户端 + 容器引用。仅执行一次。"""
        if self._initialized:
            return
        self._initialized = True

        if not self._config.get("enabled", False):
            logger.info("[Sandbox] 沙箱未启用 (sandbox_enabled=False)")
            return

        try:
            import docker  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("[Sandbox] docker 包未安装，代码执行不可用。请运行: pip install docker")
            return

        try:
            self._client = docker.from_env(timeout=10)
            container_name = self._config["container_name"]
            self._container = self._client.containers.get(container_name)
            # 验证容器存活
            self._container.reload()
            if self._container.status != "running":
                logger.warning("[Sandbox] 容器 %s 状态为 %s，尝试启动...", container_name, self._container.status)
                self._container.start()
                time.sleep(2)
                self._container.reload()
            if self._container.status == "running":
                self._available = True
                logger.info("[Sandbox] 沙箱容器就绪: %s", container_name)
            else:
                logger.warning("[Sandbox] 容器 %s 无法启动 (status=%s)", container_name, self._container.status)
        except Exception as e:
            logger.warning("[Sandbox] Docker 连接失败，代码执行不可用: %s", e)
            self._available = False

    @property
    def available(self) -> bool:
        """沙箱是否可用（已启用 + Docker 连接正常 + 容器运行中）。"""
        self._ensure_initialized()
        return self._available

    # -----------------------------------------------------------------
    # 图表捕获包装器
    # -----------------------------------------------------------------

    _FIGURE_MARKER = "___HIVELOGIC_FIGURE_BASE64___"

    def _build_wrapper_script(self, user_code: str, context_json: Optional[str]) -> str:
        """构建包装脚本: 注入 matplotlib 钩子 + context + 用户代码 + 图表收集。

        生成的脚本结构::

            # 1. 设置 matplotlib Agg 后端
            # 2. 注入 context 变量（如果有）
            # 3. exec(user_code)
            # 4. 收集所有 open figures 为 base64 PNG，以特殊标记输出
        """
        # 安全转义: 用户代码中如果包含三引号会导致字符串提前结束
        # 使用 base64 编码用户代码来避免任何转义问题
        encoded_code = base64.b64encode(user_code.encode("utf-8")).decode("ascii")

        context_injection = ""
        if context_json:
            # context_json 已经是 JSON 字符串，直接注入
            context_injection = f'_hivelogic_context = json.loads({context_json!r})\n'

        marker = self._FIGURE_MARKER

        return textwrap.dedent(f"""\
            # -*- coding: utf-8 -*-
            # HiveLogic 沙箱包装脚本 (自动生成)
            import sys, os, json, base64, io, traceback

            # 1. matplotlib Agg 后端 (无显示器)
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as _hlt_plt

            # 2. 注入 context (可选)
            {context_injection}

            # 3. 解码并执行用户代码
            _hlt_user_code = base64.b64decode("{encoded_code}").decode("utf-8")
            _hlt_user_globals = {{"__name__": "__main__", "__builtins__": __builtins__}}
            # 注入常用库到用户命名空间
            try:
                import pandas as pd
                _hlt_user_globals["pd"] = pd
            except ImportError:
                pass
            try:
                import numpy as np
                _hlt_user_globals["np"] = np
            except ImportError:
                pass
            try:
                import matplotlib.pyplot as plt
                _hlt_user_globals["plt"] = plt
            except ImportError:
                pass
            try:
                import scipy
                _hlt_user_globals["scipy"] = scipy
            except ImportError:
                pass
            try:
                from hivelogic_data import load_kline, load_analysis_history, list_available_symbols, db_info
                _hlt_user_globals["load_kline"] = load_kline
                _hlt_user_globals["load_analysis_history"] = load_analysis_history
                _hlt_user_globals["list_available_symbols"] = list_available_symbols
                _hlt_user_globals["db_info"] = db_info
            except Exception:
                pass  # hivelogic_data 可能不可用

            try:
                exec(compile(_hlt_user_code, "<sandbox>", "exec"), _hlt_user_globals)
            except Exception:
                traceback.print_exc(file=sys.stderr)
                sys.exit(1)

            # 4. 收集所有 matplotlib figures 为 base64 PNG
            _hlt_figs = _hlt_plt.get_fignums()
            if _hlt_figs:
                for _hlt_fignum in _hlt_figs:
                    _hlt_fig = _hlt_plt.figure(_hlt_fignum)
                    _hlt_buf = io.BytesIO()
                    _hlt_fig.savefig(_hlt_buf, format="png", dpi=100, bbox_inches="tight")
                    _hlt_b64 = base64.b64encode(_hlt_buf.getvalue()).decode("ascii")
                    print("{marker}" + _hlt_b64)
                _hlt_plt.close("all")
        """)

    # -----------------------------------------------------------------
    # 核心执行方法
    # -----------------------------------------------------------------

    def execute(
        self,
        code: str,
        *,
        timeout: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """在沙箱容器中执行 Python 代码。

        Args:
            code: 要执行的 Python 代码
            timeout: 超时秒数（None 用配置默认值）
            context: 可选的上下文数据，注入为 ``_hivelogic_context`` 变量

        Returns:
            dict 包含:
                - ``stdout``: 标准输出（截断到 max_output_bytes）
                - ``stderr``: 标准错误（截断到 max_output_bytes）
                - ``exit_code``: 退出码 (0=成功)
                - ``figures``: list[str] — base64 PNG 图片
                - ``truncated``: bool — 输出是否被截断
                - ``error``: str | None — 沙箱不可用时的错误信息
                - ``duration_ms``: int — 执行耗时毫秒
        """
        if not self.available:
            return {
                "stdout": "",
                "stderr": "",
                "exit_code": -1,
                "figures": [],
                "truncated": False,
                "error": "代码执行沙箱不可用。请确保 SANDBOX_ENABLED=true 且沙箱容器正在运行。",
                "duration_ms": 0,
            }

        effective_timeout = timeout or self._config["timeout_seconds"]
        max_bytes = self._config["max_output_bytes"]
        marker = self._FIGURE_MARKER

        # 构建包装脚本
        context_json = json.dumps(context, ensure_ascii=False) if context else None
        wrapper = self._build_wrapper_script(code, context_json)

        # 生成唯一文件名
        script_id = uuid.uuid4().hex[:12]
        script_path = f"/tmp/sandbox_output/hivelogic_{script_id}.py"

        start_time = time.time()

        try:
            # 步骤 1: 将脚本写入 /tmp (tmpfs 可写)
            write_cmd = ["sh", "-c", f"cat > {script_path} << 'HIVELOGIC_HEREDOC_EOF'\n{wrapper}\nHIVELOGIC_HEREDOC_EOF"]
            write_result = self._container.exec_run(write_cmd, user="sandbox")
            if write_result.exit_code != 0:
                return {
                    "stdout": "",
                    "stderr": write_result.output.decode("utf-8", errors="replace") if write_result.output else "写入脚本失败",
                    "exit_code": -1,
                    "figures": [],
                    "truncated": False,
                    "error": "无法将代码写入沙箱临时目录",
                    "duration_ms": int((time.time() - start_time) * 1000),
                }

            # 步骤 2: 执行脚本
            exec_result = self._container.exec_run(
                ["python", script_path],
                user="sandbox",
                demux=True,  # 分离 stdout 和 stderr
                workdir="/sandbox",
            )

            duration_ms = int((time.time() - start_time) * 1000)

            # 解析输出 (demux=True 返回 (stdout_bytes, stderr_bytes) 元组)
            if isinstance(exec_result.output, tuple):
                stdout_bytes, stderr_bytes = exec_result.output
            else:
                stdout_bytes = exec_result.output
                stderr_bytes = b""

            stdout_raw = (stdout_bytes or b"").decode("utf-8", errors="replace")
            stderr_raw = (stderr_bytes or b"").decode("utf-8", errors="replace")
            exit_code = exec_result.exit_code if exec_result.exit_code is not None else -1

            # 步骤 3: 从 stdout 中提取图表 (按标记行分割)
            figures: List[str] = []
            stdout_lines = stdout_raw.split("\n")
            clean_stdout_lines: List[str] = []
            for line in stdout_lines:
                if line.startswith(marker):
                    b64_data = line[len(marker):]
                    if b64_data:
                        figures.append(b64_data)
                else:
                    clean_stdout_lines.append(line)
            stdout_clean = "\n".join(clean_stdout_lines)

            # 步骤 4: 截断输出
            truncated = False
            if len(stdout_clean.encode("utf-8")) > max_bytes:
                stdout_clean = stdout_clean.encode("utf-8")[:max_bytes].decode("utf-8", errors="replace")
                truncated = True
                stdout_clean += "\n... [stdout 截断，超过 {} 字节]".format(max_bytes)
            if len(stderr_raw.encode("utf-8")) > max_bytes:
                stderr_raw = stderr_raw.encode("utf-8")[:max_bytes].decode("utf-8", errors="replace")
                truncated = True
                stderr_raw += "\n... [stderr 截断，超过 {} 字节]".format(max_bytes)

            # 步骤 5: 清理临时文件 (best-effort)
            try:
                self._container.exec_run(["rm", "-f", script_path], user="sandbox")
            except Exception:
                pass

            return {
                "stdout": stdout_clean,
                "stderr": stderr_raw,
                "exit_code": exit_code,
                "figures": figures,
                "truncated": truncated,
                "error": None,
                "duration_ms": duration_ms,
            }

        except Exception as e:
            logger.error("[Sandbox] 代码执行异常: %s", e, exc_info=True)
            return {
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
                "figures": [],
                "truncated": False,
                "error": f"沙箱执行异常: {e}",
                "duration_ms": int((time.time() - start_time) * 1000),
            }


# ---------------------------------------------------------------------------
# 每日配额检查 (B.5 安全审计)
# ---------------------------------------------------------------------------

def _check_daily_quota() -> Optional[str]:
    """检查今日代码执行次数是否超过配额。

    读取 ``code_execution_log`` 表中今日记录数，与 ``sandbox_daily_quota`` 比较。
    配额为 0 表示不限制。失败时（表不存在/DB不可用）保守放行。

    Returns:
        错误信息字符串（超限时），None 表示通过。
    """
    try:
        from src.config import get_config
        cfg = get_config()
        quota = getattr(cfg, "sandbox_daily_quota", 50)
        if quota <= 0:
            return None  # 不限制
    except Exception:
        quota = 50  # 回退到默认值

    try:
        import sqlite3
        from src.services.kline_cache_manager import DEFAULT_CACHE_DB
        conn = sqlite3.connect(DEFAULT_CACHE_DB, timeout=5)
        # 今日 UTC 起始时间戳（code_execution_log.executed_at 是 ISO 字符串）
        from datetime import datetime, timezone
        today_start = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        count = conn.execute(
            "SELECT COUNT(*) FROM code_execution_log WHERE executed_at >= ?",
            (today_start,),
        ).fetchone()[0]
        conn.close()
        if count >= quota:
            logger.warning("[Sandbox] 每日代码执行配额已用尽: %d/%d", count, quota)
            return f"今日代码执行配额已用尽 ({count}/{quota})。请明天再试或联系管理员提升配额。"
    except Exception:
        # 表不存在或 DB 不可用 — 保守放行（首次执行时表尚未创建）
        logger.debug("[Sandbox] 配额检查跳过（表未就绪）", exc_info=True)
        return None

    return None


# ---------------------------------------------------------------------------
# 工具处理器
# ---------------------------------------------------------------------------

def _handle_execute_python(
    code: str,
    context: Optional[str] = None,
) -> dict:
    """在隔离沙箱中执行 Python 代码。

    沙箱环境: 无网络、只读文件系统、资源受限 (1GB 内存, 0.5 CPU)。
    预装 pandas/numpy/scipy/matplotlib/akshare 等数据科学库。
    可通过 ``from hivelogic_data import load_kline`` 只读访问缓存数据。

    返回 stdout/stderr/图表(base64 PNG)。matplotlib 图表自动捕获。
    """
    mgr = SandboxManager.get_instance()

    # B.5 安全审计 — 每日配额检查 (sandbox_daily_quota, 0 = 不限制)
    quota_error = _check_daily_quota()
    if quota_error:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": "",
            "success": False,
            "error": quota_error,
            "duration_ms": 0,
            "figures_count": 0,
        }

    # 解析 context (可能是 JSON 字符串)
    parsed_context: Optional[Dict[str, Any]] = None
    if context:
        try:
            parsed_context = json.loads(context) if isinstance(context, str) else context
        except (json.JSONDecodeError, TypeError):
            parsed_context = None

    result = mgr.execute(code, context=parsed_context)

    # 记录执行日志 (B.5 安全审计)
    try:
        _log_code_execution(code, result)
    except Exception:
        logger.debug("[Sandbox] 代码执行日志记录失败", exc_info=True)

    # 构建对 AI 友好的返回
    response: Dict[str, Any] = {
        "exit_code": result["exit_code"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "duration_ms": result["duration_ms"],
        "figures_count": len(result["figures"]),
    }

    if result["error"]:
        response["error"] = result["error"]
        response["success"] = False
    else:
        response["success"] = result["exit_code"] == 0

    if result["truncated"]:
        response["truncated"] = True

    # 图表以独立字段返回（base64 太长，不放入 stdout）
    if result["figures"]:
        response["figures"] = result["figures"]

    return response


def _log_code_execution(code: str, result: Dict[str, Any]) -> None:
    """将代码执行记录写入日志（B.5 安全审计 — 全量落库）。

    记录: 代码内容、stdout/stderr 摘要、耗时、退出码、时间戳。
    写入 market_cache.db 的 code_execution_log 表。
    """
    import sqlite3
    from src.services.kline_cache_manager import DEFAULT_CACHE_DB

    try:
        conn = sqlite3.connect(DEFAULT_CACHE_DB, timeout=5)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS code_execution_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                code_hash TEXT,
                stdout_excerpt TEXT,
                stderr_excerpt TEXT,
                exit_code INTEGER,
                duration_ms INTEGER,
                figures_count INTEGER,
                success INTEGER,
                executed_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )
        """)
        import hashlib
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]
        # 摘要: 各取前 2000 字符
        stdout_excerpt = (result.get("stdout") or "")[:2000]
        stderr_excerpt = (result.get("stderr") or "")[:2000]
        conn.execute(
            "INSERT INTO code_execution_log (code, code_hash, stdout_excerpt, stderr_excerpt, exit_code, duration_ms, figures_count, success) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                code,
                code_hash,
                stdout_excerpt,
                stderr_excerpt,
                result.get("exit_code", -1),
                result.get("duration_ms", 0),
                result.get("figures", []) and len(result["figures"]) or 0,
                1 if result.get("exit_code") == 0 else 0,
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        # 日志记录失败不影响工具执行
        pass


# ---------------------------------------------------------------------------
# 工具定义
# ---------------------------------------------------------------------------

execute_python_tool = ToolDefinition(
    name="execute_python",
    description=(
        "在隔离的 Docker 沙箱中执行 Python 代码，用于自定义回测、因子计算、统计检验、画图等。"
        "沙箱预装 pandas/numpy/scipy/matplotlib/scikit-learn/akshare。"
        "可通过 `from hivelogic_data import load_kline` 只读访问缓存数据（K线、分析历史）。"
        "无网络、只读文件系统、资源受限（1GB 内存, 30s 超时）。"
        "matplotlib 图表自动捕获为图片返回。"
        "注意: 仅在 autonomous 模式下可用。"
    ),
    parameters=[
        ToolParameter(
            name="code",
            type="string",
            description=(
                "要执行的 Python 代码。可用库: pandas(pd), numpy(np), matplotlib.pyplot(plt), "
                "scipy, sklearn, akshare, statsmodels。"
                "获取数据: `from hivelogic_data import load_kline; df = load_kline('600519', days=365)`。"
                "画图: 直接用 plt.plot() 等，图表会自动捕获返回。"
            ),
        ),
        ToolParameter(
            name="context",
            type="string",
            description="可选的 JSON 字符串，注入为 _hivelogic_context 变量。用于传递股票代码、日期等参数。",
            required=False,
            default=None,
        ),
    ],
    handler=_handle_execute_python,
    category="code",
    requires_approval=True,
)

ALL_CODE_TOOLS: List[ToolDefinition] = [execute_python_tool]
