# -*- coding: utf-8 -*-
"""
VisionAgent — multimodal image understanding specialist.

Phase C.3 核心组件:
- 接收图片（K 线截图、用户上传、财报/公告截图）+ 问题，用 VISION tier 模型分析。
- 用途 1：用户贴图问"这个形态怎么看"。
- 用途 2：被 autonomous planner 调用，对生成的 K 线图做形态确认。
- 用途 3：财报/公告 OCR 提取关键数据。

设计要点:
  1. 不走标准 run_agent_loop（无工具循环）— 直接调 call_text_tiered(agent_name="vision")
     构造 OpenAI vision 格式的 list content 消息: [text, image_url]
  2. 如果 ctx.meta["images"] 存在（用户上传），直接用之
  3. 如果无图片但 ctx.stock_code 存在，自动调 capture_kline_chart 生成截图
  4. 降级: VISION 模型不可用时，退化为纯文本分析（告知 AI 无图可看）
  5. 注册为可被 orchestrator 插入的 specialist agent
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from src.agent.agents.base_agent import BaseAgent
from src.agent.protocols import AgentContext, AgentOpinion, StageResult, StageStatus

logger = logging.getLogger(__name__)


class VisionAgent(BaseAgent):
    """Multimodal vision analysis agent.

    Receives images (base64 data URLs) + a question, calls the VISION tier
    model to analyze chart patterns, OCR financial reports, etc.

    Image sources (priority order):
        1. ``ctx.meta["images"]`` — user-uploaded images (list of data URLs)
        2. Auto-capture via ``capture_kline_chart`` tool when ``ctx.stock_code``
           is set but no images are provided

    The agent bypasses the standard tool-calling loop because vision analysis
    is a single multimodal LLM call, not an iterative ReAct cycle.
    """

    agent_name = "vision"
    max_steps = 2  # Only used for the optional chart-capture pre-step
    # Vision agent can call chart-capture tools to auto-generate K-line images
    tool_names = [
        "capture_kline_chart",
        "capture_intraday_chart",
    ]

    # ------------------------------------------------------------------
    # Prompt assembly
    # ------------------------------------------------------------------

    def system_prompt(self, ctx: AgentContext) -> str:
        report_lang = ctx.meta.get("report_language", "zh")
        if report_lang == "en":
            return (
                "You are a **Vision Analysis Agent** specialised in reading financial charts and documents.\n\n"
                "First, classify the image(s) into one of these types, then apply the matching analysis path:\n\n"
                "**Type A — K-line / price chart**\n"
                "1. K-line pattern recognition: head-and-shoulders, double top/bottom, "
                "triangles, flags, support/resistance breakouts, candlestick patterns "
                "(hammer, doji, engulfing, morning/evening star).\n"
                "2. Technical indicator visual check: MA alignment (bullish/bearish stack), "
                "volume spikes, price-volume divergence, BOLL band squeeze/break.\n"
                "3. Chart annotation: identify key price levels, trend lines, volume characteristics.\n\n"
                "**Type B — Financial report / earnings screenshot**\n"
                "Extract structured data in this format:\n"
                "```\n【财报OCR】\n报告期: <e.g. 2024Q3 / 2024年报>\n营业总收入: <amount + unit + YoY%>\n归母净利润: <amount + unit + YoY%>\n扣非净利润: <amount + unit + YoY%>\n基本EPS: <value>\n毛利率: <%>\n净利率: <%>\n资产负债率: <%>\n经营现金流: <amount + unit + YoY%>\nROE: <%>\n十大股东变动: <增/减/新进，如有>\n```\n"
                "If a field is not visible, mark as `N/A`. Always include units (元/万元/亿元).\n\n"
                "**Type C — Company announcement / notice**\n"
                "Identify announcement type (定增/回购/增持/减持/重大资产重组/业绩预告/分红/诉讼), "
                "then extract: 关键主体, 涉及金额/比例, 时间节点, 对股价影响判断 (利好/利空/中性).\n"
                "Format:\n"
                "```\n【公告OCR】\n公告类型: <type>\n关键事项: <one-line summary>\n核心数据: <amounts, ratios, dates>\n影响评估: <利好/利空/中性> — <reason>\n```\n\n"
                "**Type D — Other / unclear**\n"
                "Describe what you see and state the image is not a recognised financial chart/document.\n\n"
                "Output language: English."
            )
        return (
            "你是一个**视觉分析 Agent**，专注于解读金融图表和文档。\n\n"
            "请先判断图片类型，再走对应分析路径：\n\n"
            "**A 类 — K 线 / 行情图**\n"
            "1. K 线形态识别：头肩顶/底、双顶/双底、三角形、旗形、突破/跌破、"
            "蜡烛图形态（锤子线、十字星、吞没形态、晨星/暮星等）。\n"
            "2. 技术指标可视化检查：均线排列（多头/空头排列）、成交量异动、"
            "价量关系、背离信号、BOLL 收口/突破。\n"
            "3. 图表标注：识别关键价位、趋势线、成交量特征。\n\n"
            "**B 类 — 财报 / 业绩截图**\n"
            "按以下结构提取数据：\n"
            "```\n【财报OCR】\n报告期: <如 2024Q3 / 2024年报>\n营业总收入: <金额+单位+同比%>\n归母净利润: <金额+单位+同比%>\n扣非净利润: <金额+单位+同比%>\n基本EPS: <值>\n毛利率: <%>\n净利率: <%>\n资产负债率: <%>\n经营现金流: <金额+单位+同比%>\nROE: <%>\n十大股东变动: <增/减/新进，如有>\n```\n"
            "未显示的字段标记为 `N/A`。务必带单位（元/万元/亿元）。\n\n"
            "**C 类 — 公司公告 / 通知**\n"
            "判断公告类型（定增/回购/增持/减持/重大资产重组/业绩预告/分红/诉讼），"
            "再提取：关键主体、涉及金额/比例、时间节点、对股价影响判断（利好/利空/中性）。\n"
            "格式：\n"
            "```\n【公告OCR】\n公告类型: <type>\n关键事项: <一句话摘要>\n核心数据: <金额、比例、日期>\n影响评估: <利好/利空/中性> — <原因>\n```\n\n"
            "**D 类 — 其他 / 不清晰**\n"
            "描述所见内容，并说明图片非金融图表/文档。\n\n"
            "输出语言: 中文。"
        )

    def build_user_message(self, ctx: AgentContext) -> str:
        """Build the text portion of the user message (image appended separately)."""
        parts: List[str] = []

        query = ctx.query or ""
        if query:
            parts.append(query)

        if ctx.stock_code:
            parts.append(f"\n标的代码: {ctx.stock_code}")
        if ctx.stock_name:
            parts.append(f"标的名称: {ctx.stock_name}")

        image_count = len(ctx.meta.get("images", []))
        if image_count > 0:
            parts.append(f"\n（附 {image_count} 张图片，请结合图片分析）")
        elif ctx.stock_code:
            parts.append("\n（已自动生成 K 线截图，请结合图片分析）")

        if not parts:
            parts.append("请分析附图中的技术形态或财务数据。")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Custom run — bypasses tool loop, calls VISION tier directly
    # ------------------------------------------------------------------

    def run(
        self,
        ctx: AgentContext,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> StageResult:
        """Execute vision analysis.

        Flow:
            1. Collect images from ctx.meta["images"] or auto-capture via tool.
            2. Build multimodal messages (text + image_url list content).
            3. Call VISION tier model via call_text_tiered.
            4. Store result in ctx and return AgentOpinion.
        """
        t0 = time.time()
        result = StageResult(stage_name=self.agent_name, status=StageStatus.RUNNING)

        try:
            if progress_callback:
                progress_callback({
                    "type": "stage_start",
                    "stage": self.agent_name,
                    "message": "视觉分析中（vision 模型）...",
                })

            # === Step 1: Collect images ===
            images: List[str] = list(ctx.meta.get("images", []) or [])

            # Auto-capture K-line chart if no images but stock_code is available
            if not images and ctx.stock_code:
                captured = self._auto_capture_chart(ctx, progress_callback)
                if captured:
                    images.extend(captured)

            if not images:
                # No images available — degrade to text-only analysis
                result.status = StageStatus.COMPLETED
                result.meta["raw_text"] = (
                    "视觉分析 Agent 未获得图片输入，且无法自动生成 K 线截图。"
                    "请提供图片或确保股票代码有效。"
                )
                result.duration_s = round(time.time() - t0, 2)
                return result

            # === Step 2: Build multimodal messages ===
            messages = self._build_multimodal_messages(ctx, images)

            # === Step 3: Call VISION tier model ===
            response = self.llm_adapter.call_text_tiered(
                messages,
                agent_name=self.agent_name,  # → VISION tier via DEFAULT_TIER_MAP
                temperature=0.3,
                max_tokens=2048,
                timeout=timeout_seconds,
            )

            raw_text = (response.content or "").strip()
            result.tokens_used = getattr(response, "total_tokens", 0) or 0
            result.meta["raw_text"] = raw_text
            result.meta["models_used"] = [getattr(response, "model", "")]
            result.meta["images_analyzed"] = len(images)
            result.meta["tool_calls_log"] = []

            if not raw_text:
                result.status = StageStatus.FAILED
                result.error = "Vision model returned empty response"
                result.duration_s = round(time.time() - t0, 2)
                return result

            # === Step 4: Post-process into opinion ===
            opinion = self.post_process(ctx, raw_text)
            if opinion is not None:
                opinion.agent_name = self.agent_name
                ctx.add_opinion(opinion)
                result.opinion = opinion

            # Store vision analysis in ctx for downstream agents
            ctx.set_data("vision_analysis", {
                "summary": raw_text,
                "images_count": len(images),
                "agent": self.agent_name,
            })

            result.status = StageStatus.COMPLETED

            if progress_callback:
                progress_callback({
                    "type": "stage_done",
                    "stage": self.agent_name,
                    "status": result.status.value,
                    "duration": round(time.time() - t0, 2),
                })

        except Exception as exc:
            logger.error("[VisionAgent] execution failed: %s", exc, exc_info=True)
            result.status = StageStatus.FAILED
            result.error = str(exc)
        finally:
            result.duration_s = round(time.time() - t0, 2)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _auto_capture_chart(
        self,
        ctx: AgentContext,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
    ) -> List[str]:
        """Auto-generate a K-line chart image when no user images are provided.

        Returns a list of data URLs (base64 PNG). Returns empty list on failure.
        """
        try:
            tool_def = self.tool_registry.get("capture_kline_chart")
            if tool_def is None:
                logger.warning("[VisionAgent] capture_kline_chart tool not found in registry")
                return []

            if progress_callback:
                progress_callback({
                    "type": "tool_call",
                    "tool": "capture_kline_chart",
                    "message": f"自动生成 {ctx.stock_code} K 线截图...",
                })

            result = tool_def.handler(stock_code=ctx.stock_code, days=60)

            if isinstance(result, dict) and result.get("image_data_url"):
                logger.info(
                    "[VisionAgent] auto-captured K-line chart for %s (%s bars)",
                    ctx.stock_code, result.get("bars", 0),
                )
                return [result["image_data_url"]]
            else:
                logger.warning(
                    "[VisionAgent] auto-capture failed for %s: %s",
                    ctx.stock_code, result.get("error", "unknown") if isinstance(result, dict) else "invalid",
                )
                return []
        except Exception as exc:
            logger.warning("[VisionAgent] auto-capture exception: %s", exc)
            return []

    def _build_multimodal_messages(
        self,
        ctx: AgentContext,
        images: List[str],
    ) -> List[Dict[str, Any]]:
        """Build OpenAI vision-format messages with list content.

        Format:
            [
              {"role": "system", "content": "..."},
              {"role": "user", "content": [
                {"type": "text", "text": "..."},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
                ...
              ]}
            ]
        """
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt(ctx)},
        ]

        # Inject conversation history (text-only messages)
        history = ctx.meta.get("conversation_history")
        if isinstance(history, list):
            for message in history:
                if not isinstance(message, dict):
                    continue
                role = message.get("role")
                content = message.get("content")
                if role in {"user", "assistant", "system"} and isinstance(content, str) and content:
                    messages.append({"role": role, "content": content})

        # Build multimodal user message
        text_content = self.build_user_message(ctx)
        content_list: List[Dict[str, Any]] = [
            {"type": "text", "text": text_content},
        ]
        for img_url in images:
            content_list.append({
                "type": "image_url",
                "image_url": {"url": img_url},
            })

        messages.append({"role": "user", "content": content_list})
        return messages

    # ------------------------------------------------------------------
    # Output processing
    # ------------------------------------------------------------------

    def post_process(self, ctx: AgentContext, raw_text: str) -> Optional[AgentOpinion]:
        """Build an AgentOpinion from the vision model's text response.

        Vision analysis is descriptive (not a buy/sell signal), so we use
        a neutral signal with moderate confidence. The raw text is the
        primary value — it gets injected into ctx for downstream agents.
        """
        text = (raw_text or "").strip()
        if not text:
            return None

        return AgentOpinion(
            agent_name=self.agent_name,
            signal="hold",  # Vision agent provides analysis, not trading signals
            confidence=0.6,
            reasoning=text,
            raw_data={
                "vision_analysis": text,
                "images_analyzed": True,
            },
        )
