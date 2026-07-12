/**
 * useChatStream — SSE 流式处理 composable
 *
 * 侧边栏和 Agent Window 共用。
 * 负责将 SSE 事件流转换为响应式状态。
 */

import { ref, readonly } from 'vue'
import { streamChat, type ChatRequest, type SSEEvent, type StreamController } from '../service/chatService'
import type { ChatMode, StageInfo, ToolCallInfo, DebateInfo, RiskDebateInfo, DashboardData, InvestigationPlan, StepReasoning } from '../service/chatService'

export type ChatStreamState =
  | 'idle'
  | 'connecting'
  | 'thinking'
  | 'executing'
  | 'debating'
  | 'generating'
  | 'done'
  | 'error'

export interface StreamResult {
  sessionId: string | null
  content: string
  thinking: string
  tools: ToolCallInfo[]
  stages: StageInfo[]
  debate: DebateInfo | null
  riskDebate: RiskDebateInfo | null
  dashboard: DashboardData | null
  plan: InvestigationPlan | null
  stepReasoning: StepReasoning[]
}

export function useChatStream() {
  const state = ref<ChatStreamState>('idle')
  const result = ref<StreamResult>({
    sessionId: null,
    content: '',
    thinking: '',
    tools: [],
    stages: [],
    debate: null,
    riskDebate: null,
    dashboard: null,
    plan: null,
    stepReasoning: []
  })
  const error = ref<string | null>(null)

  let controller: StreamController | null = null

  function resetResult() {
    result.value = {
      sessionId: null,
      content: '',
      thinking: '',
      tools: [],
      stages: [],
      debate: null,
      riskDebate: null,
      dashboard: null,
      plan: null,
      stepReasoning: []
    }
    error.value = null
  }

  function handleEvent(event: SSEEvent) {
    switch (event.type) {
      case 'thinking':
        state.value = 'thinking'
        if (event.data.content) {
          result.value.thinking += event.data.content as string
        }
        break

      case 'tool_start':
        state.value = 'executing'
        result.value.tools.push({
          name: event.data.tool as string,
          args: event.data.args as Record<string, unknown>,
          status: 'running'
        })
        break

      case 'tool_done': {
        state.value = 'executing'
        const toolName = event.data.tool as string
        const tool = result.value.tools.find(t => t.name === toolName && t.status === 'running')
        if (tool) {
          tool.status = 'done'
          tool.result = event.data.result as string
          tool.duration = event.data.duration as number
        }
        break
      }

      case 'stage_start':
        state.value = 'executing'
        result.value.stages.push({
          stage: event.data.stage as string,
          status: 'running',
          message: event.data.message as string
        })
        break

      case 'stage_done': {
        const stageName = event.data.stage as string
        const stage = result.value.stages.find(s => s.stage === stageName)
        if (stage) {
          stage.status = 'completed'
          stage.duration = event.data.duration as number
        }
        break
      }

      case 'parallel_start':
        state.value = 'executing'
        // Create stage entries for parallel agents so stage_done can mark them completed
        if (Array.isArray(event.data.agents)) {
          for (const name of event.data.agents as string[]) {
            if (!result.value.stages.find(s => s.stage === name)) {
              result.value.stages.push({
                stage: name,
                status: 'running',
                message: `Running ${name} analysis...`
              })
            }
          }
        }
        break

      case 'debate_round':
        state.value = 'debating'
        result.value.debate = {
          round: event.data.round as number,
          totalRounds: event.data.total as number,
          bull: event.data.bull as string | undefined,
          bear: event.data.bear as string | undefined,
          status: event.data.status as 'running' | 'completed'
        }
        break

      case 'risk_debate':
        state.value = 'debating'
        result.value.riskDebate = {
          perspectives: event.data.perspectives as string[],
          content: event.data.content as Record<string, string>,
          status: event.data.status as 'running' | 'completed'
        }
        break

      case 'plan_generated':
        result.value.plan = event.data.plan as InvestigationPlan
        break

      case 'step_reasoning':
        result.value.stepReasoning.push({
          step: event.data.step as number,
          phase: (event.data.phase as string) || 'execution',
          content: event.data.content as string
        })
        break

      case 'generating':
        state.value = 'generating'
        if (event.data.content) {
          result.value.content += event.data.content as string
        }
        break

      case 'done':
        state.value = 'done'
        if (event.data.session_id) {
          result.value.sessionId = event.data.session_id as string
        }
        if (event.data.dashboard) {
          result.value.dashboard = event.data.dashboard as DashboardData
        }
        // Final content (if provided as whole) — skip when dashboard is present to avoid raw JSON display
        if (event.data.content && !result.value.content && !event.data.dashboard) {
          result.value.content = event.data.content as string
        }
        break

      case 'plan_ready':
        state.value = 'done'
        result.value.dashboard = { plan: event.data.plan } as DashboardData
        break

      case 'error':
        state.value = 'error'
        error.value = (event.data.message as string) || '未知错误'
        break

      case 'stream_end':
        if (state.value !== 'done' && state.value !== 'error') {
          state.value = 'done'
        }
        break

      case 'aborted':
        state.value = 'idle'
        break
    }
  }

  function send(request: ChatRequest) {
    resetResult()
    state.value = 'connecting'
    controller = streamChat(request, handleEvent)
  }

  function abort() {
    if (controller) {
      controller.abort()
      controller = null
    }
    state.value = 'idle'
  }

  function reset() {
    resetResult()
    state.value = 'idle'
  }

  return {
    state: readonly(state),
    result: readonly(result),
    error: readonly(error),
    send,
    abort,
    reset
  }
}
