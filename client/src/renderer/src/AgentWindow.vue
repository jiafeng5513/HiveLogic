<template>
  <div class="agent-window">
    <!-- 三栏主体 -->
    <div class="agent-window__content">
      <!-- 左栏: 历史会话 -->
      <aside class="agent-window__sidebar">
        <div class="sidebar-header">
          <span class="sidebar-title">历史会话</span>
          <button
            v-if="sessions.length"
            class="sidebar-clear-all"
            @click="onClearAll"
            title="清除全部"
          >🗑️</button>
        </div>
        <div class="sidebar-sessions">
          <div
            v-for="session in sessions"
            :key="session.id"
            class="session-item"
            :class="{ active: session.id === currentSessionId }"
            @click="onSwitchSession(session.id)"
          >
            <div class="session-item__info">
              <span class="session-item__title">{{ session.title || '未命名' }}</span>
              <span class="session-item__time">{{ formatSessionTime(session.updated_at || session.created_at) }}</span>
            </div>
            <button class="session-item__delete" @click.stop="onDeleteSession(session.id)" title="删除">×</button>
          </div>
          <div v-if="!sessions.length" class="sidebar-empty">暂无历史</div>
        </div>
      </aside>

      <!-- 中栏: 对话 + 报告 -->
      <main class="agent-window__main">
        <div class="agent-window__messages" ref="bodyRef">
          <template v-for="msg in messages" :key="msg.id">
            <!-- 用户消息 -->
            <div v-if="msg.role === 'user'" class="aw-msg aw-msg--user">
              <div class="aw-msg__bubble aw-msg__bubble--user">
                <div v-if="msg.images && msg.images.length > 0" class="aw-msg__images">
                  <img
                    v-for="(img, idx) in msg.images"
                    :key="idx"
                    :src="img"
                    alt="attachment"
                    class="aw-msg__image"
                  />
                </div>
                <span v-if="msg.content">{{ msg.content }}</span>
              </div>
            </div>

            <!-- Assistant 消息 -->
            <div v-else class="aw-msg aw-msg--assistant">
              <!-- 思考 -->
              <ThinkingBlock v-if="msg.metadata?.thinking" :content="msg.metadata.thinking" />

              <!-- 辩论面板 -->
              <DebatePanel v-if="msg.metadata?.debate" :debate="msg.metadata.debate" />

              <!-- 风险讨论 -->
              <RiskDebatePanel v-if="msg.metadata?.riskDebate" :risk-debate="msg.metadata.riskDebate" />

              <!-- 正文（dashboard 已有时不重复渲染 JSON） -->
              <StreamRenderer v-if="!msg.metadata?.dashboard" :content="msg.content" />

              <!-- 结果 Dashboard -->
              <DashboardResult
                v-if="msg.metadata?.dashboard"
                :dashboard="msg.metadata.dashboard"
                @annotate="onAnnotate(msg)"
              />
              <!-- 雷达图 & 导出 -->
              <div v-if="msg.metadata?.dashboard" class="aw-dashboard-extras">
                <AnalysisRadar
                  v-if="getRadarDimensions(msg.metadata.dashboard).length >= 3"
                  :dimensions="getRadarDimensions(msg.metadata.dashboard)"
                />
                <AnalysisExport
                  :dashboard="msg.metadata.dashboard"
                  :stock-code="symbolInput"
                  :stock-name="''"
                />
              </div>
            </div>
          </template>

          <!-- 流式 (正在生成) -->
          <div v-if="isStreaming" class="aw-msg aw-msg--assistant aw-msg--streaming">
            <ThinkingBlock v-if="streamResult.thinking" :content="streamResult.thinking" />
            <DebatePanel v-if="streamResult.debate" :debate="streamResult.debate" />
            <RiskDebatePanel v-if="streamResult.riskDebate" :risk-debate="streamResult.riskDebate" />
            <StreamRenderer :content="streamResult.content" :streaming="true" />
          </div>

          <!-- Plan 模式: 等待用户确认 -->
          <PlanCard
            v-if="pendingPlan"
            :plan="pendingPlan"
            :executing="planExecuting"
            @execute="onPlanExecute"
            @modify="onPlanModify"
            @cancel="onPlanCancel"
          />

          <!-- 多股票对比分析 -->
          <CompareAnalysis
            v-if="compareItems.length > 1"
            :items="compareItems"
            @close="compareItems = []"
          />
        </div>

      <!-- 输入区 -->
      <div class="agent-window__input">
        <ChatInput
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
        <button class="new-chat-btn" @click="newChat" title="新对话">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 1v6H2v2h6v6h2V9h6V7H10V1H8z" />
          </svg>
        </button>
      </div>
      </main>

      <!-- 右栏: 分析进度 + 工具调用 -->
      <aside class="agent-window__panel" v-show="showRightPanel">
        <!-- Agent 进度 -->
        <AgentProgress
          v-if="showProgress"
          :stages="streamResult.stages"
          :mode="currentMode"
        />

        <!-- 实时工具调用 -->
        <div v-if="streamResult.tools.length" class="panel-section">
          <div class="panel-section__title">工具调用</div>
          <ToolCallCard v-for="tool in streamResult.tools" :key="tool.name" :tool="tool" />
        </div>
      </aside>
    </div>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import AgentProgress from './components/agent/AgentProgress.vue'
import DebatePanel from './components/agent/DebatePanel.vue'
import RiskDebatePanel from './components/agent/RiskDebatePanel.vue'
import ThinkingBlock from './components/agent/ThinkingBlock.vue'
import ToolCallCard from './components/agent/ToolCallCard.vue'
import StreamRenderer from './components/agent/StreamRenderer.vue'
import DashboardResult from './components/agent/DashboardResult.vue'
import PlanCard from './components/agent/PlanCard.vue'
import ChatInput from './components/sidebar/ChatInput.vue'
import AnalysisRadar from './components/analysis/AnalysisRadar.vue'
import AnalysisExport from './components/analysis/AnalysisExport.vue'
import CompareAnalysis from './components/analysis/CompareAnalysis.vue'
import { useChat } from './composables/useChat'
import type { ChatMode, ChatMessage } from './service/chatService'
import { annotateFromDashboard } from './service/annotationService'

// 浮动助手: 支持快速和深度分析
const allowedModes: ChatMode[] = ['quick', 'deep']

const {
  messages,
  sessions,
  currentSessionId,
  currentMode,
  skills,
  selectedSkills,
  connected,
  isStreaming,
  streamResult,
  init,
  sendMessage,
  stopStreaming,
  setMode,
  newChat,
  switchSession,
  removeSession,
  clearAllSessions
} = useChat({
  defaultMode: 'quick',
  allowedModes,
  showUpgradeHint: false
})

const bodyRef = ref<HTMLElement | null>(null)
const inputRef = ref<InstanceType<typeof ChatInput> | null>(null)
const symbolInput = ref('')
const compareItems = ref<Array<{ code: string; dashboard: Record<string, unknown> }>>([])

// Plan 模式状态
const pendingPlan = ref<{ steps: { description: string; done?: boolean; running?: boolean }[]; estimated_time?: string; estimated_tokens?: number } | null>(null)
const planExecuting = ref(false)

// 显示进度条的模式
const showProgress = computed(() =>
  ['quick', 'deep', 'plan'].includes(currentMode.value) &&
  (isStreaming.value || streamResult.value.stages.length > 0)
)

// 右侧面板: 有进度或工具调用时显示
const showRightPanel = computed(() =>
  showProgress.value || streamResult.value.tools.length > 0
)

// 从 URL 参数获取初始值
onMounted(() => {
  const params = new URLSearchParams(window.location.search)
  const symbol = params.get('symbol')
  const mode = params.get('mode') as ChatMode | null
  const sessionId = params.get('sessionId')

  if (symbol) symbolInput.value = symbol
  if (mode && allowedModes.includes(mode)) setMode(mode)

  init()

  // 如果带了 symbol 参数，自动开始分析
  if (symbol) {
    nextTick(() => {
      sendMessage(`分析 ${symbol}`, { symbol, mode: currentMode.value })
    })
  }
})

// 自动滚动 — 监听所有可能导致内容变化的数据源
const _scrollTrigger = computed(() => [
  messages.value.length,
  streamResult.value.content,
  streamResult.value.thinking,
  streamResult.value.stages.length,
  streamResult.value.tools.length,
])
watch(_scrollTrigger, () => {
  nextTick(() => {
    if (bodyRef.value) {
      bodyRef.value.scrollTop = bodyRef.value.scrollHeight
    }
  })
})

function onSend(text: string, images: string[] = []) {
  sendMessage(text, { symbol: symbolInput.value || undefined, images: images.length > 0 ? images : undefined })
}

function onSymbolEnter() {
  if (symbolInput.value.trim()) {
    sendMessage(`分析 ${symbolInput.value}`, { symbol: symbolInput.value, mode: currentMode.value })
  }
}

function onSkillToggle(skillId: string) {
  if (selectedSkills.value.includes(skillId)) {
    selectedSkills.value = []
  } else {
    selectedSkills.value = [skillId]
  }
}

function onAnnotate(msg: ChatMessage) {
  const dashboard = msg.metadata?.dashboard
  if (dashboard) {
    const symbol = symbolInput.value || (dashboard as Record<string, unknown>).stock_name as string || ''
    if (!symbol) return
    annotateFromDashboard(symbol, dashboard, 'current')
  }
}

function onContinueChat() {
  // IPC: 通知侧边栏聚焦
  if (window.electronAPI?.invoke) {
    window.electronAPI.invoke('agent:sync-result', {
      sessionId: messages.value.length > 0 ? 'current' : null,
      summary: streamResult.value.content?.slice(0, 200)
    })
  }
}

// Plan 模式: 监听 plan_ready 事件 (dashboard.plan)
watch(() => streamResult.value.dashboard, (dashboard) => {
  if (dashboard && (dashboard as Record<string, unknown>).plan) {
    pendingPlan.value = (dashboard as Record<string, unknown>).plan as typeof pendingPlan.value
  }
})

function onPlanExecute() {
  if (!pendingPlan.value) return
  planExecuting.value = true
  pendingPlan.value = null
  // 发送确认执行，使用 full 模式
  sendMessage('确认执行分析计划', { symbol: symbolInput.value || undefined, mode: 'full' })
  planExecuting.value = false
}

function onPlanModify() {
  // 保留计划在界面上，用户可在输入框修改后重新提交
  pendingPlan.value = null
}

function onPlanCancel() {
  pendingPlan.value = null
  stopStreaming()
}

// ==================== 会话管理 ====================
function onSwitchSession(sessionId: string) {
  switchSession(sessionId)
}

function onDeleteSession(sessionId: string) {
  removeSession(sessionId)
}

function onClearAll() {
  if (confirm('确定清除全部历史记录？此操作不可撤销。')) {
    clearAllSessions()
  }
}

/** 将 ISO 时间字符串格式化为友好的相对/绝对时间 */
function formatSessionTime(isoStr: string | undefined): string {
  if (!isoStr) return ''
  const date = new Date(isoStr)
  if (isNaN(date.getTime())) return ''
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  const diffHour = Math.floor(diffMs / 3600000)
  const diffDay = Math.floor(diffMs / 86400000)

  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin}分钟前`
  if (diffHour < 24) return `${diffHour}小时前`
  if (diffDay < 7) return `${diffDay}天前`
  // 超过7天显示日期
  const m = date.getMonth() + 1
  const d = date.getDate()
  return `${m}/${d}`
}

// ==================== 雷达图维度提取 ====================
function getRadarDimensions(dashboard: Record<string, unknown>) {
  const dims: { key: string; label: string; value: number }[] = []
  const d = dashboard as Record<string, any>
  if (d.confidence != null) dims.push({ key: 'confidence', label: '置信度', value: Math.round(d.confidence * 100) })
  if (d.market_context) {
    const mc = d.market_context
    if (mc.strength) {
      const strengthMap: Record<string, number> = { strong: 80, moderate: 55, weak: 30 }
      dims.push({ key: 'strength', label: '趋势', value: strengthMap[mc.strength] || 50 })
    }
    if (mc.sentiment) {
      const sentMap: Record<string, number> = { bullish: 80, neutral: 50, bearish: 25 }
      dims.push({ key: 'sentiment', label: '情绪', value: sentMap[mc.sentiment] || 50 })
    }
  }
  if (d.risk_assessment?.max_acceptable_position) {
    const pos = parseInt(d.risk_assessment.max_acceptable_position)
    if (!isNaN(pos)) dims.push({ key: 'position', label: '仓位', value: pos })
  }
  if (d.debate_summary?.confidence_shift != null) {
    dims.push({ key: 'debate', label: '辩论', value: Math.min(100, Math.max(0, 50 + d.debate_summary.confidence_shift * 50)) })
  }
  if (d.skill_opinions?.length) {
    const buyCount = d.skill_opinions.filter((s: any) => ['buy', '买入'].includes(s.signal)).length
    dims.push({ key: 'skills', label: '策略', value: Math.round((buyCount / d.skill_opinions.length) * 100) })
  }
  return dims
}

// ==================== 对比分析收集 ====================
watch(
  () => streamResult.value.dashboard,
  (dashboard) => {
    if (dashboard && symbolInput.value) {
      const existing = compareItems.value.find(i => i.code === symbolInput.value)
      if (!existing) {
        compareItems.value.push({ code: symbolInput.value, dashboard: dashboard as Record<string, unknown> })
      }
    }
  }
)
</script>

<style scoped>
.agent-window {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #1e1e1e;
  color: #e0e0e0;
}

/* ===== 三栏布局 ===== */
.agent-window__content {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* 左栏: 历史会话 */
.agent-window__sidebar {
  width: 200px;
  min-width: 160px;
  border-right: 1px solid #333;
  display: flex;
  flex-direction: column;
  background: #1a1a1a;
  flex-shrink: 0;
}

.sidebar-header {
  padding: 10px 12px;
  font-size: 12px;
  font-weight: 600;
  color: #999;
  border-bottom: 1px solid #2a2a2a;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sidebar-clear-all {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 12px;
  padding: 2px 4px;
  opacity: 0.6;
  transition: opacity 0.15s;
}

.sidebar-clear-all:hover {
  opacity: 1;
}

.sidebar-sessions {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
  scrollbar-width: thin;
  scrollbar-color: #444 transparent;
}

.session-item {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 12px;
  color: #bbb;
  border-left: 3px solid transparent;
  transition: background 0.15s;
}

.session-item:hover {
  background: #2a2a2a;
}

.session-item.active {
  background: #1e3a5f;
  border-left-color: #4ec9b0;
  color: #fff;
}

.session-item__info {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.session-item__title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-item__time {
  font-size: 10px;
  color: #666;
}

.session-item__delete {
  background: none;
  border: none;
  color: #666;
  cursor: pointer;
  font-size: 14px;
  padding: 0 4px;
  opacity: 0;
  transition: opacity 0.15s;
}

.session-item:hover .session-item__delete {
  opacity: 1;
}

.session-item__delete:hover {
  color: #f44;
}

.sidebar-empty {
  padding: 16px 12px;
  font-size: 12px;
  color: #666;
  font-style: italic;
}

/* 中栏: 对话主体 */
.agent-window__main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.agent-window__messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  scrollbar-width: thin;
  scrollbar-color: #444 transparent;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* 右栏: 进度 + 工具 */
.agent-window__panel {
  width: 260px;
  min-width: 200px;
  border-left: 1px solid #333;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  background: #1a1a1a;
  overflow-y: auto;
  flex-shrink: 0;
  scrollbar-width: thin;
  scrollbar-color: #444 transparent;
}

.panel-section__title {
  font-size: 11px;
  font-weight: 600;
  color: #999;
  margin-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* ===== 消息样式 ===== */
.aw-msg--user {
  display: flex;
  justify-content: flex-end;
}

.aw-msg__bubble--user {
  background: #0e639c;
  color: #fff;
  padding: 8px 14px;
  border-radius: 12px 12px 4px 12px;
  max-width: 70%;
  font-size: 13px;
  line-height: 1.5;
}

.aw-msg__images {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 6px;
}

.aw-msg__image {
  width: 120px;
  height: 120px;
  object-fit: cover;
  border-radius: 6px;
  cursor: pointer;
  transition: transform 0.15s;
}

.aw-msg__image:hover {
  transform: scale(1.03);
}

.aw-msg--assistant {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.aw-msg--streaming {
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0.5; }
  to { opacity: 1; }
}

.agent-window__input {
  flex-shrink: 0;
  border-top: 1px solid #333;
  padding: 8px 16px;
  display: grid;
  grid-template-columns: auto 1fr;
  grid-template-rows: auto auto;
  gap: 6px 8px;
}

.agent-window__input > :deep(.chat-input-area) {
  display: contents;
  border-top: none;
  padding: 0;
}

.agent-window__input > :deep(.chat-input-area) > .chat-input-toolbar {
  grid-column: 1 / -1;
  margin-bottom: 0;
}

.agent-window__input > :deep(.chat-input-area) > .chat-input-wrapper {
  grid-column: 2;
  grid-row: 2;
}

.new-chat-btn {
  grid-column: 1;
  grid-row: 2;
  aspect-ratio: 1;
  background: none;
  border: 1px solid #444;
  border-radius: 6px;
  color: #666;
  cursor: pointer;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.15s, border-color 0.15s;
}

.new-chat-btn:hover {
  color: #4ec9b0;
  border-color: #4ec9b0;
}

.aw-dashboard-extras {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-top: 8px;
  flex-wrap: wrap;
}
</style>
