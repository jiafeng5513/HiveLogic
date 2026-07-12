<template>
  <div class="cache-timeline-container">
    <!-- 统计概览 -->
    <div class="cache-stats" v-if="cacheStatus">
      <span class="stat-item">
        <span class="stat-label">总缓存</span>
        <span class="stat-value">{{ cacheStatus.total_size_mb }} MB</span>
      </span>
      <span class="stat-item">
        <span class="stat-label">记录数</span>
        <span class="stat-value">{{ formatNumber(cacheStatus.total_records) }}</span>
      </span>
      <span class="stat-item">
        <span class="stat-label">市场数</span>
        <span class="stat-value">{{ Object.keys(cacheStatus.markets || {}).length }}</span>
      </span>
      <span class="stat-item action" @click="refreshStatus">
        <span class="stat-label">🔄 刷新</span>
      </span>
    </div>

    <!-- 工具栏 -->
    <div class="timeline-toolbar">
      <div class="toolbar-left">
        <select v-model="selectedInterval" class="toolbar-select" @change="loadTimeline">
          <option value="1d">日线</option>
          <option value="1h">1小时</option>
          <option value="5m">5分钟</option>
          <option value="1m">1分钟</option>
        </select>
      </div>
      <div class="toolbar-center" v-if="selection">
        <span class="selection-info">
          {{ marketLabel(selection.market) }}: {{ formatDate(selection.start) }} ~ {{ formatDate(selection.end) }}
        </span>
        <button class="btn btn-sm btn-primary" @click="downloadSelection" :disabled="downloading">
          {{ downloading ? '提交中...' : '⬇ 下载全部品种' }}
        </button>
        <button class="btn btn-sm btn-danger" @click="deleteSelection">🗑 删除</button>
        <button class="btn btn-sm" @click="clearSelection">✕ 取消</button>
      </div>
      <div class="toolbar-right">
        <button class="btn btn-sm" @click="zoomIn" title="放大">＋</button>
        <button class="btn btn-sm" @click="zoomOut" title="缩小">－</button>
        <button class="btn btn-sm" @click="fitAll" title="适应全部">⊡</button>
      </div>
    </div>

    <!-- 时间轴画布 -->
    <div class="timeline-viewport" ref="viewportRef"
      @mousedown="onMouseDown"
      @mousemove="onMouseMove"
      @mouseup="onMouseUp"
      @mouseleave="onMouseLeave"
      @wheel.prevent="onWheel"
    >
      <canvas ref="canvasRef" :width="canvasWidth" :height="canvasHeight"></canvas>
      <!-- 选区高亮 -->
      <div class="selection-overlay" v-if="selectionRect" :style="selectionRect"></div>
      <!-- Hover 提示 -->
      <div class="timeline-tooltip" v-if="tooltip" :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px' }">
        <div class="tooltip-title">{{ tooltip.market }} / {{ tooltip.symbol }}</div>
        <div class="tooltip-range">{{ formatDate(tooltip.start) }} ~ {{ formatDate(tooltip.end) }}</div>
        <div class="tooltip-info">记录数: {{ tooltip.count }} | 完整度: {{ (tooltip.completeness * 100).toFixed(0) }}%</div>
      </div>
    </div>

    <!-- 手动下载面板 -->
    <div class="manual-download-panel">
      <div class="panel-header">📥 批量下载缓存（按市场全部品种）</div>
      <div class="panel-row">
        <label class="panel-label">市场</label>
        <select v-model="manualDownload.market" class="toolbar-select" @change="onMarketChange">
          <option value="crypto_binance">加密(Binance)</option>
          <option value="crypto_okx">加密(OKX)</option>
          <option value="cn">A股</option>
          <option value="us">美股</option>
          <option value="hk">港股</option>
        </select>
        <label class="panel-label">周期</label>
        <select v-model="manualDownload.interval" class="toolbar-select">
          <option value="1d">日线</option>
          <option value="1h">1小时</option>
          <option value="5m">5分钟</option>
          <option value="1m">1分钟</option>
        </select>
        <span class="symbol-count-badge" v-if="symbolCount > 0">
          ~{{ symbolCount }} 个品种
        </span>
      </div>
      <div class="panel-row">
        <label class="panel-label">起始</label>
        <input type="date" v-model="manualDownload.startDate" class="panel-input date-input" />
        <label class="panel-label">结束</label>
        <input type="date" v-model="manualDownload.endDate" class="panel-input date-input" />
        <button class="btn btn-sm btn-primary" @click="startBatchDownload" :disabled="batchDownloading">
          {{ batchDownloading ? '提交中...' : '⬇ 下载全部品种' }}
        </button>
      </div>
      <div class="panel-hint" v-if="symbolCount > 0">
        将下载 {{ marketLabel(manualDownload.market) }} 全部 ~{{ symbolCount }} 个品种的
        {{ intervalLabel(manualDownload.interval) }}数据
      </div>
    </div>

    <!-- 批次下载进度 -->
    <div class="download-tasks" v-if="activeBatches.length || activeTasks.length">
      <div class="download-tasks-header">
        <span class="tasks-title">⏳ 下载进度</span>
      </div>
      <!-- 批次级进度 -->
      <div class="batch-item" v-for="batch in activeBatches" :key="batch.batch_id">
        <div class="batch-header">
          <span class="batch-label">{{ marketLabel(batch.market) }} 全部品种</span>
          <span class="batch-stats">{{ batch.completed_symbols }}/{{ batch.total_symbols }} 品种</span>
          <span class="task-status-badge" :class="'status-' + batch.status">
            {{ batchStatusLabel(batch.status) }}
          </span>
          <button class="btn btn-sm btn-danger-icon" @click="cancelBatch(batch.batch_id)" title="取消批次">✕</button>
        </div>
        <div class="batch-progress-row">
          <div class="task-progress-bar">
            <div class="task-progress-fill progress-animated" :style="{ width: (batch.overall_progress * 100) + '%' }"></div>
          </div>
          <span class="task-percent">{{ (batch.overall_progress * 100).toFixed(1) }}%</span>
        </div>
        <div class="batch-current" v-if="batch.current_tasks && batch.current_tasks.length">
          <span class="batch-current-label">正在下载:</span>
          <span class="batch-current-symbol" v-for="t in batch.current_tasks" :key="t.task_id">
            {{ t.symbol }} ({{ (t.progress * 100).toFixed(0) }}%)
          </span>
        </div>
        <div class="batch-failed" v-if="batch.failed_symbols > 0">
          <span class="batch-failed-label">⚠ {{ batch.failed_symbols }} 个品种失败</span>
        </div>
      </div>
      <!-- 单独任务（非批次）进度 -->
      <div class="task-item" v-for="task in standaloneTasks" :key="task.task_id">
        <span class="task-label">{{ marketLabel(task.market) }} / {{ task.symbol || '全部' }}</span>
        <span class="task-status-badge" :class="'status-' + task.status">{{ task.status === 'running' ? '下载中' : '等待中' }}</span>
        <div class="task-progress-bar">
          <div class="task-progress-fill" :class="{ 'progress-animated': task.status === 'running' }" :style="{ width: (task.progress * 100) + '%' }"></div>
        </div>
        <span class="task-percent">{{ (task.progress * 100).toFixed(1) }}%</span>
        <button class="btn btn-sm btn-danger-icon" @click="cancelTask(task.task_id)" title="取消">✕</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { getApiBase } from '../../service/serverConfig'

const props = defineProps({
  baseUrl: { type: String, default: getApiBase() },
})

// ==================== State ====================
const viewportRef = ref(null)
const canvasRef = ref(null)
const canvasWidth = ref(800)
const canvasHeight = ref(200)

const cacheStatus = ref(null)
const timelineData = ref({}) // { market: [segments...] }
const selectedInterval = ref('1d')
const selection = ref(null) // { market, start, end }
const selectionRect = ref(null)
const tooltip = ref(null)
const downloading = ref(false)
const batchDownloading = ref(false)
const activeTasks = ref([])
const activeBatches = ref([])
const symbolCount = ref(0)

// 手动下载表单
const manualDownload = reactive({
  market: 'crypto_binance',
  interval: '1d',
  startDate: '',
  endDate: '',
})

// 非批次的单独任务
const standaloneTasks = computed(() =>
  activeTasks.value.filter(t => !t.batch_id)
)

// 视图状态
const viewState = reactive({
  startTime: 0,    // 可视区域起始时间 (ms)
  endTime: 0,      // 可视区域结束时间 (ms)
  pixelPerMs: 0,   // 每像素对应毫秒数
})

// 交互状态
const interaction = reactive({
  isDragging: false,
  isSelecting: false,
  isPanning: false,
  startX: 0,
  startY: 0,
  startViewStart: 0,
  startViewEnd: 0,
})

// ==================== Constants ====================
const TRACK_HEIGHT = 32
const TRACK_GAP = 4
const RULER_HEIGHT = 28
const LABEL_WIDTH = 80
const COLORS = {
  cached: '#2ea043',
  partial: '#d29922',
  empty: '#30363d',
  selection: 'rgba(56, 139, 253, 0.3)',
  ruler: '#8b949e',
  track_bg: '#21262d',
  label: '#c9d1d9',
}

// ==================== Computed ====================
// 始终显示所有5个市场轨道
const ALL_MARKETS = ['crypto_binance', 'crypto_okx', 'cn', 'us', 'hk']
const trackMarkets = computed(() => ALL_MARKETS)

// ==================== Lifecycle ====================
let resizeObserver = null
let progressTimer = null

onMounted(async () => {
  // 设置默认日期范围：近一年
  const now = new Date()
  const oneYearAgo = new Date(now.getTime() - 365 * 24 * 3600000)
  manualDownload.endDate = now.toISOString().slice(0, 10)
  manualDownload.startDate = oneYearAgo.toISOString().slice(0, 10)

  await refreshStatus()
  await loadTimeline()
  await fetchSymbolCount()
  setupResize()
  progressTimer = setInterval(pollProgress, 3000)
})

onUnmounted(() => {
  if (resizeObserver) resizeObserver.disconnect()
  if (progressTimer) clearInterval(progressTimer)
})

// ==================== Data Loading ====================
async function refreshStatus() {
  try {
    const resp = await fetch(`${props.baseUrl}/api/v1/cache/status`)
    if (resp.ok) cacheStatus.value = await resp.json()
  } catch (e) {
    console.warn('[CacheTimeline] Failed to load status:', e)
  }
}

async function loadTimeline() {
  try {
    const resp = await fetch(`${props.baseUrl}/api/v1/cache/timeline/summary?interval=${selectedInterval.value}`)
    if (resp.ok) {
      const data = await resp.json()
      const prevEmpty = Object.keys(timelineData.value).length === 0
      timelineData.value = data.markets || {}
      // 首次加载或从空变有数据时自适应视图
      if (prevEmpty && Object.keys(timelineData.value).length > 0) {
        fitAll()
      } else {
        nextTick(render)
      }
    }
  } catch (e) {
    console.warn('[CacheTimeline] Failed to load timeline:', e)
  }
}

async function pollProgress() {
  try {
    // 轮询单个任务进度
    const resp = await fetch(`${props.baseUrl}/api/v1/cache/download/progress`)
    if (resp.ok) {
      const data = await resp.json()
      const prevTaskCount = activeTasks.value.length
      activeTasks.value = (data.tasks || []).filter(t => t.status === 'running' || t.status === 'pending')

      // 有任务完成时刷新时间轴
      if (prevTaskCount > 0 && activeTasks.value.length < prevTaskCount) {
        await loadTimeline()
        await refreshStatus()
      }
    }

    // 轮询批次进度
    const batchResp = await fetch(`${props.baseUrl}/api/v1/cache/download/batches`)
    if (batchResp.ok) {
      const batchData = await batchResp.json()
      const prevBatchActive = activeBatches.value.length
      activeBatches.value = (batchData.batches || []).filter(b => b.status === 'running')

      // 批次完成时自动刷新
      if (prevBatchActive > 0 && activeBatches.value.length === 0) {
        await loadTimeline()
        await refreshStatus()
      }
    }

    // 有活跃任务/批次时加速轮询
    adjustPollInterval()
  } catch (e) { /* ignore */ }
}

function adjustPollInterval() {
  const hasActive = activeTasks.value.length > 0 || activeBatches.value.length > 0
  const interval = hasActive ? 1500 : 5000
  if (progressTimer) clearInterval(progressTimer)
  progressTimer = setInterval(pollProgress, interval)
}

async function fetchSymbolCount() {
  try {
    const resp = await fetch(`${props.baseUrl}/api/v1/cache/symbols/${manualDownload.market}`)
    if (resp.ok) {
      const data = await resp.json()
      symbolCount.value = data.count || 0
    }
  } catch (e) {
    symbolCount.value = 0
  }
}

function onMarketChange() {
  fetchSymbolCount()
}

// ==================== Canvas Rendering ====================
function setupResize() {
  const el = viewportRef.value
  if (!el) return
  const updateSize = () => {
    canvasWidth.value = el.clientWidth
    const trackCount = ALL_MARKETS.length
    canvasHeight.value = RULER_HEIGHT + trackCount * (TRACK_HEIGHT + TRACK_GAP) + 10
    nextTick(render)
  }
  resizeObserver = new ResizeObserver(updateSize)
  resizeObserver.observe(el)
  updateSize()
}

function render() {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  const w = canvas.width
  const h = canvas.height
  ctx.clearRect(0, 0, w, h)

  if (!viewState.startTime || !viewState.endTime) return

  // 画时间刻度尺
  drawRuler(ctx, w)

  // 画每条轨道
  const markets = trackMarkets.value
  markets.forEach((market, idx) => {
    const y = RULER_HEIGHT + idx * (TRACK_HEIGHT + TRACK_GAP)
    drawTrack(ctx, market, timelineData.value[market], y, w)
  })

  // 画选区
  if (selectionRect.value) {
    const sr = selectionRect.value
    ctx.fillStyle = COLORS.selection
    ctx.fillRect(parseInt(sr.left), 0, parseInt(sr.width), h)
  }
}

function drawRuler(ctx, w) {
  const { startTime, endTime } = viewState
  const duration = endTime - startTime
  if (duration <= 0) return

  ctx.fillStyle = '#161b22'
  ctx.fillRect(0, 0, w, RULER_HEIGHT)

  // 自适应刻度间距
  const intervals = [
    { ms: 365.25 * 24 * 3600000, label: 'year' },
    { ms: 30 * 24 * 3600000, label: 'month' },
    { ms: 7 * 24 * 3600000, label: 'week' },
    { ms: 24 * 3600000, label: 'day' },
    { ms: 3600000, label: 'hour' },
  ]
  let tickInterval = intervals[0]
  for (const iv of intervals) {
    if (duration / iv.ms < 100 && duration / iv.ms > 3) {
      tickInterval = iv
      break
    }
  }

  ctx.strokeStyle = '#30363d'
  ctx.fillStyle = COLORS.ruler
  ctx.font = '11px monospace'
  ctx.textAlign = 'center'

  const firstTick = Math.ceil(startTime / tickInterval.ms) * tickInterval.ms
  for (let t = firstTick; t <= endTime; t += tickInterval.ms) {
    const x = timeToX(t, w)
    ctx.beginPath()
    ctx.moveTo(x, RULER_HEIGHT - 8)
    ctx.lineTo(x, RULER_HEIGHT)
    ctx.stroke()

    const d = new Date(t)
    let label = ''
    if (tickInterval.label === 'year') label = d.getFullYear().toString()
    else if (tickInterval.label === 'month') label = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    else if (tickInterval.label === 'week' || tickInterval.label === 'day') label = `${d.getMonth() + 1}/${d.getDate()}`
    else label = `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
    ctx.fillText(label, x, RULER_HEIGHT - 12)
  }
}

function drawTrack(ctx, market, segments, y, w) {
  // 轨道背景
  ctx.fillStyle = COLORS.track_bg
  ctx.fillRect(LABEL_WIDTH, y, w - LABEL_WIDTH, TRACK_HEIGHT)

  // 轨道标签
  ctx.fillStyle = COLORS.label
  ctx.font = '12px sans-serif'
  ctx.textAlign = 'left'
  ctx.fillText(marketLabel(market), 4, y + TRACK_HEIGHT / 2 + 4)

  // 画缓存段
  if (!segments || !segments.length) return
  for (const seg of segments) {
    const x1 = Math.max(timeToX(seg.start_time, w), LABEL_WIDTH)
    const x2 = Math.min(timeToX(seg.end_time, w), w)
    if (x2 <= x1) continue

    const completeness = seg.completeness ?? 1.0
    ctx.fillStyle = completeness >= 0.95 ? COLORS.cached : COLORS.partial
    ctx.fillRect(x1, y + 2, x2 - x1, TRACK_HEIGHT - 4)
  }
}

function timeToX(t, w) {
  const { startTime, endTime } = viewState
  const ratio = (t - startTime) / (endTime - startTime)
  return LABEL_WIDTH + ratio * (w - LABEL_WIDTH)
}

function xToTime(x, w) {
  const ratio = (x - LABEL_WIDTH) / (w - LABEL_WIDTH)
  return viewState.startTime + ratio * (viewState.endTime - viewState.startTime)
}

// ==================== Interactions ====================
function onMouseDown(e) {
  const rect = viewportRef.value.getBoundingClientRect()
  const x = e.clientX - rect.left
  const y = e.clientY - rect.top

  if (e.button === 1 || (e.button === 0 && e.shiftKey)) {
    // 中键/Shift+左键 = 平移
    interaction.isPanning = true
    interaction.startX = x
    interaction.startViewStart = viewState.startTime
    interaction.startViewEnd = viewState.endTime
  } else if (e.button === 0 && x > LABEL_WIDTH) {
    // 左键在轨道区 = 框选
    interaction.isSelecting = true
    interaction.startX = x
    interaction.startY = y
    selectionRect.value = null
    selection.value = null
  }
}

function onMouseMove(e) {
  const rect = viewportRef.value.getBoundingClientRect()
  const x = e.clientX - rect.left
  const y = e.clientY - rect.top
  const w = canvasWidth.value

  if (interaction.isPanning) {
    const dx = x - interaction.startX
    const timeDelta = dx * (viewState.endTime - viewState.startTime) / (w - LABEL_WIDTH)
    viewState.startTime = interaction.startViewStart - timeDelta
    viewState.endTime = interaction.startViewEnd - timeDelta
    render()
    return
  }

  if (interaction.isSelecting) {
    const left = Math.min(interaction.startX, x)
    const width = Math.abs(x - interaction.startX)
    selectionRect.value = {
      left: left + 'px',
      top: '0px',
      width: width + 'px',
      height: canvasHeight.value + 'px',
    }
    render()
    return
  }

  // Hover 提示
  updateTooltip(x, y, w)
}

function onMouseUp(e) {
  const rect = viewportRef.value.getBoundingClientRect()
  const x = e.clientX - rect.left
  const w = canvasWidth.value

  if (interaction.isSelecting && selectionRect.value) {
    const left = parseInt(selectionRect.value.left)
    const width = parseInt(selectionRect.value.width)
    if (width > 5) {
      const startT = xToTime(left, w)
      const endT = xToTime(left + width, w)
      // 确定选中的轨道
      const y = interaction.startY
      const trackIdx = Math.floor((y - RULER_HEIGHT) / (TRACK_HEIGHT + TRACK_GAP))
      const market = trackMarkets.value[trackIdx] || trackMarkets.value[0]
      selection.value = {
        market,
        start: Math.round(startT),
        end: Math.round(endT),
      }
    }
  }

  interaction.isPanning = false
  interaction.isSelecting = false
}

function onMouseLeave() {
  tooltip.value = null
  if (interaction.isPanning || interaction.isSelecting) {
    interaction.isPanning = false
    interaction.isSelecting = false
  }
}

function onWheel(e) {
  const rect = viewportRef.value.getBoundingClientRect()
  const x = e.clientX - rect.left
  const w = canvasWidth.value

  const zoomFactor = e.deltaY > 0 ? 1.2 : 0.8
  const mouseTime = xToTime(x, w)
  const newDuration = (viewState.endTime - viewState.startTime) * zoomFactor

  // 最小/最大缩放限制
  const minDuration = 3600000 // 1小时
  const maxDuration = 10 * 365.25 * 24 * 3600000 // 10年
  if (newDuration < minDuration || newDuration > maxDuration) return

  const ratio = (x - LABEL_WIDTH) / (w - LABEL_WIDTH)
  viewState.startTime = mouseTime - newDuration * ratio
  viewState.endTime = mouseTime + newDuration * (1 - ratio)
  render()
}

function updateTooltip(x, y, w) {
  if (x < LABEL_WIDTH || y < RULER_HEIGHT) {
    tooltip.value = null
    return
  }
  const trackIdx = Math.floor((y - RULER_HEIGHT) / (TRACK_HEIGHT + TRACK_GAP))
  const market = trackMarkets.value[trackIdx]
  if (!market) { tooltip.value = null; return }

  const time = xToTime(x, w)
  const segments = timelineData.value[market] || []
  const hit = segments.find(s => time >= s.start_time && time <= s.end_time)
  if (hit) {
    tooltip.value = {
      x: x + 10,
      y: y + 10,
      market,
      symbol: hit.symbol || market,
      start: hit.start_time,
      end: hit.end_time,
      count: hit.record_count || 0,
      completeness: hit.completeness ?? 1.0,
    }
  } else {
    tooltip.value = null
  }
}

// ==================== Zoom Controls ====================
function zoomIn() {
  const mid = (viewState.startTime + viewState.endTime) / 2
  const half = (viewState.endTime - viewState.startTime) * 0.35
  viewState.startTime = mid - half
  viewState.endTime = mid + half
  render()
}

function zoomOut() {
  const mid = (viewState.startTime + viewState.endTime) / 2
  const half = (viewState.endTime - viewState.startTime) * 0.7
  viewState.startTime = mid - half
  viewState.endTime = mid + half
  render()
}

function fitAll() {
  let minT = Infinity, maxT = -Infinity
  for (const segs of Object.values(timelineData.value)) {
    for (const seg of segs) {
      if (seg.start_time < minT) minT = seg.start_time
      if (seg.end_time > maxT) maxT = seg.end_time
    }
  }
  if (minT === Infinity) {
    // 无数据时默认显示近一年
    const now = Date.now()
    viewState.startTime = now - 365 * 24 * 3600000
    viewState.endTime = now
  } else {
    const padding = (maxT - minT) * 0.1 || 30 * 24 * 3600000
    viewState.startTime = minT - padding
    viewState.endTime = maxT + padding
  }
  render()
}

function clearSelection() {
  selection.value = null
  selectionRect.value = null
  render()
}

// ==================== Actions ====================
async function downloadSelection() {
  if (!selection.value) return
  downloading.value = true
  try {
    // 框选下载也使用批量接口（按市场全部品种）
    const resp = await fetch(`${props.baseUrl}/api/v1/cache/download/market`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        market: selection.value.market,
        interval: selectedInterval.value,
        start_time: selection.value.start,
        end_time: selection.value.end,
      }),
    })
    if (resp.ok) {
      clearSelection()
      await pollProgress()
    }
  } catch (e) {
    console.error('[CacheTimeline] Download failed:', e)
  } finally {
    downloading.value = false
  }
}

async function startBatchDownload() {
  if (!manualDownload.startDate || !manualDownload.endDate) return
  batchDownloading.value = true
  try {
    const startTime = new Date(manualDownload.startDate).getTime()
    const endTime = new Date(manualDownload.endDate).getTime() + 24 * 3600000 - 1
    if (endTime <= startTime) {
      alert('结束日期必须大于起始日期')
      return
    }
    const confirmMsg = `确认下载 ${marketLabel(manualDownload.market)} 全部 ~${symbolCount.value} 个品种的${intervalLabel(manualDownload.interval)}数据？\n时间范围: ${manualDownload.startDate} ~ ${manualDownload.endDate}`
    if (!confirm(confirmMsg)) return

    const resp = await fetch(`${props.baseUrl}/api/v1/cache/download/market`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        market: manualDownload.market,
        interval: manualDownload.interval,
        start_time: startTime,
        end_time: endTime,
      }),
    })
    if (resp.ok) {
      await pollProgress()
    } else {
      const err = await resp.text()
      console.error('[CacheTimeline] Batch download failed:', err)
      alert('批量下载创建失败: ' + err)
    }
  } catch (e) {
    console.error('[CacheTimeline] Batch download failed:', e)
  } finally {
    batchDownloading.value = false
  }
}

async function cancelBatch(batchId) {
  if (!confirm('确认取消该批次的所有下载任务？')) return
  try {
    await fetch(`${props.baseUrl}/api/v1/cache/download/batch/${batchId}/cancel`, { method: 'POST' })
    await pollProgress()
  } catch (e) { /* ignore */ }
}

async function deleteSelection() {
  if (!selection.value) return
  if (!confirm(`确认删除 ${marketLabel(selection.value.market)} ${formatDate(selection.value.start)} ~ ${formatDate(selection.value.end)} 的缓存？`)) return
  try {
    const resp = await fetch(`${props.baseUrl}/api/v1/cache/range`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        market: selection.value.market,
        symbol: '',
        interval: selectedInterval.value,
        start_time: selection.value.start,
        end_time: selection.value.end,
      }),
    })
    if (resp.ok) {
      clearSelection()
      await loadTimeline()
      await refreshStatus()
    }
  } catch (e) {
    console.error('[CacheTimeline] Delete failed:', e)
  }
}

async function cancelTask(taskId) {
  try {
    await fetch(`${props.baseUrl}/api/v1/cache/download/${taskId}/cancel`, { method: 'POST' })
    await pollProgress()
  } catch (e) { /* ignore */ }
}

// ==================== Helpers ====================
function marketLabel(market) {
  const map = {
    cn: 'A股',
    hk: '港股',
    us: '美股',
    crypto_binance: '加密(Binance)',
    crypto_okx: '加密(OKX)',
  }
  return map[market] || market
}

function intervalLabel(interval) {
  const map = { '1d': '日线', '1h': '1小时线', '5m': '5分钟线', '1m': '1分钟线' }
  return map[interval] || interval
}

function batchStatusLabel(status) {
  const map = { running: '下载中', completed: '已完成', partial_failed: '部分失败', cancelled: '已取消' }
  return map[status] || status
}

function formatDate(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function formatNumber(n) {
  if (!n) return '0'
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return n.toString()
}

// Watch for data changes
watch(trackMarkets, () => {
  const el = viewportRef.value
  if (el) {
    const trackCount = Math.max(trackMarkets.value.length, 3)
    canvasHeight.value = RULER_HEIGHT + trackCount * (TRACK_HEIGHT + TRACK_GAP) + 10
    nextTick(render)
  }
})
</script>

<style scoped>
.cache-timeline-container {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.cache-stats {
  display: flex;
  gap: 16px;
  align-items: center;
  padding: 6px 0;
}
.stat-item {
  display: flex;
  gap: 4px;
  align-items: center;
  font-size: 12px;
}
.stat-item.action {
  cursor: pointer;
  opacity: 0.7;
}
.stat-item.action:hover { opacity: 1; }
.stat-label { color: var(--color-text-muted, #8b949e); }
.stat-value { color: var(--color-text, #c9d1d9); font-weight: 500; }

.timeline-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 0;
}
.toolbar-select {
  background: var(--color-bg-secondary, #21262d);
  color: var(--color-text, #c9d1d9);
  border: 1px solid var(--color-border, #30363d);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 12px;
}
.toolbar-center {
  display: flex;
  gap: 6px;
  align-items: center;
}
.selection-info {
  font-size: 11px;
  color: var(--color-text-muted, #8b949e);
}
.toolbar-right {
  display: flex;
  gap: 4px;
}
.btn-sm {
  padding: 2px 8px;
  font-size: 12px;
  border-radius: 4px;
  border: 1px solid var(--color-border, #30363d);
  background: var(--color-bg-secondary, #21262d);
  color: var(--color-text, #c9d1d9);
  cursor: pointer;
}
.btn-sm:hover { background: var(--color-bg-tertiary, #30363d); }
.btn-sm.btn-primary { background: #238636; border-color: #2ea043; color: #fff; }
.btn-sm.btn-primary:hover { background: #2ea043; }
.btn-sm.btn-danger { background: #da3633; border-color: #da3633; color: #fff; }
.btn-sm.btn-danger:hover { background: #f85149; }

.timeline-viewport {
  position: relative;
  width: 100%;
  min-height: 120px;
  border: 1px solid var(--color-border, #30363d);
  border-radius: 6px;
  overflow: hidden;
  cursor: crosshair;
  background: #0d1117;
}
.timeline-viewport canvas {
  display: block;
}
.selection-overlay {
  position: absolute;
  background: rgba(56, 139, 253, 0.15);
  border-left: 1px solid rgba(56, 139, 253, 0.6);
  border-right: 1px solid rgba(56, 139, 253, 0.6);
  pointer-events: none;
}
.timeline-tooltip {
  position: absolute;
  background: #1c2128;
  border: 1px solid #30363d;
  border-radius: 4px;
  padding: 6px 8px;
  font-size: 11px;
  color: #c9d1d9;
  pointer-events: none;
  z-index: 10;
  white-space: nowrap;
}
.tooltip-title { font-weight: 600; margin-bottom: 2px; }
.tooltip-range { color: #8b949e; }
.tooltip-info { color: #8b949e; margin-top: 2px; }

.download-tasks {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px;
  background: #161b22;
  border: 1px solid var(--color-border, #30363d);
  border-radius: 6px;
}
.download-tasks-header {
  display: flex;
  align-items: center;
  margin-bottom: 2px;
}
.tasks-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text, #c9d1d9);
}
.task-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.task-label {
  min-width: 120px;
  color: var(--color-text-muted, #8b949e);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.task-status-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 8px;
  white-space: nowrap;
}
.task-status-badge.status-running {
  background: rgba(46, 160, 67, 0.2);
  color: #3fb950;
}
.task-status-badge.status-pending {
  background: rgba(210, 153, 34, 0.2);
  color: #d29922;
}
.task-progress-bar {
  flex: 1;
  height: 8px;
  background: #21262d;
  border-radius: 4px;
  overflow: hidden;
}
.task-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #238636, #2ea043);
  border-radius: 4px;
  transition: width 0.3s ease;
}
.task-progress-fill.progress-animated {
  background: linear-gradient(90deg, #238636, #2ea043, #3fb950, #2ea043);
  background-size: 200% 100%;
  animation: progress-shine 1.5s linear infinite;
}
@keyframes progress-shine {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
.task-percent {
  min-width: 44px;
  text-align: right;
  color: var(--color-text, #c9d1d9);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}
.task-detail {
  font-size: 11px;
  color: var(--color-text-muted, #8b949e);
  white-space: nowrap;
}
.btn-danger-icon {
  background: none;
  border: none;
  color: #da3633;
  cursor: pointer;
  padding: 0 4px;
}

.manual-download-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  background: #161b22;
  border: 1px solid var(--color-border, #30363d);
  border-radius: 6px;
}
.panel-header {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text, #c9d1d9);
}
.panel-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.panel-label {
  font-size: 12px;
  color: var(--color-text-muted, #8b949e);
  white-space: nowrap;
}
.panel-input {
  background: var(--color-bg-secondary, #21262d);
  color: var(--color-text, #c9d1d9);
  border: 1px solid var(--color-border, #30363d);
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 12px;
  min-width: 100px;
}
.panel-input.date-input {
  min-width: 130px;
}
.panel-input:focus {
  outline: none;
  border-color: #388bfd;
}
.panel-hint {
  font-size: 11px;
  color: var(--color-text-muted, #8b949e);
  padding: 2px 0;
}
.symbol-count-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  background: rgba(56, 139, 253, 0.15);
  color: #58a6ff;
  white-space: nowrap;
}

/* 批次进度样式 */
.batch-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px 8px;
  background: #1c2128;
  border-radius: 4px;
  border: 1px solid #30363d;
}
.batch-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.batch-label {
  font-weight: 600;
  color: var(--color-text, #c9d1d9);
  min-width: 100px;
}
.batch-stats {
  color: var(--color-text-muted, #8b949e);
  font-variant-numeric: tabular-nums;
}
.batch-progress-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.batch-current {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--color-text-muted, #8b949e);
  flex-wrap: wrap;
}
.batch-current-label {
  color: #8b949e;
}
.batch-current-symbol {
  padding: 1px 5px;
  background: #21262d;
  border-radius: 3px;
  font-family: monospace;
  font-size: 10px;
}
.batch-failed {
  font-size: 11px;
}
.batch-failed-label {
  color: #f85149;
}
</style>
