<template>
  <div class="market-browser-page">
    <!-- 顶部市场板块切换 -->
    <MarketTabs v-model="activeMarket" :tabs="marketTabs" />

    <!-- 筛选工具栏 -->
    <FilterBar
      v-model:searchQuery="searchQuery"
      :activeFilters="activeFilters"
      @removeFilter="removeFilter"
      @clearFilters="clearFilters"
    />

    <!-- 数据表格 -->
    <DataTable
      :columns="currentColumns"
      :data="filteredData"
      :totalRows="totalRows"
      :filteredCount="filteredData.length"
      :updateTime="updateTime"
      @rowDblClick="handleRowDblClick"
      @rowContextMenu="handleRowContextMenu"
    />

    <!-- 右键菜单 -->
    <div
      v-if="contextMenu.visible"
      class="context-menu"
      :style="{ left: contextMenu.x + 'px', top: contextMenu.y + 'px' }"
    >
      <div class="menu-item" @click="openInChart(contextMenu.row)">📈 在图表中打开</div>
      <div class="menu-item" @click="addToWatchlist(contextMenu.row)">⭐ 添加到自选</div>
      <div class="menu-item" @click="copySymbol(contextMenu.row)">📋 复制代码</div>
      <div class="menu-separator"></div>
      <div class="menu-item" @click="contextMenu.visible = false">取消</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import MarketTabs from './components/market-browser/MarketTabs.vue'
import FilterBar from './components/market-browser/FilterBar.vue'
import DataTable from './components/market-browser/DataTable.vue'
import { getApiBase } from './service/serverConfig'

const API_BASE = getApiBase() + '/api/v1/market'

// 市场 Tab 定义
const marketTabs = ref([
  { key: 'crypto', label: '加密货币', icon: '₿' },
  { key: 'cn_stock', label: 'A股', icon: '🇨🇳' },
  { key: 'hk_stock', label: '港股', icon: '🇭🇰' },
  { key: 'us_stock', label: '美股', icon: '🇺🇸' },
])

const activeMarket = ref('crypto')
const searchQuery = ref('')
const activeFilters = ref([])
const tableData = ref([])
const totalRows = ref(0)
const updateTime = ref('')
const loading = ref(false)
let refreshTimer = null

// 各市场列配置
const columnConfigs = {
  crypto: [
    { key: 'symbol', label: '代码', width: 100, minWidth: 80, sticky: true, sortable: true },
    { key: 'name', label: '名称', width: 100, minWidth: 80, sticky: true },
    { key: 'price', label: '最新价', width: 110, minWidth: 90, align: 'right', type: 'number', decimals: 2, sortable: true },
    { key: 'change_pct', label: '涨跌幅', width: 90, minWidth: 80, align: 'right', sortable: true },
    { key: 'volume', label: '成交量', width: 110, minWidth: 90, align: 'right', type: 'volume', sortable: true },
    { key: 'turnover', label: '成交额', width: 110, minWidth: 90, align: 'right', type: 'volume', sortable: true },
    { key: 'high_24h', label: '24h最高', width: 100, minWidth: 80, align: 'right', type: 'number', decimals: 2, sortable: true },
    { key: 'low_24h', label: '24h最低', width: 100, minWidth: 80, align: 'right', type: 'number', decimals: 2, sortable: true },
  ],
  cn_stock: [
    { key: 'symbol', label: '代码', width: 80, minWidth: 70, sticky: true, sortable: true },
    { key: 'name', label: '名称', width: 90, minWidth: 80, sticky: true },
    { key: 'price', label: '最新价', width: 90, minWidth: 80, align: 'right', type: 'number', decimals: 2, sortable: true },
    { key: 'change_pct', label: '涨跌幅', width: 80, minWidth: 70, align: 'right', sortable: true },
    { key: 'volume', label: '成交量', width: 100, minWidth: 80, align: 'right', type: 'volume', sortable: true },
    { key: 'volume_ratio', label: '量比', width: 70, minWidth: 60, align: 'right', type: 'number', decimals: 2, sortable: true },
    { key: 'turnover_rate', label: '换手率', width: 80, minWidth: 70, align: 'right', type: 'number', decimals: 2, sortable: true },
    { key: 'total_mv', label: '总市值', width: 100, minWidth: 80, align: 'right', type: 'marketCap', sortable: true },
    { key: 'pe_ratio', label: 'P/E', width: 70, minWidth: 60, align: 'right', type: 'number', decimals: 1, sortable: true },
    { key: 'amplitude', label: '振幅', width: 70, minWidth: 60, align: 'right', type: 'number', decimals: 2, sortable: true },
  ],
  hk_stock: [
    { key: 'symbol', label: '代码', width: 80, minWidth: 70, sticky: true, sortable: true },
    { key: 'name', label: '名称', width: 100, minWidth: 80, sticky: true },
    { key: 'price', label: '最新价', width: 100, minWidth: 80, align: 'right', type: 'number', decimals: 3, sortable: true },
    { key: 'change_pct', label: '涨跌幅', width: 80, minWidth: 70, align: 'right', sortable: true },
    { key: 'volume', label: '成交量', width: 100, minWidth: 80, align: 'right', type: 'volume', sortable: true },
    { key: 'turnover', label: '成交额', width: 100, minWidth: 80, align: 'right', type: 'volume', sortable: true },
    { key: 'turnover_rate', label: '换手率', width: 80, minWidth: 70, align: 'right', type: 'number', decimals: 2, sortable: true },
    { key: 'amplitude', label: '振幅', width: 70, minWidth: 60, align: 'right', type: 'number', decimals: 2, sortable: true },
  ],
  us_stock: [
    { key: 'symbol', label: '代码', width: 80, minWidth: 70, sticky: true, sortable: true },
    { key: 'name', label: '名称', width: 120, minWidth: 90, sticky: true },
    { key: 'price', label: '最新价', width: 100, minWidth: 80, align: 'right', type: 'number', decimals: 2, sortable: true },
    { key: 'change_pct', label: '涨跌幅', width: 80, minWidth: 70, align: 'right', sortable: true },
    { key: 'volume', label: '成交量', width: 100, minWidth: 80, align: 'right', type: 'volume', sortable: true },
    { key: 'turnover', label: '成交额', width: 100, minWidth: 80, align: 'right', type: 'volume', sortable: true },
    { key: 'turnover_rate', label: '换手率', width: 80, minWidth: 70, align: 'right', type: 'number', decimals: 2, sortable: true },
    { key: 'amplitude', label: '振幅', width: 70, minWidth: 60, align: 'right', type: 'number', decimals: 2, sortable: true },
  ],
}

const currentColumns = computed(() => columnConfigs[activeMarket.value] || columnConfigs.crypto)

// 前端筛选（搜索）
const filteredData = computed(() => {
  let data = tableData.value
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    data = data.filter(row =>
      (row.symbol && row.symbol.toLowerCase().includes(q)) ||
      (row.name && row.name.toLowerCase().includes(q))
    )
  }
  // 应用筛选条件
  activeFilters.value.forEach(filter => {
    data = data.filter(row => {
      const val = row[filter.field]
      if (val == null) return false
      if (filter.op === '>') return val > filter.value
      if (filter.op === '<') return val < filter.value
      if (filter.op === '>=') return val >= filter.value
      if (filter.op === '<=') return val <= filter.value
      return true
    })
  })
  return data
})

// 获取标的浏览器数据
async function fetchData() {
  loading.value = true
  try {
    const url = `${API_BASE}/browser/data?type=${activeMarket.value}&limit=500`
    const resp = await fetch(url)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const result = await resp.json()
    tableData.value = result.data || []
    totalRows.value = result.total || tableData.value.length
    updateTime.value = new Date().toLocaleTimeString('zh-CN')
  } catch (e) {
    console.error('[MarketBrowser] fetchData error:', e)
    // 降级尝试：使用现有的 symbols + realtime 接口
    await fetchDataFallback()
  } finally {
    loading.value = false
  }
}

// 降级方案：使用现有接口组合数据
async function fetchDataFallback() {
  try {
    const resp = await fetch(`${API_BASE}/symbols?type=${activeMarket.value}`)
    if (!resp.ok) return
    const result = await resp.json()
    const symbols = result.symbols || []
    tableData.value = symbols.map(s => ({
      symbol: s.symbol,
      name: s.name,
      price: s.current_price,
      change_pct: s.change_percent,
    }))
    totalRows.value = result.total || tableData.value.length
    updateTime.value = new Date().toLocaleTimeString('zh-CN')
  } catch (e) {
    console.error('[MarketBrowser] fetchDataFallback error:', e)
  }
}

function removeFilter(idx) {
  activeFilters.value.splice(idx, 1)
}

function clearFilters() {
  activeFilters.value = []
}

function handleRowDblClick(row) {
  openInChart(row)
}

function handleRowContextMenu(event, row) {
  contextMenu.value = {
    visible: true,
    x: event.clientX,
    y: event.clientY,
    row
  }
}

const contextMenu = ref({ visible: false, x: 0, y: 0, row: null })

function openInChart(row) {
  contextMenu.value.visible = false
  if (window.electronAPI?.openSymbolInChart) {
    window.electronAPI.openSymbolInChart({
      symbol: row.symbol,
      name: row.name,
      market_type: activeMarket.value,
      exchange: row.exchange || '',
      data_source: row.data_source || ''
    })
  }
}

async function addToWatchlist(row) {
  contextMenu.value.visible = false
  try {
    await fetch(`${API_BASE}/watchlist`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        symbol: row.symbol,
        name: row.name,
        market_type: activeMarket.value,
        exchange: row.exchange || '',
        data_source: row.data_source || ''
      })
    })
  } catch (e) {
    console.error('[MarketBrowser] addToWatchlist error:', e)
  }
}

function copySymbol(row) {
  contextMenu.value.visible = false
  navigator.clipboard.writeText(row.symbol).catch(() => {})
}

// 关闭右键菜单
function handleGlobalClick() {
  contextMenu.value.visible = false
}

function startAutoRefresh() {
  stopAutoRefresh()
  // 交易时段 8 秒刷新
  refreshTimer = setInterval(fetchData, 8000)
}

function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

watch(activeMarket, () => {
  tableData.value = []
  fetchData()
})

onMounted(() => {
  fetchData()
  startAutoRefresh()
  document.addEventListener('click', handleGlobalClick)
})

onUnmounted(() => {
  stopAutoRefresh()
  document.removeEventListener('click', handleGlobalClick)
})
</script>

<style scoped>
.market-browser-page {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #1e1e1e;
  overflow: hidden;
}

.context-menu {
  position: fixed;
  z-index: 1000;
  background: #2d2d30;
  border: 1px solid #454545;
  border-radius: 4px;
  padding: 4px 0;
  min-width: 160px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
}

.menu-item {
  padding: 6px 16px;
  font-size: 13px;
  color: #e0e0e0;
  cursor: pointer;
  white-space: nowrap;
}

.menu-item:hover {
  background: #094771;
}

.menu-separator {
  height: 1px;
  background: #454545;
  margin: 4px 0;
}
</style>
