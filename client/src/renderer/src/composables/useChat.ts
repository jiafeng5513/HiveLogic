/**
 * useChat — Chat 状态管理 composable
 *
 * 侧边栏和 Agent Window 共用。
 * 管理消息列表、会话、模式切换等。
 */

import { ref, computed, watch } from 'vue'
import { useChatStream } from './useChatStream'
import {
  fetchSessions,
  fetchSessionMessages,
  deleteSession,
  deleteAllSessions,
  fetchSkills,
  checkHealth,
  type ChatMessage,
  type ChatSession,
  type AgentSkill,
  type ChatMode,
  type ChatRequest
} from '../service/chatService'

export interface UseChatOptions {
  /** 初始模式 */
  defaultMode?: ChatMode
  /** 允许的模式列表 (侧边栏限制, Agent Window 全部) */
  allowedModes?: ChatMode[]
  /** 是否自动检测升级提示 (仅侧边栏) */
  showUpgradeHint?: boolean
}

export function useChat(options: UseChatOptions = {}) {
  const {
    defaultMode = 'quick',
    allowedModes = ['quick', 'deep', 'plan'],
    showUpgradeHint = false
  } = options

  // ==================== 状态 ====================
  const messages = ref<ChatMessage[]>([])
  const sessions = ref<ChatSession[]>([])
  const currentSessionId = ref<string | null>(null)
  const currentMode = ref<ChatMode>(defaultMode)
  const skills = ref<AgentSkill[]>([])
  const selectedSkills = ref<string[]>([])
  const connected = ref(false)
  const loading = ref(false)
  const shouldUpgrade = ref(false)

  // SSE 流
  const { state: streamState, result: streamResult, error: streamError, send: streamSend, abort: streamAbort, reset: streamReset } = useChatStream()

  // ==================== 计算属性 ====================
  const isStreaming = computed(() =>
    streamState.value !== 'idle' && streamState.value !== 'done' && streamState.value !== 'error'
  )

  // ==================== 初始化 ====================
  async function init() {
    connected.value = await checkHealth()
    if (connected.value) {
      try {
        const data = await fetchSkills()
        skills.value = data.skills
        if (data.defaultSkillId) {
          selectedSkills.value = [data.defaultSkillId]
        }
      } catch { /* ignore */ }
      await loadSessions()
    } else {
      // 后端可能尚未就绪，延迟重试加载会话
      setTimeout(async () => {
        connected.value = await checkHealth()
        if (connected.value) {
          try {
            const data = await fetchSkills()
            skills.value = data.skills
            if (data.defaultSkillId && !selectedSkills.value.length) {
              selectedSkills.value = [data.defaultSkillId]
            }
          } catch { /* ignore */ }
          await loadSessions()
        }
      }, 3000)
    }

    // 监听 Agent Window 同步分析结果
    if (window.electronAPI?.onAgentResult) {
      window.electronAPI.onAgentResult((data: { sessionId?: string; summary?: string }) => {
        if (data.sessionId && data.summary) {
          const syncMsg: ChatMessage = {
            id: `sync-${Date.now()}`,
            role: 'assistant',
            content: data.summary,
            timestamp: Date.now(),
            mode: 'full',
            metadata: { syncedFromAgentWindow: true }
          }
          messages.value.push(syncMsg)
          if (data.sessionId !== 'current') {
            currentSessionId.value = data.sessionId
          }
        }
        // 刷新会话列表
        loadSessions()
      })
    }
  }

  // ==================== 会话管理 ====================
  // 内存缓存: 保存当前会话的 messages（含 metadata），避免切换回来时丢失
  const sessionMessageCache = new Map<string, ChatMessage[]>()

  async function loadSessions() {
    try {
      sessions.value = await fetchSessions()
    } catch { /* ignore */ }
  }

  async function switchSession(sessionId: string) {
    if (sessionId === currentSessionId.value) return

    // 缓存当前会话的消息（保留 metadata）
    if (currentSessionId.value && messages.value.length > 0) {
      sessionMessageCache.set(currentSessionId.value, [...messages.value])
    }

    loading.value = true
    try {
      // 优先从缓存读取（保留 dashboard metadata）
      const cached = sessionMessageCache.get(sessionId)
      if (cached && cached.length > 0) {
        messages.value = cached
      } else {
        const msgs = await fetchSessionMessages(sessionId)
        messages.value = msgs
        sessionMessageCache.set(sessionId, msgs)
      }
      currentSessionId.value = sessionId
    } finally {
      loading.value = false
    }
  }

  async function removeSession(sessionId: string) {
    await deleteSession(sessionId)
    sessions.value = sessions.value.filter(s => s.id !== sessionId)
    if (currentSessionId.value === sessionId) {
      newChat()
    }
  }

  async function clearAllSessions() {
    await deleteAllSessions()
    sessions.value = []
    newChat()
  }

  function newChat() {
    messages.value = []
    currentSessionId.value = null
    shouldUpgrade.value = false
    streamReset()
  }

  // ==================== 发送消息 ====================
  function sendMessage(text: string, opts?: { mode?: ChatMode; agentId?: string; symbol?: string; images?: string[] }) {
    const mode = opts?.mode || currentMode.value
    if (!allowedModes.includes(mode)) return

    // 添加用户消息
    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: Date.now(),
      mode,
      images: opts?.images
    }
    messages.value.push(userMsg)

    // 构建请求
    const request: ChatRequest = {
      message: text,
      session_id: currentSessionId.value || undefined,
      mode,
      skills: selectedSkills.value.length > 0 ? selectedSkills.value : undefined,
      agent_id: opts?.agentId,
      symbol: opts?.symbol,
      images: opts?.images
    }

    // 发送 SSE 请求
    streamSend(request)
  }

  function stopStreaming() {
    streamAbort()
  }

  // ==================== 模式切换 ====================
  function setMode(mode: ChatMode) {
    if (allowedModes.includes(mode)) {
      currentMode.value = mode
    }
  }

  // ==================== 监听流完成 → 追加 assistant 消息 ====================
  watch(
    () => streamState.value,
    (newState) => {
      if (newState === 'done' || newState === 'error') {
        const assistantMsg: ChatMessage = {
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          content: streamResult.value.content || streamError.value || '',
          timestamp: Date.now(),
          mode: currentMode.value,
          metadata: {
            thinking: streamResult.value.thinking || undefined,
            tools: streamResult.value.tools.length > 0 ? [...streamResult.value.tools] : undefined,
            stages: streamResult.value.stages.length > 0 ? [...streamResult.value.stages] : undefined,
            debate: streamResult.value.debate || undefined,
            riskDebate: streamResult.value.riskDebate || undefined,
            dashboard: streamResult.value.dashboard || undefined
          }
        }
        messages.value.push(assistantMsg)

        // 更新 session_id
        if (streamResult.value.sessionId) {
          currentSessionId.value = streamResult.value.sessionId
          // 更新缓存，保留完整 metadata（dashboard等）
          sessionMessageCache.set(streamResult.value.sessionId, [...messages.value])
        }

        // 流完成后刷新会话列表，确保历史记录及时更新
        loadSessions()

        // 智能升级提示检测 (仅侧边栏)
        if (showUpgradeHint && newState === 'done') {
          const confidence = streamResult.value.dashboard?.confidence as number | undefined
          if (confidence !== undefined && confidence < 0.6) {
            shouldUpgrade.value = true
          }
        }
      }
    }
  )

  return {
    // 状态
    messages,
    sessions,
    currentSessionId,
    currentMode,
    skills,
    selectedSkills,
    connected,
    loading,
    isStreaming,
    streamState,
    streamResult,
    streamError,
    shouldUpgrade,
    allowedModes,
    // 方法
    init,
    sendMessage,
    stopStreaming,
    setMode,
    newChat,
    switchSession,
    removeSession,
    clearAllSessions,
    loadSessions
  }
}
