/**
 * ===================================
 * Chat Service — Agent 对话 API 封装
 * ===================================
 *
 * 职责:
 * 1. 封装后端 /api/v1/agent/chat/* 系列接口
 * 2. SSE (EventSource) 流式消息消费
 * 3. 会话 CRUD
 * 4. 技能列表获取
 */

import { getApiBase } from './serverConfig'

// ==================== 类型定义 ====================

export type ChatMode = 'quick' | 'deep' | 'plan' | 'autonomous'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  mode?: ChatMode
  images?: string[] // 用户消息附带的图片 (data URL), 用于多模态展示
  metadata?: {
    thinking?: string
    tools?: ToolCallInfo[]
    stages?: StageInfo[]
    debate?: DebateInfo
    riskDebate?: RiskDebateInfo
    dashboard?: DashboardData
    fromAgentWindow?: boolean
  }
}

export interface ToolCallInfo {
  name: string
  args?: Record<string, unknown>
  result?: string
  status: 'running' | 'done' | 'error'
  duration?: number
}

export interface StageInfo {
  stage: string
  status: 'pending' | 'running' | 'completed' | 'error'
  message?: string
  duration?: number
}

export interface DebateInfo {
  round: number
  totalRounds: number
  bull?: string
  bear?: string
  status: 'running' | 'completed'
}

export interface RiskDebateInfo {
  perspectives: string[]
  content: Record<string, string>
  status: 'running' | 'completed'
}

export interface PlanStep {
  step: number
  objective: string
  tools: string[]
  expected_data?: string
  priority: 'high' | 'medium' | 'low'
}

export interface InvestigationPlan {
  investigation_steps: PlanStep[]
  early_stop_conditions: string[]
  deep_dive_triggers: string[]
  estimated_steps: number
}

export interface StepReasoning {
  step: number
  phase: string  // "planning" | "execution"
  content: string
}

export interface DashboardData {
  signal?: string
  confidence?: number
  summary?: string
  // Extended fields from Phase 2
  debate_summary?: {
    bull_core_thesis?: string
    bear_core_thesis?: string
    manager_verdict?: string
    confidence_shift?: string
  }
  risk_assessment?: {
    aggressive_view?: string
    conservative_view?: string
    verdict?: string
    max_acceptable_position?: string
  }
  market_context?: {
    index_trend?: string
    sector_strength?: string
    market_sentiment?: string
  }
  skill_opinions?: Array<{
    skill_name: string
    signal: string
    confidence: number
    key_observation: string
  }>
  [key: string]: unknown
}

export interface ChatSession {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface AgentSkill {
  id: string
  name: string
  description?: string
}

export interface ChatRequest {
  message: string
  session_id?: string
  mode?: ChatMode
  skills?: string[]
  agent_id?: string
  symbol?: string
  images?: string[] // 多模态图片 (data URL), 触发 VisionAgent
}

export interface SSEEvent {
  type: string
  data: Record<string, unknown>
}

// ==================== 配置 ====================

// 后端地址统一走 serverConfig（支持本地/远程模式切换），不再硬编码端口
function getApiUrl(path: string): string {
  return `${getApiBase()}${path}`
}

// ==================== 健康检查 ====================

export async function checkHealth(): Promise<boolean> {
  try {
    const resp = await fetch(getApiUrl('/api/health'), {
      signal: AbortSignal.timeout(3000)
    })
    return resp.ok
  } catch {
    return false
  }
}

// ==================== 技能 API ====================

export async function fetchSkills(): Promise<{ skills: AgentSkill[]; defaultSkillId?: string }> {
  const resp = await fetch(getApiUrl('/api/v1/agent/skills'), {
    signal: AbortSignal.timeout(5000)
  })
  if (!resp.ok) throw new Error(`fetchSkills failed: ${resp.status}`)
  const data = await resp.json()
  return {
    skills: data.skills || [],
    defaultSkillId: data.default_skill_id
  }
}

// ==================== 会话 API ====================

export async function fetchSessions(limit = 30): Promise<ChatSession[]> {
  const resp = await fetch(getApiUrl(`/api/v1/agent/chat/sessions?limit=${limit}`), {
    signal: AbortSignal.timeout(5000)
  })
  if (!resp.ok) throw new Error(`fetchSessions failed: ${resp.status}`)
  const data = await resp.json()
  // 后端返回 session_id / last_active，映射为前端 ChatSession
  return (data.sessions || []).map((s: Record<string, unknown>) => ({
    id: s.session_id || s.id,
    title: s.title || '未命名',
    created_at: s.created_at || '',
    updated_at: s.last_active || s.updated_at || s.created_at || '',
    message_count: s.message_count || 0
  })) as ChatSession[]
}

export async function fetchSessionMessages(sessionId: string): Promise<ChatMessage[]> {
  const resp = await fetch(getApiUrl(`/api/v1/agent/chat/sessions/${encodeURIComponent(sessionId)}`), {
    signal: AbortSignal.timeout(10000)
  })
  if (!resp.ok) throw new Error(`fetchSessionMessages failed: ${resp.status}`)
  const data = await resp.json()
  // 后端返回 {id, role, content, created_at}，映射为前端 ChatMessage
  return (data.messages || []).map((m: Record<string, unknown>) => {
    const content = String(m.content || '')
    const role = m.role as ChatMessage['role']
    let metadata: ChatMessage['metadata'] = undefined

    // assistant 消息: 尝试解析 dashboard JSON（后端存储时 content = JSON.stringify(dashboard)）
    if (role === 'assistant' && content.trim().startsWith('{')) {
      try {
        const parsed = JSON.parse(content)
        // 判断是否为 dashboard 数据（含常见 dashboard 字段）
        if (parsed && typeof parsed === 'object' && (
          parsed.signal || parsed.summary || parsed.confidence != null ||
          parsed.decision_type || parsed.analysis_summary || parsed.sentiment_score != null ||
          parsed.confidence_level || parsed.dashboard
        )) {
          metadata = { dashboard: parsed as DashboardData }
        }
      } catch {
        // 非 JSON，按普通文本处理
      }
    }

    return {
      id: String(m.id),
      role,
      content: metadata?.dashboard ? '' : content,
      timestamp: m.created_at ? new Date(m.created_at as string).getTime() : Date.now(),
      mode: undefined,
      metadata
    }
  }) as ChatMessage[]
}

export async function deleteSession(sessionId: string): Promise<void> {
  const resp = await fetch(getApiUrl(`/api/v1/agent/chat/sessions/${encodeURIComponent(sessionId)}`), {
    method: 'DELETE',
    signal: AbortSignal.timeout(5000)
  })
  if (!resp.ok) throw new Error(`deleteSession failed: ${resp.status}`)
}

export async function deleteAllSessions(): Promise<void> {
  const resp = await fetch(getApiUrl('/api/v1/agent/chat/sessions'), {
    method: 'DELETE',
    signal: AbortSignal.timeout(10000)
  })
  if (!resp.ok) throw new Error(`deleteAllSessions failed: ${resp.status}`)
}

// ==================== 流式对话 (SSE) ====================

export type SSECallback = (event: SSEEvent) => void

export interface StreamController {
  abort: () => void
}

/**
 * 发起流式对话请求 (SSE)
 * @param request 对话请求
 * @param onEvent SSE 事件回调
 * @returns StreamController (用于中止)
 */
export function streamChat(request: ChatRequest, onEvent: SSECallback): StreamController {
  const abortController = new AbortController()

  const url = getApiUrl('/api/v1/agent/chat/stream')
  const body = JSON.stringify({
    message: request.message,
    session_id: request.session_id || undefined,
    mode: request.mode || 'chat',
    skills: request.skills || [],
    agent_id: request.agent_id || undefined,
    symbol: request.symbol || undefined,
    images: request.images || undefined
  })

  // 使用 fetch + ReadableStream 解析 SSE (比 EventSource 更灵活，支持 POST)
  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body,
    signal: abortController.signal
  })
    .then(async (resp) => {
      if (!resp.ok) {
        onEvent({ type: 'error', data: { message: `HTTP ${resp.status}` } })
        return
      }
      const reader = resp.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        let currentEvent = ''
        let currentData = ''

        for (const line of lines) {
          if (line.startsWith('event:')) {
            currentEvent = line.slice(6).trim()
          } else if (line.startsWith('data:')) {
            currentData = line.slice(5).trim()
          } else if (line === '') {
            // Empty line = end of event
            if (currentEvent && currentData) {
              try {
                const parsed = JSON.parse(currentData)
                onEvent({ type: currentEvent, data: parsed })
              } catch {
                onEvent({ type: currentEvent, data: { raw: currentData } })
              }
            } else if (currentData) {
              // No event type, treat as 'message'
              try {
                const parsed = JSON.parse(currentData)
                onEvent({ type: parsed.type || 'message', data: parsed })
              } catch {
                onEvent({ type: 'message', data: { raw: currentData } })
              }
            }
            currentEvent = ''
            currentData = ''
          }
        }
      }

      // Stream ended
      onEvent({ type: 'stream_end', data: {} })
    })
    .catch((err) => {
      if (err.name === 'AbortError') {
        onEvent({ type: 'aborted', data: {} })
      } else {
        onEvent({ type: 'error', data: { message: err.message } })
      }
    })

  return { abort: () => abortController.abort() }
}
