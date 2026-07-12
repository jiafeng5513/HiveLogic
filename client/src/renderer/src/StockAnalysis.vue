<template>
  <div class="stock-analysis view-container">
    <!-- 左侧历史记录 -->
    <aside class="side-panel" ref="sidePanelRef">
      <div class="side-panel-resize-handle"></div>
      <div class="side-panel-header">
        <span>分析历史</span>
      </div>
      <div class="side-panel-content">
        <div class="history-list">
          <div
            v-for="task in taskList"
            :key="task.task_id"
            class="history-item"
            :class="{ active: currentTaskId === task.task_id }"
            @click="loadTaskResult(task)"
          >
            <div class="history-item-header">
              <span class="stock-code">{{ task.stock_code }}</span>
              <span class="stock-name" v-if="task.stock_name">{{ task.stock_name }}</span>
            </div>
            <div class="history-item-meta">
              <span
                class="status-badge"
                :class="task.status"
              >{{ statusText(task.status) }}</span>
              <span class="time">{{ formatTime(task.created_at) }}</span>
            </div>
            <div class="progress-bar" v-if="task.status === 'processing'">
              <div class="progress-fill" :style="{ width: (task.progress || 0) + '%' }"></div>
            </div>
          </div>
          <div v-if="taskList.length === 0" class="history-empty">暂无分析记录</div>
        </div>
      </div>
    </aside>

    <!-- 主内容区 -->
    <div class="main-view">
      <!-- 顶部搜索栏 -->
      <div class="search-bar">
        <div class="mode-toggle">
          <button
            class="mode-btn"
            :class="{ active: analysisMode === 'quick' }"
            @click="analysisMode = 'quick'"
          >⚡ 快速</button>
          <button
            class="mode-btn"
            :class="{ active: analysisMode === 'deep' }"
            @click="analysisMode = 'deep'"
          >🔬 深度</button>
        </div>
        <div class="search-input-wrapper">
          <input
            ref="searchInput"
            v-model="searchQuery"
            type="text"
            class="search-input"
            placeholder="输入股票代码或名称，如 600519、贵州茅台、gzmt"
            @keydown.enter="handleAnalyze"
            @input="onSearchInput"
            @focus="showSuggestions = suggestions.length > 0"
            @blur="hideSuggestionsDelayed"
          />
          <div class="suggestions" v-show="showSuggestions && suggestions.length > 0">
            <div
              v-for="(item, index) in suggestions"
              :key="index"
              class="suggestion-item"
              @mousedown.prevent="selectSuggestion(item)"
            >
              <span class="suggestion-code">{{ item.code }}</span>
              <span class="suggestion-name">{{ item.name }}</span>
            </div>
          </div>
        </div>
        <button class="analyze-btn" @click="handleAnalyze" :disabled="analyzing || agentStreaming || serviceStatus !== 'connected'" :title="serviceStatus !== 'connected' ? 'DSA 服务未连接' : ''">
          {{ (analyzing || agentStreaming) ? '分析中...' : '分析' }}
        </button>
      </div>

      <!-- 内容区 -->
      <div class="main-view-content content-area">
        <!-- 欢迎页 -->
        <div v-if="!reportData && !analyzing && !agentStreaming && !agentDashboard && !agentFallbackContent" class="welcome">
          <div class="welcome-icon">📊</div>
          <h2>股票智能分析</h2>
          <p>输入股票代码或名称，AI 将从技术面、基本面、舆情等多维度进行深度分析</p>
          <div class="quick-stocks">
            <span class="quick-label">快速分析：</span>
            <button
              v-for="stock in quickStocks"
              :key="stock.code"
              class="quick-btn"
              @click="quickAnalyze(stock)"
            >{{ stock.name }}</button>
          </div>
        </div>

        <!-- Agent 流式分析中 (deep/quick 模式走 agent 管道) -->
        <div v-if="agentStreaming" class="analyzing-panel">
          <div class="analyzing-header">
            <div class="analyzing-spinner"></div>
            <span>正在{{ analysisMode === 'deep' ? '深度' : '快速' }}分析 {{ currentStockCode }}
              <template v-if="currentStockName">（{{ currentStockName }}）</template>
            </span>
          </div>
          <div class="agent-stream-content" v-if="agentStreamResult.content">
            <StreamRenderer :content="agentStreamResult.content" :streaming="true" />
          </div>
        </div>

        <!-- Agent 分析结果 (Dashboard) -->
        <div v-if="agentDashboard && !agentStreaming" class="report-container">
          <div class="report-header">
            <h2>
              {{ reportStockCode }}
              <span v-if="reportStockName">{{ reportStockName }}</span>
            </h2>
            <div class="report-header-actions">
              <span class="analysis-mode-badge">{{ analysisMode === 'deep' ? '🔬 深度分析' : '⚡ 快速分析' }}</span>
              <AnalysisExport
                :dashboard="agentDashboard"
                :stock-code="reportStockCode"
                :stock-name="reportStockName"
              />
            </div>
          </div>
          <DashboardResult
            :dashboard="agentDashboard"
            @annotate="onAnnotateDashboard"
            @chat="onFollowUp"
          />
          <!-- 对比分析 -->
          <CompareAnalysis
            v-if="compareItems.length > 1"
            :items="compareItems"
            @close="compareItems = []"
          />
        </div>

        <!-- Agent 分析结果降级显示 (无 dashboard 但有 content) -->
        <div v-if="!agentDashboard && agentFallbackContent && !agentStreaming" class="report-container">
          <div class="report-header">
            <h2>
              {{ reportStockCode }}
              <span v-if="reportStockName">{{ reportStockName }}</span>
            </h2>
            <div class="report-header-actions">
              <span class="analysis-mode-badge fallback">⚠️ 文本模式</span>
            </div>
          </div>
          <div class="agent-fallback-content">
            <StreamRenderer :content="agentFallbackContent" :streaming="false" />
          </div>
        </div>

        <!-- 分析进度 (传统任务模式兜底) -->
        <div v-if="analyzing && !agentStreaming" class="analyzing-panel">
          <div class="analyzing-header">
            <div class="analyzing-spinner"></div>
            <span>正在分析 {{ currentStockCode }}
              <template v-if="currentStockName">（{{ currentStockName }}）</template>
            </span>
          </div>
          <div class="analyzing-progress">
            <div class="analyzing-progress-bar">
              <div class="analyzing-progress-fill" :style="{ width: currentProgress + '%' }"></div>
            </div>
            <span class="analyzing-progress-text">{{ currentProgress }}%</span>
          </div>
          <div class="analyzing-message" v-if="currentMessage">{{ currentMessage }}</div>
        </div>

        <!-- 分析报告 -->
        <div v-if="reportData && !analyzing" class="report-container">
          <div class="report-header">
            <h2>
              {{ reportStockCode }}
              <span v-if="reportStockName">{{ reportStockName }}</span>
            </h2>
            <span class="report-time" v-if="reportTime">{{ reportTime }}</span>
          </div>
          <ReportOverview
            :meta="reportData.meta"
            :summary="reportData.summary"
            :conclusion="reportData.conclusion"
          />
          <StrategyGrid
            :strategy="reportData.strategyPoints"
            :battle-plan="reportData.battlePlan"
          />
          <ReportNews :items="newsItems" />
          <div class="report-sections">
            <CollapsiblePanel
              v-for="section in reportSections"
              :key="section.key"
              :title="section.title"
              :default-open="section.defaultOpen !== false"
            >
              <div class="report-body" v-html="section.html"></div>
            </CollapsiblePanel>
          </div>
          <div class="report-footer" v-if="reportData.metaInfo">
            <span class="meta-text">{{ reportData.metaInfo }}</span>
          </div>
        </div>

        <!-- 错误提示 -->
        <div v-if="errorMsg" class="error-panel">
          <div class="error-icon">⚠️</div>
          <div class="error-text">{{ errorMsg }}</div>
          <button class="retry-btn" @click="errorMsg = ''">关闭</button>
        </div>
      </div>
    </div>

    <!-- 右侧面板: 实时进度 + 追问 -->
    <aside class="right-panel" v-show="showRightPanel">
      <div class="right-panel-header">
        <span>实时进度</span>
        <button class="panel-collapse-btn" @click="rightPanelVisible = false" title="折叠">✕</button>
      </div>
      <div class="right-panel-content">
        <AnalysisSideProgress
          :stages="agentStreamResult.stages"
          :debate="agentStreamResult.debate"
          :risk-debate="agentStreamResult.riskDebate"
          :thinking="agentStreamResult.thinking"
          :mode="analysisMode"
          :plan="agentStreamResult.plan"
          :step-reasoning="agentStreamResult.stepReasoning"
        />
        <AnalysisRadar
          v-if="radarDimensions.length > 0 && !agentStreaming"
          :dimensions="radarDimensions"
        />
        <FollowUpInput
          v-if="agentDashboard && !agentStreaming"
          :stock-code="currentStockCode"
          :signal="agentDashboard?.signal"
          @send="onFollowUpSend"
        />
      </div>
    </aside>
  </div>
</template>

<script setup>
import '@renderer/styles/layout.css'
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useSidePanelWidth } from './composables/useSidePanelWidth'
import { useChatStream } from './composables/useChatStream'
import { getApiBase } from './service/serverConfig'
import MarkdownIt from 'markdown-it'

import hljs from 'highlight.js/lib/core'
import javascript from 'highlight.js/lib/languages/javascript'
import python from 'highlight.js/lib/languages/python'
import json from 'highlight.js/lib/languages/json'
import bash from 'highlight.js/lib/languages/bash'
import sql from 'highlight.js/lib/languages/sql'
import 'highlight.js/styles/github-dark.css'

hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('python', python)
hljs.registerLanguage('json', json)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('sql', sql)
import ReportOverview from './components/report/ReportOverview.vue'
import StrategyGrid from './components/report/StrategyGrid.vue'
import CollapsiblePanel from './components/report/CollapsiblePanel.vue'
import ReportNews from './components/report/ReportNews.vue'
import StreamRenderer from './components/agent/StreamRenderer.vue'
import DashboardResult from './components/agent/DashboardResult.vue'
import AnalysisSideProgress from './components/analysis/AnalysisSideProgress.vue'
import FollowUpInput from './components/analysis/FollowUpInput.vue'
import AnalysisRadar from './components/analysis/AnalysisRadar.vue'
import AnalysisExport from './components/analysis/AnalysisExport.vue'
import CompareAnalysis from './components/analysis/CompareAnalysis.vue'

const sidePanelRef = ref(null)
useSidePanelWidth(sidePanelRef)

const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
  breaks: true,
  highlight: function (str, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return '<pre class="hljs"><code>' + hljs.highlight(str, { language: lang }).value + '</code></pre>'
      } catch (_) { /* ignore */ }
    }
    return ''
  }
})

// 状态
const searchQuery = ref('')
const searchInput = ref(null)
const suggestions = ref([])
const showSuggestions = ref(false)
const analyzing = ref(false)
const currentStockCode = ref('')
const currentStockName = ref('')
const currentProgress = ref(0)
const currentMessage = ref('')
const currentTaskId = ref('')
const reportHtml = ref('')
const reportData = ref(null)
const reportSections = ref([])
const newsItems = ref([])
const reportStockCode = ref('')
const reportStockName = ref('')
const reportTime = ref('')
const errorMsg = ref('')
const taskList = ref([])
const serviceStatus = ref('unknown') // unknown, connected, disconnected
let searchTimer = null
let eventSource = null

// Agent 模式 & 流式分析状态
const analysisMode = ref('deep') // 'quick' | 'deep'
const rightPanelVisible = ref(true)
const agentDashboard = ref(null)
const agentFallbackContent = ref('') // 降级内容：无 dashboard 时的 markdown 输出
const { state: agentState, result: agentStreamResult, error: agentError, send: agentSend, abort: agentAbort } = useChatStream()
const agentStreaming = computed(() =>
  agentState.value !== 'idle' && agentState.value !== 'done' && agentState.value !== 'error'
)
const showRightPanel = computed(() =>
  rightPanelVisible.value && (agentStreaming.value || agentDashboard.value || agentFallbackContent.value)
)

// 监听 agent stream 完成 → 提取 dashboard
watch(agentState, (newState) => {
  if (newState === 'done') {
    if (agentStreamResult.value.dashboard) {
      agentDashboard.value = agentStreamResult.value.dashboard
      reportStockCode.value = currentStockCode.value
      reportStockName.value = currentStockName.value
    } else if (agentStreamResult.value.content) {
      // 降级逻辑：后端未返回 dashboard 但有 content，仍保留内容供 StreamRenderer 显示
      agentFallbackContent.value = agentStreamResult.value.content
      reportStockCode.value = currentStockCode.value
      reportStockName.value = currentStockName.value
    }
    analyzing.value = false
  } else if (newState === 'error') {
    errorMsg.value = agentError.value || '分析失败'
    analyzing.value = false
  }
})

// 对比分析列表
const compareItems = ref([])

// 雷达图维度 — 从 dashboard 提取
const radarDimensions = computed(() => {
  const d = agentDashboard.value
  if (!d) return []
  const dims = []
  if (d.confidence != null) dims.push({ key: 'confidence', label: '置信度', value: Math.round(d.confidence * 100) })
  if (d.market_context) {
    const mc = d.market_context
    if (mc.strength) {
      const strengthMap = { strong: 80, moderate: 55, weak: 30 }
      dims.push({ key: 'strength', label: '趋势', value: strengthMap[mc.strength] || 50 })
    }
    if (mc.sentiment) {
      const sentMap = { bullish: 80, neutral: 50, bearish: 25 }
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
    const buyCount = d.skill_opinions.filter(s => ['buy', '买入'].includes(s.signal)).length
    dims.push({ key: 'skills', label: '策略', value: Math.round((buyCount / d.skill_opinions.length) * 100) })
  }
  // 保证至少3个维度才显示雷达
  return dims.length >= 3 ? dims : []
})

const quickStocks = [
  { code: '600519', name: '贵州茅台' },
  { code: '300750', name: '宁德时代' },
  { code: '002594', name: '比亚迪' },
  { code: '601318', name: '中国平安' }
]

// 后端地址统一走 serverConfig（支持本地/远程模式切换），不再硬编码端口
function getBaseUrl() {
  return getApiBase()
}

// 检查服务状态
async function checkService() {
  try {
    const resp = await fetch(`${getBaseUrl()}/api/health`, { signal: AbortSignal.timeout(3000) })
    if (resp.ok) {
      serviceStatus.value = 'connected'
      return true
    }
  } catch {
    // ignore
  }
  serviceStatus.value = 'disconnected'
  return false
}

// 搜索防抖
function onSearchInput() {
  clearTimeout(searchTimer)
  const q = searchQuery.value.trim()
  if (!q) {
    suggestions.value = []
    showSuggestions.value = false
    return
  }
  // 本地快速匹配（如果是纯数字直接跳过联想）
  if (/^\d{6}$/.test(q)) {
    suggestions.value = []
    showSuggestions.value = false
    return
  }
  searchTimer = setTimeout(() => fetchSuggestions(q), 300)
}

async function fetchSuggestions(query) {
  if (serviceStatus.value !== 'connected') return
  try {
    const resp = await fetch(
      `${getBaseUrl()}/api/v1/stocks/search?q=${encodeURIComponent(query)}&limit=8`,
      { signal: AbortSignal.timeout(3000) }
    )
    if (resp.ok) {
      const data = await resp.json()
      suggestions.value = data.results || data || []
      showSuggestions.value = suggestions.value.length > 0
    }
  } catch {
    suggestions.value = []
  }
}

function selectSuggestion(item) {
  searchQuery.value = item.code
  currentStockName.value = item.name || ''
  suggestions.value = []
  showSuggestions.value = false
  handleAnalyze()
}

function hideSuggestionsDelayed() {
  setTimeout(() => {
    showSuggestions.value = false
  }, 200)
}

// 触发分析
async function handleAnalyze() {
  const code = searchQuery.value.trim()
  if (!code) return

  if (serviceStatus.value !== 'connected') {
    errorMsg.value = 'DSA 服务未连接，请先在设置中启动服务'
    return
  }

  // 重置状态
  currentStockCode.value = code
  errorMsg.value = ''
  reportData.value = null
  reportSections.value = []
  newsItems.value = []
  agentDashboard.value = null
  agentFallbackContent.value = ''
  rightPanelVisible.value = true

  // 使用 Agent 管道 (useChatStream) 进行分析
  agentSend({
    message: `分析 ${code}`,
    mode: analysisMode.value,
    symbol: code
  })
}

// 追问发送
function onFollowUpSend(text) {
  agentSend({
    message: text,
    mode: analysisMode.value,
    symbol: currentStockCode.value
  })
  agentDashboard.value = null
  agentFallbackContent.value = ''
  rightPanelVisible.value = true
}

function onFollowUp() {
  rightPanelVisible.value = true
}

function onAnnotateDashboard() {
  // TODO: 联动 K 线图标注
}

// 快速分析
function quickAnalyze(stock) {
  searchQuery.value = stock.code
  currentStockName.value = stock.name
  handleAnalyze()
}

// SSE 连接
function connectSSE() {
  if (eventSource) {
    eventSource.close()
  }

  const url = `${getBaseUrl()}/api/v1/analysis/tasks/stream`
  eventSource = new EventSource(url)

  eventSource.addEventListener('connected', () => {
    console.log('[SSE] 已连接到任务流')
  })

  eventSource.addEventListener('task_created', (e) => {
    const data = JSON.parse(e.data)
    console.log('[SSE] 任务已创建:', data)
    fetchTaskList()
  })

  eventSource.addEventListener('task_started', (e) => {
    const data = JSON.parse(e.data)
    if (data.task_id === currentTaskId.value) {
      currentMessage.value = '分析已开始...'
      currentProgress.value = 5
    }
    updateTaskInList(data.task_id, { status: 'processing' })
  })

  eventSource.addEventListener('task_progress', (e) => {
    const data = JSON.parse(e.data)
    if (data.task_id === currentTaskId.value) {
      currentProgress.value = data.progress || 0
      currentMessage.value = data.message || ''
    }
    updateTaskInList(data.task_id, { progress: data.progress, message: data.message })
  })

  eventSource.addEventListener('task_completed', async (e) => {
    const data = JSON.parse(e.data)
    console.log('[SSE] 任务完成:', data.task_id)
    updateTaskInList(data.task_id, { status: 'completed' })
    fetchTaskList()
    if (data.task_id === currentTaskId.value) {
      currentProgress.value = 100
      currentMessage.value = '分析完成，加载报告...'
      // SSE 事件不携带报告内容，通过 history 端点获取完整报告
      try {
        const resp = await fetch(`${getBaseUrl()}/api/v1/history/${data.task_id}`)
        if (resp.ok) {
          const reportData = await resp.json()
          analyzing.value = false
          renderReport(reportData)
          fetchNews(data.task_id)
        } else {
          analyzing.value = false
          errorMsg.value = '加载报告失败'
        }
      } catch (err) {
        analyzing.value = false
        errorMsg.value = `加载报告失败: ${err.message}`
      }
    }
  })

  eventSource.addEventListener('task_failed', (e) => {
    const data = JSON.parse(e.data)
    console.error('[SSE] 任务失败:', data)
    if (data.task_id === currentTaskId.value) {
      analyzing.value = false
      errorMsg.value = `分析失败: ${data.error || '未知错误'}`
    }
    updateTaskInList(data.task_id, { status: 'failed', error: data.error })
    fetchTaskList()
  })

  eventSource.onerror = () => {
    console.warn('[SSE] 连接中断，5秒后重连...')
    eventSource.close()
    eventSource = null
    setTimeout(() => {
      if (serviceStatus.value === 'connected') {
        connectSSE()
      }
    }, 5000)
  }
}

// 获取新闻资讯
async function fetchNews(taskId) {
  newsItems.value = []
  if (!taskId || serviceStatus.value !== 'connected') return
  try {
    const resp = await fetch(`${getBaseUrl()}/api/v1/history/${taskId}/news?limit=10`, {
      signal: AbortSignal.timeout(5000)
    })
    if (resp.ok) {
      const data = await resp.json()
      newsItems.value = data.items || []
    }
  } catch {
    // 新闻获取失败不影响主报告展示
  }
}

// 渲染报告
// /api/v1/history/{task_id} 返回: { meta, summary, strategy, details }
// details.raw_result 包含 LLM 原始输出（dashboard、各类分析文本等）
function renderReport(data) {
  const meta = data.meta || {}
  const summary = data.summary || {}
  const strategy = data.strategy || {}
  const details = data.details || {}
  const raw = details.raw_result || {}
  const dashboard = raw.dashboard || {}

  reportStockCode.value = meta.stock_code || raw.code || currentStockCode.value
  reportStockName.value = meta.stock_name || raw.name || currentStockName.value
  reportTime.value = meta.created_at ? formatTime(meta.created_at) : ''

  const st = strategy.ideal_buy ? strategy : (dashboard.battle_plan?.sniper_points || {})

  // 构建元信息
  const metaParts = []
  if (meta.report_type) metaParts.push(`报告类型: ${meta.report_type}`)
  if (meta.model_used) metaParts.push(`模型: ${meta.model_used}`)
  if (meta.current_price != null) metaParts.push(`当前价: ${meta.current_price}`)
  if (meta.change_pct != null) metaParts.push(`涨跌幅: ${meta.change_pct}%`)

  // 结构化数据供组件使用
  reportData.value = {
    meta: {
      ...meta,
      current_price: meta.current_price,
      change_pct: meta.change_pct
    },
    summary: {
      ...summary,
      operation_advice: summary.operation_advice || raw.operation_advice,
      trend_prediction: summary.trend_prediction || raw.trend_prediction,
      sentiment_score: summary.sentiment_score != null ? summary.sentiment_score : raw.sentiment_score,
      sentiment_label: summary.sentiment_label || raw.confidence_level,
      analysis_summary: summary.analysis_summary || raw.analysis_summary
    },
    conclusion: dashboard.core_conclusion || null,
    strategyPoints: st,
    battlePlan: dashboard.battle_plan || {},
    metaInfo: metaParts.length > 0 ? metaParts.join(' · ') : ''
  }

  // 构建可折叠的详细分析区域
  const sections = []

  // 数据透视
  const dp = dashboard.data_perspective
  if (dp) {
    const lines = []
    if (dp.trend_status) {
      const ts = dp.trend_status
      lines.push(`**趋势**: ${ts.ma_alignment || ''} (强度 ${ts.trend_score || '-'}/100)\n`)
    }
    if (dp.price_position) {
      const pp = dp.price_position
      lines.push('| 指标 | 值 |')
      lines.push('|------|------|')
      if (pp.current_price) lines.push(`| 当前价 | ${pp.current_price} |`)
      if (pp.ma5) lines.push(`| MA5 | ${pp.ma5} |`)
      if (pp.ma10) lines.push(`| MA10 | ${pp.ma10} |`)
      if (pp.ma20) lines.push(`| MA20 | ${pp.ma20} |`)
      if (pp.support_level) lines.push(`| 支撑位 | ${pp.support_level} |`)
      if (pp.resistance_level) lines.push(`| 阻力位 | ${pp.resistance_level} |`)
      lines.push('')
      if (pp.bias_status) lines.push(`乖离状态: ${pp.bias_status}\n`)
    }
    if (dp.volume_analysis) {
      const va = dp.volume_analysis
      lines.push(`**量能**: ${va.volume_status || ''} (量比 ${va.volume_ratio || '-'}, 换手率 ${va.turnover_rate || '-'}%)\n`)
      if (va.volume_meaning) lines.push(`> ${va.volume_meaning}\n`)
    }
    if (lines.length > 0) {
      sections.push({ key: 'data_perspective', title: '📊 数据透视', html: md.render(lines.join('\n')), defaultOpen: true })
    }
  }

  // 详细分析文本（来自 raw_result）
  const textSections = [
    { key: 'technical_analysis', title: '📈 技术分析' },
    { key: 'trend_analysis', title: '📉 趋势分析' },
    { key: 'ma_analysis', title: '📐 均线分析' },
    { key: 'volume_analysis', title: '📊 量能分析' },
    { key: 'pattern_analysis', title: '🕯️ 形态分析' },
    { key: 'fundamental_analysis', title: '💰 基本面分析' },
    { key: 'sector_position', title: '🏭 板块地位' },
    { key: 'news_summary', title: '📰 舆情资讯' },
    { key: 'market_sentiment', title: '🌡️ 市场情绪' }
  ]
  textSections.forEach(({ key, title }) => {
    const text = raw[key]
    if (text && text.trim()) {
      sections.push({ key, title, html: md.render(text), defaultOpen: false })
    }
  })

  // 情报汇总
  const intel = dashboard.intelligence
  if (intel) {
    const lines = []
    if (intel.earnings_outlook) lines.push(`**盈利展望**: ${intel.earnings_outlook}\n`)
    if (intel.sentiment_summary) lines.push(`**情绪总结**: ${intel.sentiment_summary}\n`)
    if (lines.length > 0) {
      sections.push({ key: 'intelligence', title: '🔍 情报汇总', html: md.render(lines.join('\n')), defaultOpen: true })
    }
  }

  // 风险提示
  const riskWarning = raw.risk_warning
  if (riskWarning && riskWarning.trim()) {
    sections.push({ key: 'risk_warning', title: '⚠️ 风险提示', html: md.render('> ' + riskWarning.replace(/\n/g, '\n> ')), defaultOpen: true })
  }

  reportSections.value = sections

  nextTick(() => {
    const container = document.querySelector('.report-container')
    if (container) container.scrollTop = 0
  })
}

// 获取任务列表
async function fetchTaskList() {
  if (serviceStatus.value !== 'connected') return
  try {
    const resp = await fetch(`${getBaseUrl()}/api/v1/analysis/tasks?limit=50`)
    if (resp.ok) {
      const data = await resp.json()
      taskList.value = data.tasks || []
    }
  } catch {
    // ignore
  }
}

// 更新列表中的任务状态
function updateTaskInList(taskId, updates) {
  const task = taskList.value.find((t) => t.task_id === taskId)
  if (task) {
    Object.assign(task, updates)
  }
}

// 加载历史任务结果
async function loadTaskResult(task) {
  if (task.status === 'completed') {
    currentTaskId.value = task.task_id
    try {
      const resp = await fetch(`${getBaseUrl()}/api/v1/history/${task.task_id}`)
      if (resp.ok) {
        const data = await resp.json()
        analyzing.value = false
        errorMsg.value = ''
        renderReport(data)
        fetchNews(task.task_id)
      }
    } catch (e) {
      errorMsg.value = `加载失败: ${e.message}`
    }
  } else if (task.status === 'processing' || task.status === 'pending') {
    currentTaskId.value = task.task_id
    currentStockCode.value = task.stock_code
    currentStockName.value = task.stock_name || ''
    currentProgress.value = task.progress || 0
    currentMessage.value = task.message || '等待中...'
    analyzing.value = true
    reportData.value = null
    reportSections.value = []
    newsItems.value = []
  }
}

// 工具函数
function statusText(status) {
  const map = {
    pending: '等待中',
    processing: '分析中',
    completed: '已完成',
    failed: '失败'
  }
  return map[status] || status
}

function formatTime(isoStr) {
  if (!isoStr) return ''
  try {
    const d = new Date(isoStr)
    return d.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch {
    return isoStr
  }
}

// 生命周期
let serviceCheckTimer = null

onMounted(async () => {
  // 监听来自标的浏览器的分析请求
  if (window.electronAPI?.onAnalyzeSymbol) {
    window.electronAPI.onAnalyzeSymbol((symbolInfo) => {
      console.log('[StockAnalysis] 收到 analyze-symbol:', symbolInfo)
      searchQuery.value = symbolInfo.symbol
      currentStockName.value = symbolInfo.name || ''
      // 等服务就绪后自动触发分析
      if (serviceStatus.value === 'connected') {
        handleAnalyze()
      }
    })
  }

  // 监听 DSA 状态变化
  if (window.electronAPI && window.electronAPI.onDsaStatusChanged) {
    window.electronAPI.onDsaStatusChanged(async (data) => {
      if (data.status === 'running') {
        await checkService()
        if (serviceStatus.value === 'connected') {
          connectSSE()
          fetchTaskList()
        }
      } else {
        serviceStatus.value = 'disconnected'
      }
    })
  }

  // 初始检查
  await checkService()

  if (serviceStatus.value === 'connected') {
    connectSSE()
    fetchTaskList()
  }

  // 定期检查服务状态
  serviceCheckTimer = setInterval(async () => {
    const wasConnected = serviceStatus.value === 'connected'
    await checkService()
    if (!wasConnected && serviceStatus.value === 'connected') {
      connectSSE()
      fetchTaskList()
    }
  }, 15000)
})

onUnmounted(() => {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
  if (serviceCheckTimer) {
    clearInterval(serviceCheckTimer)
  }
  clearTimeout(searchTimer)
})
</script>

<style>
/* 主布局 */
.stock-analysis {
  height: 100vh;
  color: #cccccc;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

/* 历史记录列表 */
.history-list {
  padding: 4px 0;
}

.history-item {
  padding: 10px 16px;
  cursor: pointer;
  border-bottom: 1px solid #2a2a2a;
  transition: background 0.15s;
}

.history-item:hover {
  background: #2a2d2e;
}

.history-item.active {
  background: #37373d;
  border-left: 2px solid #4a9eff;
}

.history-item-header {
  display: flex;
  gap: 8px;
  align-items: baseline;
  margin-bottom: 4px;
}

.stock-code {
  font-weight: 600;
  color: #e0e0e0;
  font-size: 13px;
}

.stock-name {
  font-size: 12px;
  color: #888;
}

.history-item-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
}

.status-badge {
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 11px;
}

.status-badge.pending {
  background: #4d3800;
  color: #d29922;
}

.status-badge.processing {
  background: #0e3a5c;
  color: #4a9eff;
}

.status-badge.completed {
  background: #1a3a1a;
  color: #2ea043;
}

.status-badge.failed {
  background: #3a1a1a;
  color: #da3633;
}

.time {
  color: #666;
}

.progress-bar {
  margin-top: 6px;
  height: 3px;
  background: #333;
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: #4a9eff;
  transition: width 0.3s;
}

.history-empty {
  padding: 40px 16px;
  text-align: center;
  color: #666;
  font-size: 13px;
}

/* 搜索栏 */
.search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: #252526;
  border-bottom: 1px solid #333;
}

.search-input-wrapper {
  flex: 1;
  position: relative;
}

.search-input {
  width: 100%;
  padding: 8px 12px;
  background: #1a1a1a;
  border: 1px solid #444;
  border-radius: 4px;
  color: #fff;
  font-size: 14px;
  box-sizing: border-box;
  outline: none;
}

.search-input:focus {
  border-color: #4a9eff;
}

.suggestions {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: #2d2d2d;
  border: 1px solid #444;
  border-top: none;
  border-radius: 0 0 4px 4px;
  z-index: 100;
  max-height: 240px;
  overflow-y: auto;
}

.suggestion-item {
  padding: 8px 12px;
  cursor: pointer;
  display: flex;
  gap: 12px;
  align-items: center;
  transition: background 0.1s;
}

.suggestion-item:hover {
  background: #37373d;
}

.suggestion-code {
  font-weight: 600;
  color: #4a9eff;
  min-width: 60px;
}

.suggestion-name {
  color: #ccc;
  font-size: 13px;
}

.analyze-btn {
  padding: 8px 20px;
  background: #4a9eff;
  border: none;
  border-radius: 4px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s;
}

.analyze-btn:hover:not(:disabled) {
  background: #5aaeff;
}

.analyze-btn:disabled {
  background: #333;
  color: #666;
  cursor: not-allowed;
}

/* 内容区 */
.content-area {
  padding: 0;
}

/* 欢迎页 */
.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
  padding: 40px;
}

.welcome-icon {
  font-size: 64px;
  margin-bottom: 16px;
}

.welcome h2 {
  font-size: 24px;
  font-weight: 500;
  color: #e0e0e0;
  margin: 0 0 8px;
}

.welcome p {
  font-size: 14px;
  color: #888;
  margin: 0 0 24px;
  max-width: 500px;
}

.quick-stocks {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
}

.quick-label {
  color: #666;
  font-size: 13px;
}

.quick-btn {
  padding: 6px 14px;
  background: #2d2d2d;
  border: 1px solid #444;
  border-radius: 4px;
  color: #ccc;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.15s;
}

.quick-btn:hover {
  background: #37373d;
  border-color: #4a9eff;
  color: #fff;
}

/* 分析进度 */
.analyzing-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 40px;
}

.analyzing-header {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 18px;
  color: #e0e0e0;
  margin-bottom: 24px;
}

.analyzing-spinner {
  width: 24px;
  height: 24px;
  border: 3px solid #333;
  border-top-color: #4a9eff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.analyzing-progress {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 400px;
  max-width: 100%;
}

.analyzing-progress-bar {
  flex: 1;
  height: 6px;
  background: #333;
  border-radius: 3px;
  overflow: hidden;
}

.analyzing-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #4a9eff, #7b61ff);
  transition: width 0.5s;
  border-radius: 3px;
}

.analyzing-progress-text {
  font-size: 14px;
  color: #888;
  min-width: 40px;
}

.analyzing-message {
  margin-top: 12px;
  font-size: 13px;
  color: #888;
}

/* 报告 */
.report-container {
  padding: 24px 32px;
  max-width: 1100px;
  margin: 0 auto;
  box-sizing: border-box;
}

.report-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #333;
}

.report-header h2 {
  margin: 0;
  font-size: 20px;
  color: #e0e0e0;
}

.report-header h2 span {
  font-size: 14px;
  color: #888;
  font-weight: normal;
  margin-left: 8px;
}

.report-time {
  font-size: 12px;
  color: #666;
}

/* Markdown 报告样式 */
.report-body {
  font-size: 14px;
  line-height: 1.7;
  color: #d4d4d4;
}

.report-body h1, .report-body h2, .report-body h3 {
  color: #e0e0e0;
  margin-top: 24px;
  margin-bottom: 8px;
}

.report-body h1 { font-size: 22px; border-bottom: 1px solid #333; padding-bottom: 8px; }
.report-body h2 { font-size: 18px; border-bottom: 1px solid #2a2a2a; padding-bottom: 6px; }
.report-body h3 { font-size: 15px; }

.report-body p {
  margin: 8px 0;
}

.report-body ul, .report-body ol {
  padding-left: 24px;
  margin: 8px 0;
}

.report-body li {
  margin: 4px 0;
}

.report-body li::marker {
  color: #666;
}

.report-body strong {
  color: #fff;
}

.report-body em {
  color: #bbb;
  font-style: italic;
}

.report-body code {
  background: #2d2d2d;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 13px;
  color: #ce9178;
}

.report-body pre {
  background: #1a1a1a;
  padding: 16px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 12px 0;
  border: 1px solid #333;
}

.report-body pre code {
  background: none;
  padding: 0;
  color: #d4d4d4;
}

.report-body table {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
  font-size: 13px;
}

.report-body thead th {
  background: #2d2d2d;
  font-weight: 600;
  color: #e0e0e0;
}

.report-body th, .report-body td {
  padding: 10px 14px;
  border: 1px solid #3a3a3a;
  text-align: left;
}

.report-body tbody tr:nth-child(even) {
  background: #252526;
}

.report-body tbody tr:hover {
  background: #2a2d2e;
}

.report-body blockquote {
  border-left: 3px solid #4a9eff;
  margin: 12px 0;
  padding: 8px 16px;
  background: #252526;
  color: #bbb;
}

.report-body blockquote p {
  margin: 4px 0;
}

.report-body a {
  color: #4a9eff;
  text-decoration: none;
}

.report-body a:hover {
  text-decoration: underline;
}

.report-body hr {
  border: none;
  border-top: 1px solid #333;
  margin: 16px 0;
}

.report-body img {
  max-width: 100%;
  border-radius: 4px;
  margin: 8px 0;
}

/* 错误面板 */
.error-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  gap: 12px;
}

.error-icon {
  font-size: 48px;
}

.error-text {
  font-size: 14px;
  color: #da3633;
  text-align: center;
  max-width: 500px;
}

.retry-btn {
  padding: 6px 16px;
  background: #2d2d2d;
  border: 1px solid #444;
  border-radius: 4px;
  color: #ccc;
  cursor: pointer;
  font-size: 13px;
}

.retry-btn:hover {
  background: #37373d;
}

/* 报告区域 */
.report-sections {
  margin-top: 16px;
}

.report-footer {
  margin-top: 20px;
  padding-top: 12px;
  border-top: 1px solid #333;
  text-align: center;
}

.meta-text {
  font-size: 12px;
  color: #666;
  font-style: italic;
}

/* 滚动条 */
.content-area::-webkit-scrollbar,
.report-container::-webkit-scrollbar {
  width: 8px;
}

.content-area::-webkit-scrollbar-track,
.report-container::-webkit-scrollbar-track {
  background: transparent;
}

.content-area::-webkit-scrollbar-thumb,
.report-container::-webkit-scrollbar-thumb {
  background: #444;
  border-radius: 4px;
}

.content-area::-webkit-scrollbar-thumb:hover,
.report-container::-webkit-scrollbar-thumb:hover {
  background: #555;
}

/* ===== 模式切换按钮 ===== */
.mode-toggle {
  display: flex;
  gap: 2px;
  background: #1a1a1a;
  border-radius: 6px;
  padding: 2px;
}

.mode-btn {
  padding: 6px 12px;
  background: transparent;
  border: none;
  border-radius: 4px;
  color: #888;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.mode-btn.active {
  background: #0e639c;
  color: #fff;
}

.mode-btn:hover:not(.active) {
  color: #ccc;
  background: #333;
}

/* ===== 右侧面板 ===== */
.right-panel {
  width: 280px;
  min-width: 240px;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #1a2634;
  border-left: 1px solid #2a3a4a;
  overflow: hidden;
  flex-shrink: 0;
}

.right-panel-header {
  height: 35px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 12px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #8bb8d4;
  border-bottom: 1px solid #2a3a4a;
  flex-shrink: 0;
}

.panel-collapse-btn {
  background: none;
  border: none;
  color: #666;
  cursor: pointer;
  font-size: 14px;
  padding: 2px 4px;
}

.panel-collapse-btn:hover {
  color: #ccc;
}

.right-panel-content {
  flex: 1;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: #3a5060 transparent;
}

/* ===== 分析模式徽章 ===== */
.analysis-mode-badge {
  font-size: 12px;
  color: #8bb8d4;
  background: #1e2e3e;
  padding: 3px 10px;
  border-radius: 4px;
}

.report-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ===== Agent 流式内容区 ===== */
.agent-stream-content {
  max-width: 800px;
  margin: 16px auto 0;
  padding: 0 32px;
}

/* ===== Agent 降级内容区 ===== */
.agent-fallback-content {
  max-width: 800px;
  margin: 16px auto 0;
  padding: 16px 32px;
}

.analysis-mode-badge.fallback {
  background: rgba(255, 170, 0, 0.15);
  color: #ffaa00;
}
</style>
