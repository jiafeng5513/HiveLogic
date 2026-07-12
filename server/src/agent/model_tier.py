# -*- coding: utf-8 -*-
"""
===================================
模型层级分配 (Tiered LLM Dispatch)
===================================

定义 Agent → 模型层级的映射关系。

四个层级:
- reasoning: 推理模型 (deepseek-reasoner 等)，用于 autonomous planner 的规划步骤
- deep_think: 深度推理模型 (GPT-4o, Claude Sonnet 等)，用于 decision/risk 等高权重 agent
- quick_think: 快速模型 (GPT-4o-mini, Claude Haiku 等)，用于 technical/intel 等信息提取 agent
- vision: 多模态视觉模型 (GPT-4o, Gemini-2.0-flash 等)，用于 vision_agent 的图像理解

核心思想:
- 信息提取类 agent (tech, intel) 对推理深度要求低，但输出量大 → quick 模型
- 综合决策类 agent (decision, risk) 对推理质量要求高 → deep 模型
- 自主规划的 planning 步骤需要最强推理能力 → reasoning 模型
- 图像理解 (K 线截图、财报 OCR) 需要多模态能力 → vision 模型
- 用户可通过 config 覆盖默认分配
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Optional


class ModelTier(str, Enum):
    """模型层级"""
    REASONING = "reasoning"    # 推理模型 (e.g. deepseek-reasoner) — 自主规划用
    DEEP = "deep_think"        # 深度推理 (e.g. GPT-4o, Claude Sonnet)
    QUICK = "quick_think"      # 快速提取 (e.g. GPT-4o-mini, Claude Haiku)
    VISION = "vision"          # 多模态视觉 (e.g. GPT-4o, Gemini-2.0-flash)


# 默认 Agent → 层级映射
# 可通过 config.agent_model_assignment 覆盖
DEFAULT_TIER_MAP: Dict[str, ModelTier] = {
    "technical": ModelTier.QUICK,
    "intel": ModelTier.QUICK,
    "risk": ModelTier.DEEP,
    "decision": ModelTier.DEEP,
    # skill agents 默认用 quick
    "skill": ModelTier.QUICK,
    # Phase 3: 辩论 agents
    "bull_researcher": ModelTier.QUICK,
    "bear_researcher": ModelTier.QUICK,
    "research_manager": ModelTier.DEEP,
    # Phase 3: 风险讨论 agents
    "risk_aggressive": ModelTier.QUICK,
    "risk_conservative": ModelTier.QUICK,
    "risk_neutral": ModelTier.QUICK,
    "risk_manager": ModelTier.DEEP,
    # Phase A: autonomous planner — 规划步骤用推理模型
    "autonomous_planner": ModelTier.REASONING,
    # Phase A: autonomous executor — 执行步骤用快速模型（调工具、提取信息）
    "autonomous_executor": ModelTier.QUICK,
    # Phase C: vision agent — 图像理解用多模态模型
    "vision": ModelTier.VISION,
}


def get_tier_for_agent(
    agent_name: str,
    override_map: Optional[Dict[str, str]] = None,
) -> ModelTier:
    """
    获取指定 agent 应使用的模型层级。

    Args:
        agent_name: Agent 名称 (e.g. "technical", "decision")
        override_map: 用户自定义覆盖 (来自 config.agent_model_assignment)

    Returns:
        ModelTier 枚举值
    """
    # 1. 用户覆盖优先
    if override_map:
        user_tier = override_map.get(agent_name)
        if user_tier:
            try:
                return ModelTier(user_tier)
            except ValueError:
                pass

    # 2. 默认映射
    tier = DEFAULT_TIER_MAP.get(agent_name)
    if tier:
        return tier

    # 3. 对未知 agent 回退到 quick
    return ModelTier.QUICK
