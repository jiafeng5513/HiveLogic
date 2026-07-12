# -*- coding: utf-8 -*-
"""
AutonomousPlannerAgent — self-planning agent for the autonomous mode.

Unlike the fixed-pipeline agents (Technical → Intel → Risk → Decision),
this agent receives the full tool registry and **decides for itself**:
- Which tools to call and in what order
- When it has enough data to stop
- How to adjust its investigation path based on intermediate findings

Key design (Phase A.5 — two-phase tiered loop):
- **Phase 1 (Plan)**: A single REASONING-tier call (deepseek-reasoner) with
  *no tools* produces a structured investigation plan.  This is where the
  expensive reasoning model adds the most value — deciding *what* to look
  at before spending tool calls.
- **Phase 2 (Execute)**: ``run_agent_loop`` runs with the QUICK-tier model
  (``agent_name="autonomous_executor"``), with the plan injected into the
  message history.  The QUICK model handles tool calls, result parsing,
  and dynamic replanning — it's fast and cheap.

Observable (Phase A.4):
- ``plan_generated`` event emitted after Phase 1 with the structured plan.
- ``step_reasoning`` events emitted by ``run_agent_loop`` whenever the
  model returns ``reasoning_content`` (REASONING models only).
- The plan + step reasoning are stored in ``ctx`` for later persistence
  by the orchestrator's decision-logging path.

The ``post_process`` method mirrors ``DecisionAgent.post_process``: parses
the dashboard JSON and stores it in ``ctx`` so the orchestrator's
``_resolve_final_output`` can pick it up.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from src.agent.agents.base_agent import BaseAgent
from src.agent.protocols import AgentContext, AgentOpinion, StageResult, StageStatus, normalize_decision_signal
from src.agent.runner import RunLoopResult, parse_dashboard_json, run_agent_loop
from src.report_language import normalize_report_language
from src.market_context import get_market_role, get_market_guidelines

logger = logging.getLogger(__name__)


class AutonomousPlannerAgent(BaseAgent):
    """Self-planning agent that autonomously decides its investigation path.

    This agent replaces the entire fixed pipeline (technical → intel →
    risk → decision) with a two-phase loop:

    1. **Plan** — REASONING model produces a structured investigation plan.
    2. **Execute** — QUICK model executes the plan via ``run_agent_loop``,
       dynamically adjusting as data comes in.

    The system prompt is goal-oriented (no fixed stages), so the LLM
    can adapt its path — e.g. if it discovers a major risk signal early,
    it can skip deep technical analysis and go straight to a risk warning.
    """

    agent_name = "autonomous_planner"
    # Execution-phase agent name — maps to QUICK tier via DEFAULT_TIER_MAP.
    # Used so run_agent_loop calls the fast model for tool execution.
    executor_agent_name = "autonomous_executor"
    max_steps = 15  # Default; hard ceiling enforced by config / orchestrator
    tool_names = None  # Full tool access — autonomous mode needs every tool

    # ------------------------------------------------------------------
    # Prompt assembly
    # ------------------------------------------------------------------

    def system_prompt(self, ctx: AgentContext) -> str:
        """Build the autonomous system prompt with market context.

        This prompt is used for the **execution phase** (Phase 2).
        The planning phase uses ``_build_planning_prompt()`` instead.
        """
        from src.agent.executor import AUTONOMOUS_SYSTEM_PROMPT

        report_language = normalize_report_language(ctx.meta.get("report_language", "zh"))
        stock_code = ctx.stock_code or ""
        market_role = get_market_role(stock_code, report_language)
        market_guidelines = get_market_guidelines(stock_code, report_language)

        skills_section = ""
        if self.skill_instructions:
            skills_section = f"## 激活的交易技能\n\n{self.skill_instructions}"

        default_skill_policy_section = ""
        if self.technical_skill_policy:
            default_skill_policy_section = f"\n{self.technical_skill_policy}\n"

        language_section = _build_language_section(report_language)

        return AUTONOMOUS_SYSTEM_PROMPT.format(
            market_role=market_role,
            market_guidelines=market_guidelines,
            default_skill_policy_section=default_skill_policy_section,
            skills_section=skills_section,
            language_section=language_section,
        )

    def _build_planning_prompt(self, ctx: AgentContext) -> str:
        """Build the planning-phase system prompt (Phase 1, no tools)."""
        from src.agent.executor import AUTONOMOUS_PLANNING_PROMPT

        report_language = normalize_report_language(ctx.meta.get("report_language", "zh"))
        stock_code = ctx.stock_code or ""
        market_role = get_market_role(stock_code, report_language)
        market_guidelines = get_market_guidelines(stock_code, report_language)
        language_section = _build_language_section(report_language)

        return AUTONOMOUS_PLANNING_PROMPT.format(
            market_role=market_role,
            market_guidelines=market_guidelines,
            language_section=language_section,
        )

    def build_user_message(self, ctx: AgentContext) -> str:
        """Build the initial user message for the autonomous agent."""
        parts: list[str] = []

        query = ctx.query or ""
        if query:
            parts.append(query)

        if ctx.stock_code:
            parts.append(f"\n标的代码: {ctx.stock_code}")
        if ctx.stock_name:
            parts.append(f"标的名称: {ctx.stock_name}")

        report_language = normalize_report_language(ctx.meta.get("report_language", "zh"))
        if report_language == "en":
            parts.append("Output language: English (keep JSON keys unchanged; use English for all human-readable values)")
        else:
            parts.append("输出语言: 中文（所有 JSON 键名保持不变，所有面向用户的文本值使用中文）")

        parts.append(
            "\n你处于自主规划模式。请先思考调研计划，然后按需调用工具获取真实数据，"
            "最后输出完整的决策仪表盘 JSON。"
        )
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Two-phase execution (A.5: REASONING plan → QUICK execute)
    # ------------------------------------------------------------------

    def run(
        self,
        ctx: AgentContext,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> StageResult:
        """Execute the two-phase autonomous loop.

        Phase 1 — Plan (REASONING tier, no tools):
            Call ``call_text_tiered`` with ``agent_name="autonomous_planner"``
            to get a structured investigation plan from the reasoning model.

        Phase 2 — Execute (QUICK tier, full tools):
            Call ``run_agent_loop`` with ``agent_name="autonomous_executor"``
            to execute the plan, with the plan injected into messages.

        Falls back to single-phase (QUICK only) if planning fails.
        """
        t0 = time.time()
        result = StageResult(stage_name=self.agent_name, status=StageStatus.RUNNING)

        try:
            # === Phase 1: Planning (REASONING model, no tools) ===
            plan_text, plan_json, planning_reasoning = self._run_planning_phase(
                ctx, progress_callback, timeout_seconds
            )

            if plan_json:
                logger.info(
                    "[AutonomousPlanner] Plan generated: %d steps, estimated %s",
                    len(plan_json.get("investigation_steps", [])),
                    plan_json.get("estimated_steps", "?"),
                )
            else:
                logger.warning(
                    "[AutonomousPlanner] Planning phase failed to produce JSON, "
                    "falling back to single-phase execution"
                )

            # === Phase 2: Execution (QUICK model, full tools) ===
            # Wrap progress_callback to intercept step_reasoning events for persistence
            step_reasoning_trace: List[Dict[str, Any]] = []
            if planning_reasoning:
                step_reasoning_trace.append({
                    "step": 0,
                    "phase": "planning",
                    "content": planning_reasoning,
                })

            execution_callback = self._make_reasoning_capture_callback(
                progress_callback, step_reasoning_trace
            )

            loop_result = self._run_execution_phase(
                ctx, execution_callback, timeout_seconds, plan_text, plan_json
            )

            result.tokens_used = loop_result.total_tokens
            result.tool_calls_count = len(loop_result.tool_calls_log)
            result.meta["raw_text"] = loop_result.content
            result.meta["models_used"] = loop_result.models_used
            result.meta["tool_calls_log"] = loop_result.tool_calls_log

            # Store plan + reasoning trace for orchestrator persistence (A.4)
            if plan_json:
                ctx.set_data("autonomous_plan", plan_json)
            if plan_text:
                ctx.set_data("autonomous_plan_text", plan_text)
            if step_reasoning_trace:
                ctx.set_data("autonomous_step_reasoning", step_reasoning_trace)

            if not loop_result.success:
                result.status = StageStatus.FAILED
                result.error = loop_result.error or "Agent loop did not produce a final answer"
                return result

            # Post-process into structured opinion
            opinion = self.post_process(ctx, loop_result.content)
            if opinion is not None:
                opinion.agent_name = self.agent_name
                self._apply_memory_calibration(ctx, opinion, result)
                ctx.add_opinion(opinion)
                result.opinion = opinion

            result.status = StageStatus.COMPLETED

        except Exception as exc:
            logger.error("[%s] execution failed: %s", self.agent_name, exc, exc_info=True)
            result.status = StageStatus.FAILED
            result.error = str(exc)
        finally:
            result.duration_s = round(time.time() - t0, 2)

        return result

    def _run_planning_phase(
        self,
        ctx: AgentContext,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
        timeout_seconds: Optional[float],
    ) -> tuple[str, Optional[dict], str]:
        """Phase 1: Call REASONING model to produce a structured plan.

        Returns:
            Tuple of (plan_text, plan_json, reasoning_content).
            plan_json is None if parsing failed or the call errored.
            reasoning_content is "" if the model didn't produce a thinking chain.
        """
        if progress_callback:
            progress_callback({
                "type": "thinking",
                "step": 0,
                "message": "正在制定调研计划（推理模型）...",
            })

        planning_system = self._build_planning_prompt(ctx)
        planning_user = self.build_user_message(ctx)

        planning_messages: List[Dict[str, Any]] = [
            {"role": "system", "content": planning_system},
            {"role": "user", "content": planning_user},
        ]

        try:
            response = self.llm_adapter.call_text_tiered(
                planning_messages,
                agent_name=self.agent_name,  # → REASONING tier
                temperature=0.3,  # lower temp for structured planning
                max_tokens=4096,
                timeout=timeout_seconds,
            )
        except Exception as exc:
            logger.warning("[AutonomousPlanner] Planning call failed: %s", exc)
            return "", None, ""

        plan_text = (response.content or "").strip()
        if not plan_text:
            logger.warning("[AutonomousPlanner] Planning produced empty response")
            return "", None, ""

        reasoning_content = getattr(response, "reasoning_content", None) or ""

        # Emit reasoning content from the planning call (if present)
        if progress_callback and reasoning_content:
            progress_callback({
                "type": "step_reasoning",
                "step": 0,
                "phase": "planning",
                "content": reasoning_content,
            })

        # Parse the structured plan JSON
        plan_json = _extract_json(plan_text)

        # Emit plan_generated event for frontend timeline (A.4)
        if progress_callback and plan_json:
            progress_callback({
                "type": "plan_generated",
                "plan": plan_json,
            })

        return plan_text, plan_json, reasoning_content

    def _run_execution_phase(
        self,
        ctx: AgentContext,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
        timeout_seconds: Optional[float],
        plan_text: str,
        plan_json: Optional[dict],
    ) -> RunLoopResult:
        """Phase 2: Execute the plan via run_agent_loop with QUICK tier.

        The plan is injected as an assistant message at the start of the
        conversation so the executor model knows what to do.
        """
        from src.agent.agents.base_agent import BaseAgent as _BA  # for _inject_cached_data

        # Build execution messages (system prompt = execution prompt)
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt(ctx)},
        ]

        # Inject conversation history (same as BaseAgent._build_messages)
        history = ctx.meta.get("conversation_history")
        if isinstance(history, list):
            for message in history:
                if not isinstance(message, dict):
                    continue
                role = message.get("role")
                content = message.get("content")
                if role in {"user", "assistant", "system"} and isinstance(content, str) and content:
                    messages.append({"role": role, "content": content})

        # Inject cached data (reuse BaseAgent helper)
        cached_data = self._inject_cached_data(ctx)
        if cached_data:
            messages.append({"role": "user", "content": cached_data})
            messages.append({"role": "assistant", "content": "Understood, I have the pre-fetched data. Proceeding with analysis."})

        # User message with the analysis request
        messages.append({"role": "user", "content": self.build_user_message(ctx)})

        # Inject the plan as an assistant message so the executor knows the path
        if plan_text:
            plan_summary = plan_text
            if plan_json:
                steps = plan_json.get("investigation_steps", [])
                if steps:
                    plan_summary = self._format_plan_for_executor(plan_json)

            messages.append({
                "role": "assistant",
                "content": (
                    "调研计划已制定（由推理模型生成）：\n\n"
                    f"{plan_summary}\n\n"
                    "请按计划逐步调用工具获取真实数据，并根据返回结果动态调整。"
                    "收集足够信息后，输出完整的决策仪表盘 JSON。"
                ),
            })

        # Run the ReAct loop with QUICK tier (executor agent name)
        # Autonomous mode gets full tool access including approval-required
        # tools (e.g. execute_python) since the user explicitly opted in.
        registry = self._filtered_registry()
        loop_result: RunLoopResult = run_agent_loop(
            messages=messages,
            tool_registry=registry,
            llm_adapter=self.llm_adapter,
            max_steps=self.max_steps,
            progress_callback=progress_callback,
            max_wall_clock_seconds=timeout_seconds,
            agent_name=self.executor_agent_name,  # → QUICK tier
            allow_approval_required=True,
        )

        return loop_result

    def _make_reasoning_capture_callback(
        self,
        original_callback: Optional[Callable[[Dict[str, Any]], None]],
        reasoning_trace: List[Dict[str, Any]],
    ) -> Optional[Callable[[Dict[str, Any]], None]]:
        """Wrap progress_callback to capture step_reasoning events for persistence.

        Returns a new callback that forwards all events to the original
        callback AND appends step_reasoning events to ``reasoning_trace``
        for later DB storage.
        """
        if original_callback is None:
            return None

        def _wrapped(event: Dict[str, Any]) -> None:
            # Forward to original
            original_callback(event)
            # Capture step_reasoning for persistence
            if event.get("type") == "step_reasoning":
                reasoning_trace.append({
                    "step": event.get("step", 0),
                    "phase": event.get("phase", "execution"),
                    "content": event.get("content", ""),
                })

        return _wrapped

    def _format_plan_for_executor(self, plan_json: dict) -> str:
        """Format the structured plan as readable text for the executor agent."""
        lines: list[str] = []
        steps = plan_json.get("investigation_steps", [])
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_num = step.get("step", "?")
            objective = step.get("objective", "")
            tools = step.get("tools", [])
            priority = step.get("priority", "")
            tools_str = ", ".join(tools) if isinstance(tools, list) else str(tools)
            lines.append(f"  {step_num}. [{priority}] {objective} (工具: {tools_str})")

        early_stop = plan_json.get("early_stop_conditions", [])
        deep_dive = plan_json.get("deep_dive_triggers", [])

        parts = ["调研步骤:"]
        if lines:
            parts.extend(lines)
        else:
            parts.append("  (无具体步骤，请自主判断)")

        if early_stop:
            parts.append("\n可提前收尾: " + "; ".join(early_stop))
        if deep_dive:
            parts.append("\n需追加调查: " + "; ".join(deep_dive))

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Output processing — mirrors DecisionAgent.post_process
    # ------------------------------------------------------------------

    def post_process(self, ctx: AgentContext, raw_text: str) -> Optional[AgentOpinion]:
        """Parse the dashboard JSON from the LLM response and store in ctx.

        This follows the same pattern as DecisionAgent.post_process:
        - On success: store parsed dashboard in ``ctx["final_dashboard"]``
        - On failure: store raw text in ``ctx["final_dashboard_raw"]``
        - Always return an AgentOpinion for the reflection/learning system
        """
        text = (raw_text or "").strip()
        if not text:
            logger.warning("[AutonomousPlanner] empty response from LLM")
            return None

        # Chat mode: store as plain text
        if ctx.meta.get("response_mode") == "chat":
            ctx.set_data("final_response_text", text)
            return AgentOpinion(
                agent_name=self.agent_name,
                signal="hold",
                confidence=0.5,
                reasoning=text,
                raw_data={"response_mode": "chat"},
            )

        dashboard = parse_dashboard_json(text)
        if dashboard:
            dashboard["decision_type"] = normalize_decision_signal(
                dashboard.get("decision_type", "hold")
            )
            ctx.set_data("final_dashboard", dashboard)

            try:
                score = float(dashboard.get("sentiment_score", 50) or 50)
            except (TypeError, ValueError):
                score = 50.0

            return AgentOpinion(
                agent_name=self.agent_name,
                signal=dashboard.get("decision_type", "hold"),
                confidence=min(1.0, score / 100.0),
                reasoning=dashboard.get("analysis_summary", ""),
                raw_data=dashboard,
            )
        else:
            # JSON parsing failed — store raw text for downstream fallback
            ctx.set_data("final_dashboard_raw", text)
            logger.warning("[AutonomousPlanner] failed to parse dashboard JSON")
            return None


# ============================================================
# Helpers
# ============================================================

def _build_language_section(report_language: str) -> str:
    """Build output-language guidance for the autonomous prompt."""
    normalized = normalize_report_language(report_language)
    if normalized == "en":
        return """
## Output Language
- Keep every JSON key unchanged.
- `decision_type` must remain `buy|hold|sell`.
- Write all human-readable JSON values in English.
"""
    return """
## 输出语言
- 所有 JSON 键名保持不变。
- `decision_type` 必须保持为 `buy|hold|sell`。
- 所有面向用户的人类可读文本值必须使用中文。
"""


def _extract_json(text: str) -> Optional[dict]:
    """Extract the first JSON object from a text that may contain markdown fences.

    Returns None if no valid JSON object is found.
    """
    if not text:
        return None

    # Strip markdown code fences if present
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Remove first line (```json or ```)
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:]
        # Remove trailing ```
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]

    # Try direct parse first
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass

    # Try to find a JSON object in the text
    start = cleaned.find("{")
    if start == -1:
        return None

    # Find matching closing brace
    depth = 0
    for i in range(start, len(cleaned)):
        if cleaned[i] == "{":
            depth += 1
        elif cleaned[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(cleaned[start:i + 1])
                except (json.JSONDecodeError, ValueError):
                    return None

    return None
