<template>
  <div class="symbol-browser">
    <div class="panel-header">
      <span class="panel-title">自选</span>
    </div>

    <!-- 标的列表 -->
    <SymbolList
      :symbols="watchlistItems"
      :loading="loading"
      active-market-type="watchlist"
      search-query=""
      @context-menu="handleContextMenu"
      @dblclick="handleDoubleClick"
      @reorder="handleReorder"
    />

    <!-- 底部状态栏 -->
    <div class="status-bar">
      <span class="status-count">共 {{ watchlistItems.length }} 个标的</span>
      <span v-if="lastUpdateTime" class="status-time">更新于 {{ lastUpdateTime }}</span>
    </div>

    <!-- 右键菜单 -->
    <SymbolContextMenu
      v-if="contextMenu.visible"
      :x="contextMenu.x"
      :y="contextMenu.y"
      :symbol="contextMenu.symbol"
      :in-watchlist="true"
      @open-chart="handleOpenChart"
      @toggle-watchlist="handleToggleWatchlist"
      @copy-code="handleCopyCode"
      @close="contextMenu.visible = false"
    />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, reactive, watch } from 'vue'
import SymbolList from './components/symbol-browser/SymbolList.vue'
import SymbolContextMenu from './components/symbol-browser/SymbolContextMenu.vue'
import { realtimeWS } from './service/realtimeWSClient'
import { getApiBase } from './service/serverConfig'

const API_BASE = getApiBase() + '/api/v1/market'

// 状态
const loading = ref(false)
const lastUpdateTime = ref('')
const watchlistItems = ref([])

// 实时行情 WebSocket
const WS_SUBSCRIPTION_ID = 'symbol-browser'
let realtimeTimer = null
const REALTIME_INTERVAL = 8000

const contextMenu = reactive({
  visible: false,
  x: 0,
  y: 0,
  symbol: null
})

// ==================== 自选列表 ====================

async function fetchWatchlist() {
  loading.value = true
  try {
    const res = await fetch(`${API_BASE}/watchlist`)
    const data = await res.json()
    if (data.symbols) {
      watchlistItems.value = data.symbols
    }
  } catch (e) {
    console.error('[SymbolBrowser] 获取自选列表失败:', e)
  } finally {
    loading.value = false
  }
}

async function handleToggleWatchlist(symbol) {
  contextMenu.visible = false
  if (!symbol) return

  try {
    await fetch(`${API_BASE}/watchlist/${encodeURIComponent(symbol.symbol)}`, {
      method: 'DELETE'
    })
    watchlistItems.value = watchlistItems.value.filter((s) => s.symbol !== symbol.symbol)
  } catch (e) {
    console.error('[SymbolBrowser] 移除自选失败:', e)
  }
}

// ==================== 拖拽排序 ====================

async function handleReorder({ from, to }) {
  const list = [...watchlistItems.value]
  const [moved] = list.splice(from, 1)
  list.splice(to, 0, moved)
  watchlistItems.value = list

  try {
    const orderedSymbols = list.map((s) => s.symbol)
    await fetch(`${API_BASE}/watchlist/reorder`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbols: orderedSymbols })
    })
  } catch (e) {
    console.error('[SymbolBrowser] 排序失败:', e)
    fetchWatchlist()
  }
}

// ==================== 实时行情 ====================

async function fetchRealtimeQuotes() {
  const list = watchlistItems.value
  if (!list || list.length === 0) return

  const groups = {}
  let count = 0
  for (const s of list) {
    if (count >= 50) break
    const mt = s.market_type || 'cn_stock'
    if (!groups[mt]) groups[mt] = []
    groups[mt].push(s.symbol)
    count++
  }

  for (const [mt, syms] of Object.entries(groups)) {
    try {
      const symbolsStr = syms.join(',')
      const res = await fetch(`${API_BASE}/realtime?symbols=${encodeURIComponent(symbolsStr)}&type=${mt}`)
      const data = await res.json()
      if (data.quotes) {
        const quoteMap = {}
        for (const q of data.quotes) {
          quoteMap[q.symbol] = q
        }
        watchlistItems.value = watchlistItems.value.map((item) => {
          const q = quoteMap[item.symbol]
          if (q) {
            return { ...item, current_price: q.price, change_percent: q.change_percent }
          }
          return item
        })
      }
    } catch (e) {
      console.error('[SymbolBrowser] 获取实时行情失败:', e)
    }
  }
  lastUpdateTime.value = new Date().toLocaleTimeString()
}

function startRealtimePolling() {
  stopRealtimePolling()
  const currentSymbols = watchlistItems.value.map((s) => s.symbol).slice(0, 50)
  if (currentSymbols.length > 0) {
    realtimeWS.updateQuotesSubscription(WS_SUBSCRIPTION_ID, currentSymbols, handleWSQuotes)
  }
  fetchRealtimeQuotes()
  realtimeTimer = setInterval(fetchRealtimeQuotes, REALTIME_INTERVAL)
}

function stopRealtimePolling() {
  if (realtimeTimer) {
    clearInterval(realtimeTimer)
    realtimeTimer = null
  }
  realtimeWS.unsubscribeQuotes(WS_SUBSCRIPTION_ID)
}

function handleWSQuotes(quotes) {
  if (!quotes || quotes.length === 0) return
  const quoteMap = {}
  for (const q of quotes) {
    quoteMap[q.symbol] = q
  }
  watchlistItems.value = watchlistItems.value.map((item) => {
    const q = quoteMap[item.symbol]
    if (q) {
      return { ...item, current_price: q.price, change_percent: q.change_percent }
    }
    return item
  })
  lastUpdateTime.value = new Date().toLocaleTimeString()
}

// 右键菜单
function handleContextMenu({ event, symbol }) {
  event.preventDefault()
  contextMenu.x = event.clientX
  contextMenu.y = event.clientY
  contextMenu.symbol = symbol
  contextMenu.visible = true
}

// 双击打开图表
function handleDoubleClick(symbol) {
  handleOpenChart(symbol)
}

// 在图表中打开
function handleOpenChart(symbol) {
  contextMenu.visible = false
  if (window.electronAPI?.openSymbolInChart) {
    window.electronAPI.openSymbolInChart({
      symbol: symbol.symbol,
      name: symbol.name,
      market_type: symbol.market_type,
      exchange: symbol.exchange,
      data_source: symbol.data_source
    })
  }
}

// 复制代码
function handleCopyCode(symbol) {
  contextMenu.visible = false
  navigator.clipboard.writeText(symbol.symbol).catch(() => {
    const ta = document.createElement('textarea')
    ta.value = symbol.symbol
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  })
}

// 点击外部关闭右键菜单
function handleClickOutside() {
  contextMenu.visible = false
}

// 页面可见性
function handleVisibility() {
  if (document.hidden) {
    stopRealtimePolling()
  } else {
    startRealtimePolling()
  }
}

// 监听自选列表变化，更新 WS 订阅
watch(watchlistItems, (list) => {
  const currentSymbols = list.map((s) => s.symbol).slice(0, 50)
  if (currentSymbols.length > 0) {
    realtimeWS.updateQuotesSubscription(WS_SUBSCRIPTION_ID, currentSymbols, handleWSQuotes)
  }
})

onMounted(async () => {
  document.addEventListener('click', handleClickOutside)
  document.addEventListener('visibilitychange', handleVisibility)
  await fetchWatchlist()
  startRealtimePolling()
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('visibilitychange', handleVisibility)
  stopRealtimePolling()
})
</script>

<style scoped>
.symbol-browser {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #1e1e1e;
  color: #cccccc;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 13px;
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  padding: 4px 8px;
  background: #252526;
  border-bottom: 1px solid #333;
  flex-shrink: 0;
}

.panel-title {
  font-size: 11px;
  font-weight: 600;
  color: #ccc;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 12px;
  border-top: 1px solid #333;
  background: #252526;
  font-size: 11px;
  color: #888;
  flex-shrink: 0;
}

.status-count {
  color: #999;
}

.status-time {
  color: #666;
}
</style>
