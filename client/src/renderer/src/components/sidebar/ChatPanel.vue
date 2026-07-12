<template>
  <div class="chat-panel">
    <!-- 头部 -->
    <div class="chat-panel__header">
      <span class="status-dot" :class="connected ? 'connected' : 'disconnected'"></span>
      <span class="header-title">聊天</span>
      <div class="header-actions">
        <button class="header-btn" title="历史会话" @click="showSessions = true">☰</button>
        <button class="header-btn" title="新对话" @click="newChat">+</button>
      </div>
    </div>

    <!-- 会话列表 (覆盖) -->
    <SessionList
      v-if="showSessions"
      :sessions="sessions"
      :current-session-id="currentSessionId"
      @close="showSessions = false"
      @switch="onSwitchSession"
      @delete="onDeleteSession"
    />

    <!-- 消息列表 -->
    <ChatMessageList
      v-show="!showSessions"
      :messages="messages"
      :is-streaming="isStreaming"
      :streaming-message="streamingMessage"
      :should-upgrade="shouldUpgrade"
      :quick-questions="quickQuestions"
      @quick-send="onQuickSend"
      @upgrade="openAgentWindow"
    />

    <!-- 输入区 -->
    <ChatInput
      v-show="!showSessions"
      ref="inputRef"
      :current-mode="currentMode"
      :allowed-modes="allowedModes"
      :skills="skills"
      :selected-skills="selectedSkills"
      :is-streaming="isStreaming"
      @send="onSend"
      @stop="stopStreaming"
      @mode-change="setMode"
      @skill-toggle="onSkillToggle"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import ChatMessageList from './ChatMessageList.vue'
import ChatMessage from './ChatMessage.vue'
import ChatInput from './ChatInput.vue'
import SessionList from './SessionList.vue'
import { useChat } from '../../composables/useChat'
import type { ChatMessage as ChatMessageType, ChatMode } from '../../service/chatService'

const props = defineProps<{
  /** 是否完整模式 (Agent Window 使用全部模式) */
  fullMode?: boolean
}>()

const emit = defineEmits<{
  'open-agent-window': [options?: { symbol?: string; sessionId?: string }]
}>()

// 初始化 chat composable
const allowedModes: ChatMode[] = props.fullMode
  ? ['chat', 'quick', 'deep', 'plan']
  : ['chat', 'quick']

const {
  messages,
  sessions,
  currentSessionId,
  currentMode,
  skills,
  selectedSkills,
  connected,
  isStreaming,
  streamState,
  streamResult,
  streamError,
  shouldUpgrade,
  init,
  sendMessage,
  stopStreaming,
  setMode,
  newChat,
  switchSession,
  removeSession,
  loadSessions
} = useChat({
  defaultMode: 'chat',
  allowedModes,
  showUpgradeHint: !props.fullMode
})

const inputRef = ref<InstanceType<typeof ChatInput> | null>(null)
const showSessions = ref(false)

// 快捷问题
const quickQuestions = computed(() => [
  { icon: '📈', text: '分析贵州茅台趋势', skill: 'bull_trend' },
  { icon: '🔮', text: '用缠论分析茅台', skill: 'chan_theory' },
  { icon: '🌊', text: '波浪理论看宁德时代', skill: 'wave_theory' },
  { icon: '📰', text: '分析贵州茅台最新舆情' }
])

// 流式消息 (正在生成的 assistant 消息)
const streamingMessage = computed<ChatMessageType | null>(() => {
  if (!isStreaming.value) return null
  return {
    id: 'streaming',
    role: 'assistant',
    content: streamResult.value.content,
    timestamp: Date.now(),
    mode: currentMode.value,
    metadata: {
      thinking: streamResult.value.thinking || undefined,
      tools: streamResult.value.tools.length > 0 ? [...streamResult.value.tools] : undefined,
      stages: streamResult.value.stages.length > 0 ? [...streamResult.value.stages] : undefined,
      debate: streamResult.value.debate || undefined,
      riskDebate: streamResult.value.riskDebate || undefined
    }
  }
})

// ==================== 事件处理 ====================

function onSend(text: string, images: string[] = []) {
  sendMessage(text, { images: images.length > 0 ? images : undefined })
}

function onQuickSend(text: string, skill?: string) {
  if (skill) {
    selectedSkills.value = [skill]
  }
  sendMessage(text)
}

function onSkillToggle(skillId: string) {
  if (selectedSkills.value.includes(skillId)) {
    selectedSkills.value = []
  } else {
    selectedSkills.value = [skillId]
  }
}

function onSwitchSession(sessionId: string) {
  switchSession(sessionId)
  showSessions.value = false
}

function onDeleteSession(sessionId: string) {
  removeSession(sessionId)
}

function openAgentWindow() {
  if (window.electronAPI?.invoke) {
    window.electronAPI.invoke('agent:toggle-window', {
      sessionId: currentSessionId.value,
      symbol: undefined
    })
  }
  emit('open-agent-window', { sessionId: currentSessionId.value || undefined })
}

// ==================== 生命周期 ====================
onMounted(() => {
  init()
})
</script>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #1e1e1e;
  position: relative;
}

.chat-panel__header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid #333;
  flex-shrink: 0;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot.connected {
  background: #4ec9b0;
}

.status-dot.disconnected {
  background: #666;
}

.header-title {
  font-size: 13px;
  color: #ccc;
  flex: 1;
}

.header-actions {
  display: flex;
  gap: 4px;
}

.header-btn {
  background: none;
  border: none;
  color: #888;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 4px;
  font-size: 14px;
  transition: background 0.15s, color 0.15s;
}

.header-btn:hover {
  background: #333;
  color: #fff;
}
</style>
