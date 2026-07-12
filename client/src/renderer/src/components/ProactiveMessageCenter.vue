<template>
  <div class="section-card pmc">
    <!-- Header -->
    <div class="pmc-header">
      <div class="pmc-title-block">
        <div class="section-title">
          主动消息中心
          <span v-if="unreadCount > 0" class="pmc-unread-badge">{{ unreadCount }}</span>
        </div>
        <div class="section-desc">AI 生成的异动分析与机会扫描消息，每 30 秒自动刷新。</div>
      </div>
      <div class="pmc-actions">
        <button class="btn btn-browse btn-sm" @click="manualRefresh" :disabled="loading">
          {{ loading ? '刷新中...' : '刷新' }}
        </button>
        <button class="btn btn-primary btn-sm" @click="markAllRead"
          :disabled="unreadCount === 0 || markingAll">
          {{ markingAll ? '处理中...' : '全部已读' }}
        </button>
      </div>
    </div>

    <!-- Stats bar -->
    <div v-if="stats" class="pmc-stats">
      <span class="pmc-stat">总计 <strong>{{ stats.total ?? 0 }}</strong></span>
      <span class="pmc-stat pmc-stat-unread">未读 <strong>{{ stats.unread ?? 0 }}</strong></span>
      <span class="pmc-stat">近24小时 <strong>{{ stats.recent_24h ?? 0 }}</strong></span>
    </div>

    <!-- Filters -->
    <div class="pmc-filters">
      <div class="pmc-filter">
        <label>类型</label>
        <select v-model="filters.message_type" class="pmc-select" @change="resetPage">
          <option value="">全部</option>
          <option value="anomaly_response">异动分析</option>
          <option value="opportunity">机会扫描</option>
        </select>
      </div>
      <div class="pmc-filter">
        <label>状态</label>
        <select v-model="filters.status" class="pmc-select" @change="resetPage">
          <option value="">全部</option>
          <option value="unread">未读</option>
          <option value="read">已读</option>
          <option value="dismissed">已忽略</option>
          <option value="acted">已采纳</option>
        </select>
      </div>
      <div class="pmc-filter">
        <label>严重度</label>
        <select v-model="filters.severity" class="pmc-select" @change="resetPage">
          <option value="">全部</option>
          <option value="info">信息</option>
          <option value="warning">警告</option>
          <option value="critical">严重</option>
        </select>
      </div>
    </div>

    <!-- Error -->
    <div v-if="error" class="section-error">{{ error }}</div>

    <!-- Loading (initial) -->
    <div v-if="loading && !messages.length" class="pmc-loading">
      <div class="spinner"></div>
      <div>加载中...</div>
    </div>

    <!-- Table -->
    <div v-else-if="messages.length" class="table-wrap">
      <table class="admin-table">
        <thead>
          <tr>
            <th>类型</th>
            <th>代码</th>
            <th>名称</th>
            <th>触发摘要</th>
            <th>信号</th>
            <th>严重度</th>
            <th>置信度</th>
            <th>状态</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="msg in messages" :key="msg.id"
            :class="{ 'pmc-row-unread': msg.status === 'unread' }"
            @click="openDetail(msg)">
            <td>
              <span :class="['status-badge', messageTypeClass(msg.message_type)]">
                {{ messageTypeLabel(msg.message_type) }}
              </span>
            </td>
            <td>{{ msg.symbol || '-' }}</td>
            <td>{{ msg.symbol_name || '-' }}</td>
            <td class="pmc-summary-cell">{{ msg.trigger_summary || '-' }}</td>
            <td>
              <span :class="['status-badge', signalClass(msg.signal)]">{{ signalLabel(msg.signal) }}</span>
            </td>
            <td>
              <span :class="['status-badge', severityClass(msg.trigger_severity)]">
                {{ severityLabel(msg.trigger_severity) }}
              </span>
            </td>
            <td>{{ msg.confidence != null ? (msg.confidence * 100).toFixed(0) + '%' : '-' }}</td>
            <td>
              <span :class="['status-badge', statusClass(msg.status)]">{{ statusLabel(msg.status) }}</span>
            </td>
            <td class="pmc-time-cell">{{ formatDateTime(msg.created_at) }}</td>
            <td class="actions-cell" @click.stop>
              <button class="btn btn-browse btn-sm" @click="openDetail(msg)">详情</button>
              <button v-if="msg.status !== 'dismissed'" class="btn btn-browse btn-sm"
                @click="dismissMessage(msg)" :disabled="actionPending[msg.id]">
                忽略
              </button>
              <button v-if="msg.status !== 'acted'" class="btn btn-primary btn-sm"
                @click="actMessage(msg)" :disabled="actionPending[msg.id]">
                已采纳
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Empty -->
    <div v-else class="section-empty">暂无消息</div>

    <!-- Pagination -->
    <div v-if="total > pageSize" class="pmc-pagination">
      <button class="btn btn-browse btn-sm" @click="goPage(page - 1)" :disabled="page <= 1">
        上一页
      </button>
      <span class="pmc-page-info">第 {{ page }} / {{ totalPages }} 页 (共 {{ total }} 条)</span>
      <button class="btn btn-browse btn-sm" @click="goPage(page + 1)" :disabled="page >= totalPages">
        下一页
      </button>
    </div>

    <!-- Detail Dialog -->
    <div class="dialog-overlay" v-if="detail.show">
      <div class="dialog-box dialog-box-wide pmc-detail-dialog">
        <h3>消息详情</h3>
        <div v-if="detail.loading" class="section-empty">加载中...</div>
        <template v-else-if="detail.data">
          <div class="kv-grid">
            <div class="kv-item">
              <span class="kv-label">类型</span>
              <span class="kv-value">
                <span :class="['status-badge', messageTypeClass(detail.data.message_type)]">
                  {{ messageTypeLabel(detail.data.message_type) }}
                </span>
              </span>
            </div>
            <div class="kv-item">
              <span class="kv-label">代码</span>
              <span class="kv-value">{{ detail.data.symbol || '-' }}</span>
            </div>
            <div class="kv-item">
              <span class="kv-label">名称</span>
              <span class="kv-value">{{ detail.data.symbol_name || '-' }}</span>
            </div>
            <div class="kv-item">
              <span class="kv-label">信号</span>
              <span class="kv-value">
                <span :class="['status-badge', signalClass(detail.data.signal)]">
                  {{ signalLabel(detail.data.signal) }}
                </span>
              </span>
            </div>
            <div class="kv-item">
              <span class="kv-label">严重度</span>
              <span class="kv-value">
                <span :class="['status-badge', severityClass(detail.data.trigger_severity)]">
                  {{ severityLabel(detail.data.trigger_severity) }}
                </span>
              </span>
            </div>
            <div class="kv-item">
              <span class="kv-label">置信度</span>
              <span class="kv-value">
                {{ detail.data.confidence != null ? (detail.data.confidence * 100).toFixed(0) + '%' : '-' }}
              </span>
            </div>
            <div class="kv-item">
              <span class="kv-label">触发类型</span>
              <span class="kv-value">{{ detail.data.trigger_type || '-' }}</span>
            </div>
            <div class="kv-item">
              <span class="kv-label">状态</span>
              <span class="kv-value">
                <span :class="['status-badge', statusClass(detail.data.status)]">
                  {{ statusLabel(detail.data.status) }}
                </span>
              </span>
            </div>
            <div class="kv-item">
              <span class="kv-label">创建时间</span>
              <span class="kv-value">{{ formatDateTime(detail.data.created_at) }}</span>
            </div>
            <div class="kv-item">
              <span class="kv-label">阅读时间</span>
              <span class="kv-value">{{ formatDateTime(detail.data.read_at) }}</span>
            </div>
          </div>

          <div v-if="detail.data.trigger_summary" class="section-subtitle">触发摘要</div>
          <div v-if="detail.data.trigger_summary" class="pmc-summary-text">
            {{ detail.data.trigger_summary }}
          </div>

          <div v-if="detail.data.analysis_summary" class="section-subtitle">分析摘要</div>
          <div v-if="detail.data.analysis_summary" class="pmc-summary-text">
            {{ detail.data.analysis_summary }}
          </div>

          <div class="section-subtitle">分析内容</div>
          <div class="pmc-analysis-content">{{ detail.data.analysis_content || '暂无内容' }}</div>
        </template>
        <div class="dialog-actions">
          <button v-if="detail.data && detail.data.status !== 'dismissed'" class="btn btn-browse"
            @click="dismissMessage(detail.data)" :disabled="actionPending[detail.data.id]">
            忽略
          </button>
          <button v-if="detail.data && detail.data.status !== 'acted'" class="btn btn-primary"
            @click="actMessage(detail.data)" :disabled="actionPending[detail.data.id]">
            已采纳
          </button>
          <button class="btn btn-browse" @click="detail.show = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- Toast -->
    <div class="admin-toast-bar" v-if="toast">
      <div :class="['admin-toast', toast.type]">{{ toast.message }}</div>
    </div>
  </div>
</template>

<script setup>
/**
 * ProactiveMessageCenter - 主动消息中心
 *
 * 展示 AI 生成的异动分析与机会扫描消息，支持筛选、分页、详情查看、
 * 状态操作（忽略/已采纳/全部已读），每 30 秒自动刷新。
 */
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { getApiBase } from '../service/serverConfig'

// ==================== 常量 ====================

const PAGE_SIZE = 20

// ==================== 响应式状态 ====================

const messages = ref([])
const total = ref(0)
const unreadCount = ref(0)
const stats = ref(null)
const loading = ref(false)
const error = ref('')
const page = ref(1)
const pageSize = PAGE_SIZE
const toast = ref(null)
const markingAll = ref(false)

const filters = reactive({
  message_type: '',
  status: '',
  severity: '',
})

const actionPending = reactive({})

const detail = reactive({
  show: false,
  loading: false,
  data: null,
})

// ==================== 计算属性 ====================

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

// ==================== 工具函数 ====================

/**
 * 将 ISO 时间字符串格式化为本地 "YYYY-MM-DD HH:mm:ss"。
 */
function formatDateTime(iso) {
  if (!iso) return '-'
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return '-'
    const pad = (n) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  } catch {
    return '-'
  }
}

/**
 * 显示 toast 消息，3 秒后自动清除。
 */
function showToast(type, message) {
  toast.value = { type, message }
  setTimeout(() => { toast.value = null }, 3000)
}

function messageTypeLabel(t) {
  if (t === 'anomaly_response') return '异动分析'
  if (t === 'opportunity') return '机会扫描'
  return t || '-'
}
function messageTypeClass(t) {
  if (t === 'anomaly_response') return 'badge-warning'
  if (t === 'opportunity') return 'badge-info'
  return 'badge-muted'
}

function signalLabel(s) {
  if (s === 'buy') return '买入'
  if (s === 'sell') return '卖出'
  if (s === 'hold') return '持有'
  if (s === 'watch') return '观察'
  return s || '-'
}
function signalClass(s) {
  if (s === 'buy') return 'badge-success'
  if (s === 'sell') return 'badge-error'
  if (s === 'hold') return 'badge-info'
  return 'badge-muted'
}

function severityLabel(s) {
  if (s === 'critical') return '严重'
  if (s === 'warning') return '警告'
  if (s === 'info') return '信息'
  return s || '-'
}
function severityClass(s) {
  if (s === 'critical') return 'badge-error'
  if (s === 'warning') return 'badge-warning'
  return 'badge-muted'
}

function statusLabel(s) {
  if (s === 'unread') return '未读'
  if (s === 'read') return '已读'
  if (s === 'dismissed') return '已忽略'
  if (s === 'acted') return '已采纳'
  return s || '-'
}
function statusClass(s) {
  if (s === 'unread') return 'badge-info'
  if (s === 'acted') return 'badge-success'
  return 'badge-muted'
}

// ==================== API 调用 ====================

/**
 * 统一 fetch 封装，处理 401 与 HTTP 错误。
 */
async function adminFetch(path, options = {}) {
  const resp = await fetch(`${getApiBase()}${path}`, {
    credentials: 'include',
    ...options,
  })
  if (resp.status === 401) throw new Error('未登录或会话已过期')
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || err.error || `HTTP ${resp.status}`)
  }
  return resp.json()
}

/**
 * 获取消息列表。
 */
async function fetchMessages() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    params.set('page', String(page.value))
    params.set('page_size', String(pageSize))
    if (filters.message_type) params.set('message_type', filters.message_type)
    if (filters.status) params.set('status', filters.status)
    if (filters.severity) params.set('severity', filters.severity)
    const data = await adminFetch(`/api/v1/proactive-messages?${params.toString()}`)
    messages.value = data.items || []
    total.value = data.total ?? 0
    unreadCount.value = data.unread_count ?? 0
    error.value = ''
  } catch (e) {
    if (!messages.value.length) {
      error.value = e.message || '未知错误'
    }
  } finally {
    loading.value = false
  }
}

/**
 * 获取统计数据（静默失败）。
 */
async function fetchStats() {
  try {
    stats.value = await adminFetch('/api/v1/proactive-messages/stats')
  } catch {
    // stats is optional
  }
}

/**
 * 手动刷新（按钮触发）。
 */
async function manualRefresh() {
  await Promise.all([fetchMessages(), fetchStats()])
}

/**
 * 筛选变化时重置到第一页。
 */
function resetPage() {
  page.value = 1
  fetchMessages()
}

/**
 * 翻页。
 */
function goPage(p) {
  if (p < 1 || p > totalPages.value) return
  page.value = p
  fetchMessages()
}

/**
 * 打开消息详情，GET /{id} 会自动将 unread 标记为 read。
 */
async function openDetail(msg) {
  detail.show = true
  detail.loading = true
  detail.data = null
  try {
    const data = await adminFetch(`/api/v1/proactive-messages/${msg.id}`)
    detail.data = data.item
    // 同步本地列表状态（unread -> read）
    const idx = messages.value.findIndex(m => m.id === msg.id)
    if (idx !== -1 && messages.value[idx].status === 'unread') {
      messages.value[idx].status = 'read'
      messages.value[idx].read_at = data.item?.read_at || new Date().toISOString()
      unreadCount.value = Math.max(0, unreadCount.value - 1)
    }
  } catch (e) {
    showToast('error', `加载失败: ${e.message}`)
    detail.show = false
  } finally {
    detail.loading = false
  }
}

/**
 * 更新消息状态（忽略/已采纳）。
 */
async function updateMessageStatus(msg, newStatus) {
  actionPending[msg.id] = true
  try {
    await adminFetch(`/api/v1/proactive-messages/${msg.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus }),
    })
    const wasUnread = msg.status === 'unread'
    msg.status = newStatus
    if (wasUnread) {
      unreadCount.value = Math.max(0, unreadCount.value - 1)
    }
    if (detail.data && detail.data.id === msg.id) {
      detail.data.status = newStatus
    }
    showToast('success', newStatus === 'dismissed' ? '已忽略' : '已采纳')
  } catch (e) {
    showToast('error', `操作失败: ${e.message}`)
  } finally {
    actionPending[msg.id] = false
  }
}

function dismissMessage(msg) {
  updateMessageStatus(msg, 'dismissed')
}

function actMessage(msg) {
  updateMessageStatus(msg, 'acted')
}

/**
 * 全部已读。
 */
async function markAllRead() {
  markingAll.value = true
  try {
    await adminFetch('/api/v1/proactive-messages/read-all', { method: 'POST' })
    showToast('success', '已全部标记为已读')
    await Promise.all([fetchMessages(), fetchStats()])
  } catch (e) {
    showToast('error', `操作失败: ${e.message}`)
  } finally {
    markingAll.value = false
  }
}

// ==================== 生命周期 ====================

let pollTimer = null

onMounted(() => {
  fetchMessages()
  fetchStats()
  pollTimer = setInterval(() => {
    fetchMessages()
    fetchStats()
  }, 30000)
})

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<style scoped>
/* ==================== 容器 ==================== */
.pmc {
  position: relative;
}

/* ==================== 复用 AdminPanel 样式 ==================== */

.section-card {
  background: #252526;
  border: 1px solid #333;
  border-radius: 12px;
  padding: 20px 24px;
  margin-bottom: 16px;
}
.section-title {
  font-size: 16px;
  font-weight: 600;
  color: #fff;
  margin-bottom: 4px;
}
.section-desc {
  font-size: 12px;
  color: #888;
  margin-bottom: 20px;
}
.section-subtitle {
  font-size: 13px;
  font-weight: 600;
  color: #ccc;
  margin: 12px 0 8px;
}
.section-empty {
  text-align: center;
  padding: 24px 12px;
  color: #666;
  font-size: 13px;
}
.section-error {
  color: #da3633;
  font-size: 13px;
  padding: 8px 12px;
  background: rgba(218, 54, 51, 0.1);
  border: 1px solid rgba(218, 54, 51, 0.3);
  border-radius: 6px;
  margin-bottom: 12px;
}

/* ==================== 按钮 ==================== */
.btn {
  padding: 7px 16px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: background 0.15s;
  white-space: nowrap;
  flex-shrink: 0;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn-primary {
  background: #0e639c;
  color: #fff;
  border-color: #0e639c;
}
.btn-primary:hover:not(:disabled) {
  background: #1177bb;
}
.btn-browse {
  background: #2d2d2d;
  color: #ccc;
  border-color: #444;
  padding: 7px 12px;
}
.btn-browse:hover:not(:disabled) {
  background: #3a3a3a;
}
.btn-sm {
  padding: 4px 10px;
  font-size: 12px;
}

/* ==================== KV 网格 ==================== */
.kv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}
.kv-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 6px;
}
.kv-label {
  font-size: 11px;
  color: #888;
}
.kv-value {
  font-size: 13px;
  color: #ddd;
  word-break: break-all;
}

/* ==================== 表格 ==================== */
.table-wrap {
  overflow-x: auto;
  margin-top: 8px;
}
.admin-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.admin-table th {
  text-align: left;
  padding: 8px 10px;
  background: #2a2a2b;
  color: #999;
  font-weight: 500;
  border-bottom: 1px solid #383838;
  white-space: nowrap;
}
.admin-table td {
  padding: 6px 10px;
  border-bottom: 1px solid #2a2a2c;
  color: #ddd;
}
.admin-table tr:last-child td {
  border-bottom: none;
}
.admin-table tbody tr {
  cursor: pointer;
}
.admin-table tbody tr:hover td {
  background: #2a2a2d;
}

/* ==================== 状态徽章 ==================== */
.status-badge {
  display: inline-block;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 3px;
  font-weight: 500;
  white-space: nowrap;
}
.badge-success {
  color: #2ea043;
  background: rgba(46, 160, 67, 0.15);
}
.badge-error {
  color: #da3633;
  background: rgba(218, 54, 51, 0.15);
}
.badge-muted {
  color: #999;
  background: rgba(150, 150, 150, 0.15);
}
.badge-info {
  color: #4a9eff;
  background: rgba(74, 158, 255, 0.15);
}
.badge-warning {
  color: #d29922;
  background: rgba(210, 153, 34, 0.15);
}

/* ==================== 操作按钮组 ==================== */
.actions-cell {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

/* ==================== 加载状态 ==================== */
.pmc-loading {
  text-align: center;
  padding: 40px 20px;
  color: #888;
}
.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #333;
  border-top-color: #4a9eff;
  border-radius: 50%;
  margin: 0 auto 12px;
  animation: pmc-spin 0.8s linear infinite;
}
@keyframes pmc-spin {
  to { transform: rotate(360deg); }
}

/* ==================== 对话框 ==================== */
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
}
.dialog-box {
  background: #2e2c29;
  border: 1px solid #444;
  border-radius: 8px;
  padding: 24px;
  max-width: 400px;
  width: 90%;
}
.dialog-box h3 {
  margin: 0 0 12px;
  font-size: 18px;
  color: #fff;
}
.dialog-box-wide {
  max-width: 600px;
}
.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 16px;
}

/* ==================== Toast ==================== */
.admin-toast-bar {
  position: fixed;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 10001;
}
.admin-toast {
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 13px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
}
.admin-toast.success {
  background: rgba(46, 160, 67, 0.2);
  color: #2ea043;
  border: 1px solid rgba(46, 160, 67, 0.4);
}
.admin-toast.error {
  background: rgba(218, 54, 51, 0.2);
  color: #da3633;
  border: 1px solid rgba(218, 54, 51, 0.4);
}

/* ==================== 组件专属样式 ==================== */

.pmc-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}
.pmc-title-block {
  flex: 1;
  min-width: 0;
}
.pmc-title-block .section-desc {
  margin-bottom: 0;
}
.pmc-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.pmc-unread-badge {
  display: inline-block;
  background: #da3633;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 10px;
  margin-left: 8px;
  vertical-align: middle;
  line-height: 16px;
}

.pmc-stats {
  display: flex;
  gap: 20px;
  padding: 10px 14px;
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 6px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.pmc-stat {
  font-size: 12px;
  color: #888;
}
.pmc-stat strong {
  color: #ddd;
  font-size: 13px;
  margin-left: 4px;
}
.pmc-stat-unread strong {
  color: #da3633;
}

.pmc-filters {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.pmc-filter {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.pmc-filter label {
  font-size: 11px;
  color: #888;
}
.pmc-select {
  padding: 5px 10px;
  background: #1a1a1a;
  border: 1px solid #444;
  border-radius: 6px;
  color: #fff;
  font-size: 12px;
  outline: none;
  min-width: 120px;
  cursor: pointer;
}
.pmc-select:focus {
  border-color: #4a9eff;
}

.pmc-row-unread td {
  border-left: 3px solid #4a9eff;
}
.pmc-row-unread td:first-child {
  padding-left: 7px;
}

.pmc-summary-cell {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pmc-time-cell {
  white-space: nowrap;
  color: #999;
}

.pmc-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  margin-top: 16px;
}
.pmc-page-info {
  font-size: 12px;
  color: #999;
}

.pmc-detail-dialog {
  max-width: 720px;
  max-height: 85vh;
  overflow-y: auto;
}
.pmc-summary-text {
  font-size: 13px;
  color: #ccc;
  line-height: 1.6;
  padding: 8px 12px;
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 6px;
}
.pmc-analysis-content {
  font-size: 13px;
  color: #ddd;
  line-height: 1.7;
  padding: 12px 14px;
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 400px;
  overflow-y: auto;
}
</style>
