<template>
  <div class="home-page">
    <div class="home-header">
      <h2 class="section-title">市场概览</h2>
      <div class="header-actions">
        <span v-if="lastUpdate" class="update-time">更新于 {{ lastUpdate }}</span>
        <button class="refresh-btn" :disabled="loading" @click="fetchIndices">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" :class="{ spinning: loading }">
            <path d="M13.45 2.55A7 7 0 0 0 2.05 8H0l3 3 3-3H4a5 5 0 0 1 8.54-3.54l1.41-1.41zM13 8l-3 3h2a5 5 0 0 1-8.54 3.54l-1.41 1.41A7 7 0 0 0 13.95 8H13z"/>
          </svg>
        </button>
      </div>
    </div>

    <div class="indices-grid">
      <IndexCard
        v-for="item in indices"
        :key="item.symbol"
        :index="item"
        @click="handleIndexClick"
      />
    </div>

    <div v-if="error" class="error-notice">
      <span>{{ error }}</span>
      <button @click="fetchIndices">重试</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import IndexCard from './components/home/IndexCard.vue'
import { getApiBase } from './service/serverConfig'

const API_BASE = getApiBase() + '/api/v1/market'

const indices = ref([
  { symbol: '000001.SH', name: '上证综指', price: null, change: null, change_percent: null, sparkline: null },
  { symbol: '399001.SZ', name: '深证成指', price: null, change: null, change_percent: null, sparkline: null },
  { symbol: '399006.SZ', name: '创业板指', price: null, change: null, change_percent: null, sparkline: null },
  { symbol: 'HSI', name: '恒生指数', price: null, change: null, change_percent: null, sparkline: null },
  { symbol: '^IXIC', name: '纳斯达克', price: null, change: null, change_percent: null, sparkline: null },
  { symbol: '^DJI', name: '道琼斯', price: null, change: null, change_percent: null, sparkline: null },
  { symbol: 'BTCUSDT', name: 'BTC/USDT', price: null, change: null, change_percent: null, sparkline: null },
  { symbol: 'ETHUSDT', name: 'ETH/USDT', price: null, change: null, change_percent: null, sparkline: null },
])

const loading = ref(false)
const lastUpdate = ref('')
const error = ref('')
let refreshTimer = null

async function fetchIndices() {
  loading.value = true
  error.value = ''
  try {
    const symbolList = indices.value.map(i => i.symbol).join(',')
    const resp = await fetch(`${API_BASE}/indices?symbols=${encodeURIComponent(symbolList)}`)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()

    if (data.quotes && Array.isArray(data.quotes)) {
      data.quotes.forEach(q => {
        const idx = indices.value.find(i => i.symbol === q.symbol)
        if (idx) {
          idx.price = q.price
          idx.change = q.change
          idx.change_percent = q.change_percent
          if (q.sparkline) idx.sparkline = q.sparkline
        }
      })
    }
    lastUpdate.value = new Date().toLocaleTimeString('zh-CN')
  } catch (e) {
    error.value = `数据加载失败: ${e.message}`
    console.error('[Home] fetchIndices error:', e)
  } finally {
    loading.value = false
  }
}

function handleIndexClick(item) {
  // 通知主进程打开对应图表
  if (window.electronAPI && window.electronAPI.openChart) {
    window.electronAPI.openChart(item.symbol, item.name)
  }
}

function startAutoRefresh() {
  stopAutoRefresh()
  refreshTimer = setInterval(fetchIndices, 30000) // 30秒刷新
}

function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

onMounted(() => {
  fetchIndices()
  startAutoRefresh()
})

onUnmounted(() => {
  stopAutoRefresh()
})
</script>

<style scoped>
.home-page {
  width: 100%;
  height: 100%;
  background: #1e1e1e;
  padding: 24px;
  box-sizing: border-box;
  overflow-y: auto;
  color: #e0e0e0;
}

.home-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: #fff;
  margin: 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.update-time {
  font-size: 12px;
  color: #888;
}

.refresh-btn {
  background: none;
  border: 1px solid #555;
  border-radius: 4px;
  color: #ccc;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.2s;
}

.refresh-btn:hover {
  background: #333;
}

.refresh-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.indices-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}

.error-notice {
  margin-top: 16px;
  padding: 10px 14px;
  background: #3a2020;
  border: 1px solid #5a3030;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: #ef5350;
}

.error-notice button {
  background: #ef5350;
  color: #fff;
  border: none;
  border-radius: 4px;
  padding: 4px 12px;
  cursor: pointer;
  font-size: 12px;
}
</style>
