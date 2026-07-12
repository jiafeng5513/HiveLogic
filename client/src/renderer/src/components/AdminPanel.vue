<template>
  <div class="admin-panel">
    <!-- Toast -->
    <div class="admin-toast-bar" v-if="toast">
      <div :class="['admin-toast', toast.type]">{{ toast.message }}</div>
    </div>

    <!-- Confirm Dialog -->
    <div class="dialog-overlay" v-if="confirmDialog.show">
      <div class="dialog-box">
        <h3>{{ confirmDialog.title }}</h3>
        <p>{{ confirmDialog.message }}</p>
        <div class="dialog-actions">
          <button class="btn btn-browse" @click="cancelConfirm">{{ confirmDialog.cancelText }}</button>
          <button class="btn btn-primary" @click="confirmConfirm">{{ confirmDialog.confirmText }}</button>
        </div>
      </div>
    </div>

    <!-- Initial Loading -->
    <div v-if="!status && !statusError" class="loading-state">
      <div class="spinner"></div>
      <div>正在加载管理面板...</div>
    </div>

    <!-- Full Error -->
    <div v-else-if="statusError && !status" class="error-state">
      <div class="error-title">加载失败</div>
      <div class="error-desc">{{ statusError }}</div>
      <button class="btn btn-primary" @click="refreshAll">重试</button>
    </div>

    <!-- Main Content -->
    <template v-else>
      <!-- 1. 进程信息 -->
      <div class="section-card">
        <div class="section-title">进程信息</div>
        <div class="section-desc">DSA 后端进程运行状态与版本信息。</div>
        <div v-if="processInfo" class="kv-grid">
          <div class="kv-item">
            <span class="kv-label">运行时长</span>
            <span class="kv-value">{{ formatUptime(processInfo.uptime_seconds) }}</span>
          </div>
          <div class="kv-item">
            <span class="kv-label">启动时间</span>
            <span class="kv-value">{{ formatDateTime(processInfo.started_at) }}</span>
          </div>
          <div class="kv-item">
            <span class="kv-label">Python 版本</span>
            <span class="kv-value">{{ processInfo.python_version || '-' }}</span>
          </div>
          <div class="kv-item">
            <span class="kv-label">进程 PID</span>
            <span class="kv-value">{{ processInfo.pid ?? '-' }}</span>
          </div>
          <div class="kv-item">
            <span class="kv-label">服务版本</span>
            <span class="kv-value">{{ processInfo.version || '-' }}</span>
          </div>
        </div>
        <div v-else class="section-empty">暂无数据</div>
      </div>

      <!-- 2. WebSocket 中继 -->
      <div class="section-card">
        <div class="section-title">WebSocket 中继</div>
        <div class="section-desc">实时行情 WebSocket 客户端连接状态。</div>
        <div v-if="getSectionError('ws_relay')" class="section-error">{{ getSectionError('ws_relay') }}</div>
        <template v-else>
          <div class="kv-grid" v-if="hasEntries(wsRelay)">
            <div class="kv-item" v-for="[k, v] in kvEntries(wsRelay)" :key="k">
              <span class="kv-label">{{ k }}</span>
              <span class="kv-value">{{ formatValue(v) }}</span>
            </div>
          </div>
          <div class="section-subtitle" v-if="wsClientCount !== null">
            客户端数量: <strong>{{ wsClientCount }}</strong>
          </div>
          <div v-if="clientsError" class="section-error">{{ clientsError }}</div>
          <div v-else-if="wsClients.length" class="table-wrap">
            <table class="admin-table">
              <thead>
                <tr>
                  <th>IP</th>
                  <th>状态</th>
                  <th>报价订阅</th>
                  <th>深度订阅</th>
                  <th>订阅品种</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(c, i) in wsClients" :key="i">
                  <td>{{ c.ip || '-' }}</td>
                  <td><span :class="['status-badge', stateClass(c.state)]">{{ c.state || '-' }}</span></td>
                  <td>{{ c.subscribed_quotes ?? 0 }}</td>
                  <td>{{ c.subscribed_depth ?? 0 }}</td>
                  <td class="symbol-cell">{{ (c.subscribed_symbols || []).join(', ') || '-' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="section-empty">暂无连接的客户端</div>
        </template>
      </div>

      <!-- 3. 调度任务 -->
      <div class="section-card">
        <div class="section-title">调度任务</div>
        <div class="section-desc">定时任务调度状态，可手动触发执行。</div>
        <div v-if="getSectionError('scheduler')" class="section-error">{{ getSectionError('scheduler') }}</div>
        <template v-else-if="schedulerTasks.length">
          <div class="table-wrap">
            <table class="admin-table">
              <thead>
                <tr>
                  <th>任务名</th>
                  <th>调度时间</th>
                  <th>上次运行</th>
                  <th>上次状态</th>
                  <th>耗时(秒)</th>
                  <th>下次运行</th>
                  <th>启用</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="task in schedulerTasks" :key="task.name">
                  <td>{{ task.name }}</td>
                  <td>{{ task.schedule_time || '-' }}</td>
                  <td>{{ formatDateTime(task.last_run) }}</td>
                  <td>
                    <span :class="['status-badge', taskStatusClass(task.last_status)]">
                      {{ task.last_status || '未运行' }}
                    </span>
                  </td>
                  <td>{{ task.last_duration_seconds != null ? Number(task.last_duration_seconds).toFixed(2) : '-' }}</td>
                  <td>{{ formatDateTime(task.next_run) }}</td>
                  <td>
                    <span :class="['status-badge', task.enabled ? 'badge-success' : 'badge-muted']">
                      {{ task.enabled ? '是' : '否' }}
                    </span>
                  </td>
                  <td>
                    <button class="btn btn-browse btn-sm"
                      @click="triggerTask(task.name)"
                      :disabled="pendingActions['trigger_' + task.name]">
                      {{ pendingActions['trigger_' + task.name] ? '执行中...' : '触发' }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
        <div v-else-if="schedulerNote" class="section-empty">{{ schedulerNote }}</div>
        <div v-else class="section-empty">暂无调度任务</div>
      </div>

      <!-- 4. 行情采集器 -->
      <div class="section-card">
        <div class="section-title">行情采集器</div>
        <div class="section-desc">市场数据采集器状态与手动采集/归档操作。</div>
        <div v-if="getSectionError('collector')" class="section-error">{{ getSectionError('collector') }}</div>
        <template v-else>
          <div class="kv-grid" v-if="hasEntries(collectorData)">
            <div class="kv-item" v-for="[k, v] in kvEntries(collectorData)" :key="k">
              <span class="kv-label">{{ k }}</span>
              <span class="kv-value">{{ formatValue(v) }}</span>
            </div>
          </div>
          <div v-else class="section-empty">暂无采集器数据</div>

          <div class="action-group">
            <div class="action-label">采集</div>
            <div class="action-buttons">
              <button v-for="m in COLLECT_MARKETS" :key="m.key"
                class="btn btn-browse btn-sm"
                @click="collectMarket(m.key)"
                :disabled="pendingActions['collect_' + m.key]">
                {{ pendingActions['collect_' + m.key] ? m.label + '...' : m.label }}
              </button>
            </div>
          </div>
          <div class="action-group">
            <div class="action-label">归档</div>
            <div class="action-buttons">
              <button v-for="m in ARCHIVE_MARKETS" :key="m.key"
                class="btn btn-browse btn-sm"
                @click="archiveMarket(m.key)"
                :disabled="pendingActions['archive_' + m.key]">
                {{ pendingActions['archive_' + m.key] ? m.label + '...' : m.label }}
              </button>
            </div>
          </div>
        </template>
      </div>

      <!-- 5. 缓存指标 -->
      <div class="section-card">
        <div class="section-title">缓存指标</div>
        <div class="section-desc">行情缓存命中情况与磁盘使用。</div>
        <div v-if="getSectionError('cache_metrics')" class="section-error">{{ getSectionError('cache_metrics') }}</div>
        <template v-else>
          <div class="kv-grid" v-if="hasEntries(cacheMetrics)">
            <div class="kv-item" v-for="[k, v] in kvEntries(cacheMetrics)" :key="k">
              <span class="kv-label">{{ k }}</span>
              <span class="kv-value">{{ formatValue(v) }}</span>
            </div>
          </div>
          <div v-else class="section-empty">暂无缓存指标</div>
        </template>

        <div class="section-subtitle" style="margin-top: 16px;">磁盘使用</div>
        <div v-if="getSectionError('disk_usage')" class="section-error">{{ getSectionError('disk_usage') }}</div>
        <div class="kv-grid" v-else-if="hasEntries(diskUsage)">
          <div class="kv-item" v-for="[k, v] in kvEntries(diskUsage)" :key="k">
            <span class="kv-label">{{ k }}</span>
            <span class="kv-value">{{ formatValue(v) }}</span>
          </div>
        </div>
        <div v-else class="section-empty">暂无磁盘使用数据</div>
      </div>

      <!-- 6. 写入队列 -->
      <div class="section-card">
        <div class="section-title">写入队列</div>
        <div class="section-desc">异步写入队列状态与错误信息。</div>
        <div v-if="getSectionError('write_queue')" class="section-error">{{ getSectionError('write_queue') }}</div>
        <div v-else-if="writeQueue" class="kv-grid">
          <div class="kv-item">
            <span class="kv-label">总入队</span>
            <span class="kv-value">{{ writeQueue.total_enqueued ?? '-' }}</span>
          </div>
          <div class="kv-item">
            <span class="kv-label">总完成</span>
            <span class="kv-value">{{ writeQueue.total_completed ?? '-' }}</span>
          </div>
          <div class="kv-item">
            <span class="kv-label">总失败</span>
            <span class="kv-value">{{ writeQueue.total_failed ?? '-' }}</span>
          </div>
          <div class="kv-item">
            <span class="kv-label">总重试</span>
            <span class="kv-value">{{ writeQueue.total_retries ?? '-' }}</span>
          </div>
          <div class="kv-item">
            <span class="kv-label">当前队列深度</span>
            <span class="kv-value">{{ writeQueue.current_depth ?? '-' }}</span>
          </div>
          <div class="kv-item kv-item-wide">
            <span class="kv-label">最近错误</span>
            <span class="kv-value">{{ writeQueue.last_error || '无' }}</span>
          </div>
        </div>
        <div v-else class="section-empty">暂无队列数据</div>
      </div>

      <!-- 7. 缓存维护 -->
      <div class="section-card">
        <div class="section-title">缓存维护</div>
        <div class="section-desc">执行缓存清理与 VACUUM 操作。</div>
        <div class="action-group">
          <button class="btn btn-primary"
            @click="runMaintenance"
            :disabled="pendingActions.maintenance">
            {{ pendingActions.maintenance ? '执行中...' : '执行维护' }}
          </button>
        </div>
        <div v-if="maintenanceResult" class="maintenance-result">
          <div class="section-subtitle">维护结果</div>
          <div class="kv-grid">
            <div class="kv-item" v-for="[k, v] in kvEntries(maintenanceResult)" :key="k">
              <span class="kv-label">{{ k }}</span>
              <span class="kv-value">{{ formatValue(v) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 8. 账号管理 -->
      <div class="section-card">
        <div class="section-title">账号管理</div>
        <div class="section-desc">客户端账号、订阅与令牌管理。</div>

        <div class="action-group">
          <button class="btn btn-primary btn-sm" @click="showCreateAccountDialog">+ 创建账号</button>
          <button class="btn btn-browse btn-sm" @click="loadAccounts" :disabled="pendingActions.accountsLoad">
            {{ pendingActions.accountsLoad ? '刷新中...' : '刷新' }}
          </button>
        </div>

        <div v-if="accountsError" class="section-error">{{ accountsError }}</div>

        <div v-if="accounts.length" class="table-wrap" style="margin-top: 12px;">
          <table class="admin-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>邮箱</th>
                <th>显示名</th>
                <th>角色</th>
                <th>状态</th>
                <th>订阅</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="acc in accounts" :key="acc.id">
                <td>{{ acc.id }}</td>
                <td>{{ acc.email }}</td>
                <td>{{ acc.display_name || '-' }}</td>
                <td><span :class="['status-badge', acc.role === 'admin' ? 'badge-success' : 'badge-muted']">{{ acc.role }}</span></td>
                <td><span :class="['status-badge', acc.status === 'active' ? 'badge-success' : 'badge-error']">{{ acc.status }}</span></td>
                <td><span :class="['status-badge', tierBadgeClass(acc.tier)]">{{ tierBadgeLabel(acc.tier) }}</span></td>
                <td class="actions-cell">
                  <button class="btn btn-browse btn-sm" @click="openAccountDetail(acc.id)" title="详情">详情</button>
                  <button class="btn btn-browse btn-sm" @click="showGrantDialog(acc.id)" title="授予订阅">订阅</button>
                  <button class="btn btn-danger-icon btn-sm" @click="deleteAccount(acc)" title="删除">✕</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="section-empty">暂无账号（点击「创建账号」或「刷新」）</div>
      </div>
    </template>

    <!-- 创建账号对话框 -->
    <div class="dialog-overlay" v-if="createDialog.show">
      <div class="dialog-box dialog-box-wide">
        <h3>创建账号</h3>
        <div class="dialog-form">
          <div class="dialog-field">
            <label>邮箱 *</label>
            <input type="email" v-model="createDialog.email" class="field-input" placeholder="user@example.com" />
          </div>
          <div class="dialog-field">
            <label>密码 *</label>
            <input type="password" v-model="createDialog.password" class="field-input" placeholder="设置密码" />
          </div>
          <div class="dialog-field">
            <label>显示名</label>
            <input type="text" v-model="createDialog.displayName" class="field-input" placeholder="可选" />
          </div>
          <div class="dialog-field">
            <label>角色</label>
            <select v-model="createDialog.role" class="field-input">
              <option value="user">user</option>
              <option value="admin">admin</option>
            </select>
          </div>
        </div>
        <div class="dialog-actions">
          <button class="btn btn-browse" @click="createDialog.show = false">取消</button>
          <button class="btn btn-primary" @click="createAccount" :disabled="!createDialog.email || !createDialog.password">
            创建
          </button>
        </div>
      </div>
    </div>

    <!-- 授予订阅对话框 -->
    <div class="dialog-overlay" v-if="grantDialog.show">
      <div class="dialog-box">
        <h3>授予订阅</h3>
        <div class="dialog-form">
          <div class="dialog-field">
            <label>等级</label>
            <select v-model="grantDialog.tier" class="field-input">
              <option value="free">免费版 (free)</option>
              <option value="pro">专业版 (pro)</option>
              <option value="enterprise">企业版 (enterprise)</option>
            </select>
          </div>
          <div class="dialog-field">
            <label>有效期（天，留空=永久）</label>
            <input type="number" v-model.number="grantDialog.durationDays" class="field-input" placeholder="30" min="1" />
          </div>
        </div>
        <div class="dialog-actions">
          <button class="btn btn-browse" @click="grantDialog.show = false">取消</button>
          <button class="btn btn-primary" @click="grantSubscription">授予</button>
        </div>
      </div>
    </div>

    <!-- 账号详情抽屉 -->
    <div class="dialog-overlay" v-if="detailDialog.show">
      <div class="dialog-box dialog-box-wide">
        <h3>账号详情 #{{ detailDialog.accountId }}</h3>
        <div v-if="detailDialog.loading" class="section-empty">加载中...</div>
        <div v-else-if="detailDialog.data">
          <div class="section-subtitle">基本信息</div>
          <div class="kv-grid">
            <div class="kv-item"><span class="kv-label">邮箱</span><span class="kv-value">{{ detailDialog.data.account?.email }}</span></div>
            <div class="kv-item"><span class="kv-label">显示名</span><span class="kv-value">{{ detailDialog.data.account?.display_name || '-' }}</span></div>
            <div class="kv-item"><span class="kv-label">角色</span><span class="kv-value">{{ detailDialog.data.account?.role }}</span></div>
            <div class="kv-item"><span class="kv-label">状态</span><span class="kv-value">{{ detailDialog.data.account?.status }}</span></div>
          </div>

          <div class="section-subtitle" style="margin-top: 16px;">订阅权限</div>
          <div class="kv-grid" v-if="detailDialog.data.entitlements">
            <div class="kv-item"><span class="kv-label">等级</span><span class="kv-value">{{ detailDialog.data.entitlements.label }}</span></div>
            <div class="kv-item"><span class="kv-label">市场</span><span class="kv-value">{{ (detailDialog.data.entitlements.markets || []).join(', ') }}</span></div>
            <div class="kv-item"><span class="kv-label">周期</span><span class="kv-value">{{ (detailDialog.data.entitlements.intervals || []).join(', ') }}</span></div>
            <div class="kv-item"><span class="kv-label">历史天数</span><span class="kv-value">{{ detailDialog.data.entitlements.history_days === -1 ? '无限' : detailDialog.data.entitlements.history_days }}</span></div>
            <div class="kv-item"><span class="kv-label">日配额</span><span class="kv-value">{{ detailDialog.data.entitlements.daily_quota === -1 ? '无限' : detailDialog.data.entitlements.daily_quota }}</span></div>
          </div>

          <div class="section-subtitle" style="margin-top: 16px;">用量（近30天）</div>
          <div class="kv-grid" v-if="detailDialog.data.usage">
            <div class="kv-item"><span class="kv-label">总请求</span><span class="kv-value">{{ detailDialog.data.usage.total_requests ?? 0 }}</span></div>
            <div class="kv-item"><span class="kv-label">今日请求</span><span class="kv-value">{{ detailDialog.data.usage.today_requests ?? 0 }}</span></div>
            <div class="kv-item"><span class="kv-label">Token 消耗</span><span class="kv-value">{{ detailDialog.data.usage.total_tokens ?? 0 }}</span></div>
          </div>

          <div class="section-subtitle" style="margin-top: 16px;">
            令牌列表
            <button class="btn btn-danger-icon btn-sm" @click="revokeAllTokens(detailDialog.accountId)" style="margin-left: 12px;">吊销全部</button>
          </div>
          <div v-if="detailDialog.tokens && detailDialog.tokens.length" class="table-wrap">
            <table class="admin-table">
              <thead>
                <tr><th>前缀</th><th>设备</th><th>创建时间</th><th>过期时间</th><th>最后使用</th><th>状态</th><th>操作</th></tr>
              </thead>
              <tbody>
                <tr v-for="t in detailDialog.tokens" :key="t.id">
                  <td>{{ t.token_prefix }}...</td>
                  <td>{{ t.device_info || '-' }}</td>
                  <td>{{ formatDateTime(t.created_at) }}</td>
                  <td>{{ formatDateTime(t.expires_at) }}</td>
                  <td>{{ formatDateTime(t.last_used_at) }}</td>
                  <td><span :class="['status-badge', t.revoked_at ? 'badge-error' : 'badge-success']">{{ t.revoked_at ? '已吊销' : '有效' }}</span></td>
                  <td><button v-if="!t.revoked_at" class="btn btn-danger-icon btn-sm" @click="revokeToken(t.id)">吊销</button></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="section-empty">暂无令牌</div>
        </div>
        <div class="dialog-actions">
          <button class="btn btn-browse" @click="detailDialog.show = false">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
/**
 * AdminPanel - DSA 后端管理面板
 *
 * 实时展示后端服务状态（进程、WS 中继、调度任务、采集器、缓存、写入队列），
 * 支持手动触发调度任务、采集/归档行情、执行缓存维护。
 * 自动每 5 秒轮询状态，挂载时启动、卸载时停止。
 */
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { getApiBase } from '../service/serverConfig'

// ==================== 常量 ====================

const COLLECT_MARKETS = [
  { key: 'cn_stock', label: 'A股' },
  { key: 'cn_etf', label: 'ETF' },
  { key: 'hk_stock', label: '港股' },
  { key: 'crypto', label: '加密' },
  { key: 'all', label: '全部' },
]

const ARCHIVE_MARKETS = [
  { key: 'cn_stock', label: 'A股' },
  { key: 'hk_stock', label: '港股' },
  { key: 'crypto', label: '加密' },
]

// ==================== 响应式状态 ====================

const status = ref(null)
const clients = ref(null)
const statusError = ref('')
const clientsError = ref('')
const toast = ref(null)
const maintenanceResult = ref(null)

const confirmDialog = reactive({
  show: false,
  title: '',
  message: '',
  confirmText: '确定',
  cancelText: '取消',
  resolve: null,
})

const pendingActions = reactive({})

// ==================== 计算属性 ====================

const processInfo = computed(() => status.value?.process || null)
const wsRelay = computed(() => status.value?.ws_relay || null)
const schedulerData = computed(() => status.value?.scheduler || null)

const schedulerTasks = computed(() => {
  const s = schedulerData.value
  if (!s || !Array.isArray(s.tasks)) return []
  return s.tasks
})

const schedulerNote = computed(() => {
  const s = schedulerData.value
  if (s && !Array.isArray(s) && s.note) return s.note
  return null
})

const collectorData = computed(() => status.value?.collector || null)
const cacheMetrics = computed(() => status.value?.cache_metrics || null)
const diskUsage = computed(() => status.value?.disk_usage || null)
const writeQueue = computed(() => status.value?.write_queue || null)
const wsClients = computed(() => clients.value?.ws_clients || [])
const wsClientCount = computed(() => {
  if (clients.value == null) return null
  return clients.value.ws_client_count ?? 0
})

// ==================== 工具函数 ====================

/**
 * 将秒数格式化为 "Xd Xh Xm Xs" 形式。
 */
function formatUptime(seconds) {
  if (seconds == null || isNaN(seconds)) return '-'
  const s = Number(seconds)
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.floor(s % 60)
  return `${d}d ${h}h ${m}m ${sec}s`
}

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
 * 通用值格式化，用于 kv 渲染未知结构的数据。
 */
function formatValue(v) {
  if (v === null || v === undefined) return '-'
  if (typeof v === 'boolean') return v ? '是' : '否'
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(2)
  if (Array.isArray(v)) return v.join(', ') || '-'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/**
 * 获取某个 section 的错误信息（如果该字段为 {error: "..."} 结构）。
 */
function getSectionError(section) {
  const v = status.value?.[section]
  if (v && typeof v === 'object' && !Array.isArray(v) && 'error' in v) {
    return v.error
  }
  return null
}

/**
 * 判断对象是否有可渲染的 kv 条目（排除 error 字段后）。
 */
function hasEntries(obj) {
  return obj && typeof obj === 'object' && !Array.isArray(obj) && kvEntries(obj).length > 0
}

/**
 * 获取对象的 kv 条目（排除 error 字段）。
 */
function kvEntries(obj) {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return []
  return Object.entries(obj).filter(([k]) => k !== 'error')
}

/**
 * 调度任务上次运行状态的 badge class。
 */
function taskStatusClass(s) {
  if (s === 'success') return 'badge-success'
  if (s === 'failed') return 'badge-error'
  return 'badge-muted'
}

/**
 * WebSocket 客户端连接状态的 badge class。
 */
function stateClass(state) {
  const s = (state || '').toLowerCase()
  if (s.includes('connected') || s === 'ok' || s === 'open') return 'badge-success'
  if (s.includes('disconnect') || s.includes('closed') || s.includes('error')) return 'badge-error'
  return 'badge-muted'
}

/**
 * 显示 toast 消息，3 秒后自动清除。
 */
function showToast(type, message) {
  toast.value = { type, message }
  setTimeout(() => { toast.value = null }, 3000)
}

/**
 * 显示确认对话框，返回 Promise<boolean>。
 */
function showConfirm(title, message, confirmText = '确定', cancelText = '取消') {
  return new Promise((resolve) => {
    confirmDialog.title = title
    confirmDialog.message = message
    confirmDialog.confirmText = confirmText
    confirmDialog.cancelText = cancelText
    confirmDialog.resolve = resolve
    confirmDialog.show = true
  })
}

function confirmConfirm() {
  confirmDialog.show = false
  if (confirmDialog.resolve) {
    confirmDialog.resolve(true)
    confirmDialog.resolve = null
  }
}

function cancelConfirm() {
  confirmDialog.show = false
  if (confirmDialog.resolve) {
    confirmDialog.resolve(false)
    confirmDialog.resolve = null
  }
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
  if (resp.status === 401) {
    throw new Error('未登录或会话已过期')
  }
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}))
    throw new Error(err.detail || err.error || `HTTP ${resp.status}`)
  }
  return resp.json()
}

/**
 * 获取服务状态。首次失败设置 statusError，后续失败静默保留旧数据。
 */
async function fetchStatus() {
  try {
    status.value = await adminFetch('/api/v1/admin/status')
    statusError.value = ''
  } catch (e) {
    if (!status.value) {
      statusError.value = e.message || '未知错误'
    }
  }
}

/**
 * 获取客户端列表。首次失败设置 clientsError，后续失败静默保留旧数据。
 */
async function fetchClients() {
  try {
    clients.value = await adminFetch('/api/v1/admin/clients')
    clientsError.value = ''
  } catch (e) {
    if (!clients.value) {
      clientsError.value = e.message || '未知错误'
    }
  }
}

/**
 * 刷新全部状态。
 */
async function refreshAll() {
  await Promise.all([fetchStatus(), fetchClients()])
}

/**
 * 手动触发调度任务。
 */
async function triggerTask(name) {
  const key = 'trigger_' + name
  pendingActions[key] = true
  try {
    await adminFetch(`/api/v1/admin/scheduler/trigger/${encodeURIComponent(name)}`, { method: 'POST' })
    showToast('success', `任务 ${name} 已触发`)
  } catch (e) {
    showToast('error', `触发失败: ${e.message}`)
  } finally {
    pendingActions[key] = false
    refreshAll()
  }
}

/**
 * 手动采集某个市场的快照。
 */
async function collectMarket(market) {
  const key = 'collect_' + market
  pendingActions[key] = true
  try {
    await adminFetch(`/api/v1/admin/collector/collect/${encodeURIComponent(market)}`, { method: 'POST' })
    showToast('success', `${market} 采集完成`)
  } catch (e) {
    showToast('error', `采集失败: ${e.message}`)
  } finally {
    pendingActions[key] = false
    refreshAll()
  }
}

/**
 * 将最新快照归档为日线 K 线。
 */
async function archiveMarket(market) {
  const key = 'archive_' + market
  pendingActions[key] = true
  try {
    const data = await adminFetch(`/api/v1/admin/collector/archive/${encodeURIComponent(market)}`, { method: 'POST' })
    showToast('success', `${market} 归档完成 (${data.archived ?? 0} 条)`)
  } catch (e) {
    showToast('error', `归档失败: ${e.message}`)
  } finally {
    pendingActions[key] = false
    refreshAll()
  }
}

/**
 * 执行缓存维护（需确认）。
 */
async function runMaintenance() {
  const ok = await showConfirm(
    '执行缓存维护',
    '确认执行缓存维护？这将清理过期数据并执行 VACUUM。',
    '确认执行',
    '取消'
  )
  if (!ok) return
  pendingActions.maintenance = true
  maintenanceResult.value = null
  try {
    const data = await adminFetch('/api/v1/admin/maintenance/run', { method: 'POST' })
    maintenanceResult.value = data
    showToast('success', '缓存维护已完成')
  } catch (e) {
    showToast('error', `维护失败: ${e.message}`)
  } finally {
    pendingActions.maintenance = false
    refreshAll()
  }
}

// ==================== 账号管理 ====================

const TIER_LABELS = { free: '免费版', pro: '专业版', enterprise: '企业版' }
function tierBadgeLabel(tier) {
  return TIER_LABELS[tier] || tier || '-'
}
function tierBadgeClass(tier) {
  if (tier === 'enterprise') return 'badge-tier-enterprise'
  if (tier === 'pro') return 'badge-tier-pro'
  return 'badge-muted'
}

const accounts = ref([])
const accountsError = ref('')

const createDialog = reactive({
  show: false,
  email: '',
  password: '',
  displayName: '',
  role: 'user',
})

const grantDialog = reactive({
  show: false,
  accountId: null,
  tier: 'pro',
  durationDays: null,
})

const detailDialog = reactive({
  show: false,
  accountId: null,
  loading: false,
  data: null,
  tokens: [],
})

async function loadAccounts() {
  pendingActions.accountsLoad = true
  try {
    const data = await adminFetch('/api/v1/admin/accounts?limit=500')
    accounts.value = data.accounts || []
    accountsError.value = ''
  } catch (e) {
    accountsError.value = e.message || '未知错误'
  } finally {
    pendingActions.accountsLoad = false
  }
}

function showCreateAccountDialog() {
  createDialog.email = ''
  createDialog.password = ''
  createDialog.displayName = ''
  createDialog.role = 'user'
  createDialog.show = true
}

async function createAccount() {
  try {
    const body = {
      email: createDialog.email,
      password: createDialog.password,
      role: createDialog.role,
    }
    if (createDialog.displayName) body.displayName = createDialog.displayName
    await adminFetch('/api/v1/admin/accounts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    createDialog.show = false
    showToast('success', '账号已创建')
    await loadAccounts()
  } catch (e) {
    showToast('error', `创建失败: ${e.message}`)
  }
}

function showGrantDialog(accountId) {
  grantDialog.accountId = accountId
  grantDialog.tier = 'pro'
  grantDialog.durationDays = null
  grantDialog.show = true
}

async function grantSubscription() {
  try {
    const body = { tier: grantDialog.tier }
    if (grantDialog.durationDays) body.durationDays = grantDialog.durationDays
    await adminFetch(`/api/v1/admin/accounts/${grantDialog.accountId}/subscriptions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    grantDialog.show = false
    showToast('success', '订阅已授予')
    await loadAccounts()
  } catch (e) {
    showToast('error', `授予失败: ${e.message}`)
  }
}

async function deleteAccount(acc) {
  const ok = await showConfirm(
    '删除账号',
    `确认删除账号 ${acc.email} (ID: ${acc.id})？此操作不可撤销。`,
    '删除',
    '取消'
  )
  if (!ok) return
  try {
    await adminFetch(`/api/v1/admin/accounts/${acc.id}`, { method: 'DELETE' })
    showToast('success', '账号已删除')
    await loadAccounts()
  } catch (e) {
    showToast('error', `删除失败: ${e.message}`)
  }
}

async function openAccountDetail(accountId) {
  detailDialog.accountId = accountId
  detailDialog.show = true
  detailDialog.loading = true
  detailDialog.data = null
  detailDialog.tokens = []
  try {
    const [entitlements, usage, tokensData] = await Promise.all([
      adminFetch(`/api/v1/admin/accounts/${accountId}/entitlements`).catch(() => null),
      adminFetch(`/api/v1/admin/accounts/${accountId}/usage`).catch(() => null),
      adminFetch(`/api/v1/admin/accounts/${accountId}/tokens`).catch(() => null),
    ])
    const account = accounts.value.find(a => a.id === accountId) || {}
    detailDialog.data = { account, entitlements, usage }
    detailDialog.tokens = tokensData?.tokens || []
  } catch (e) {
    showToast('error', `加载失败: ${e.message}`)
  } finally {
    detailDialog.loading = false
  }
}

async function revokeToken(tokenId) {
  try {
    await adminFetch(`/api/v1/admin/tokens/${tokenId}`, { method: 'DELETE' })
    showToast('success', '令牌已吊销')
    await openAccountDetail(detailDialog.accountId)
  } catch (e) {
    showToast('error', `吊销失败: ${e.message}`)
  }
}

async function revokeAllTokens(accountId) {
  const ok = await showConfirm(
    '吊销全部令牌',
    '确认吊销该账号的所有有效令牌？使用中的客户端将立即断开。',
    '确认吊销',
    '取消'
  )
  if (!ok) return
  try {
    const data = await adminFetch(`/api/v1/admin/accounts/${accountId}/tokens/revoke-all`, { method: 'POST' })
    showToast('success', `已吊销 ${data.revoked ?? 0} 个令牌`)
    await openAccountDetail(accountId)
  } catch (e) {
    showToast('error', `吊销失败: ${e.message}`)
  }
}

// ==================== 生命周期 ====================

let pollTimer = null

onMounted(() => {
  refreshAll()
  loadAccounts()
  pollTimer = setInterval(refreshAll, 5000)
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
.admin-panel {
  position: relative;
}

/* ==================== 复用 Settings.vue 样式 ==================== */
/* 由于 Settings.vue 使用 <style scoped>，这里需重新定义共用类 */

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
.kv-item-wide {
  grid-column: 1 / -1;
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
.symbol-cell {
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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

/* ==================== 操作按钮组 ==================== */
.action-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
  align-items: center;
}
.action-label {
  font-size: 12px;
  color: #888;
  margin-right: 4px;
  min-width: 32px;
}
.action-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

/* ==================== 维护结果 ==================== */
.maintenance-result {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #333;
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
.admin-toast.info {
  background: rgba(74, 158, 255, 0.2);
  color: #4a9eff;
  border: 1px solid rgba(74, 158, 255, 0.4);
}

/* ==================== 加载 / 错误状态 ==================== */
.loading-state,
.error-state {
  text-align: center;
  padding: 60px 20px;
  color: #888;
}
.error-title {
  font-size: 16px;
  font-weight: 500;
  color: #ccc;
  margin-bottom: 8px;
}
.error-desc {
  font-size: 13px;
  color: #666;
  margin-bottom: 16px;
}
.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #333;
  border-top-color: #4a9eff;
  border-radius: 50%;
  margin: 0 auto 12px;
  animation: admin-spin 0.8s linear infinite;
}
@keyframes admin-spin {
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
.dialog-box p {
  margin: 0 0 20px;
  font-size: 14px;
  color: #ccc;
  line-height: 1.5;
}
.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

/* 账号管理 */
.actions-cell {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.badge-tier-pro {
  color: #4a9eff;
  background: rgba(74, 158, 255, 0.15);
}
.badge-tier-enterprise {
  color: #d29922;
  background: rgba(210, 153, 34, 0.15);
}

/* 对话框表单 */
.dialog-box-wide {
  max-width: 600px;
}
.dialog-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-bottom: 20px;
}
.dialog-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.dialog-field label {
  font-size: 12px;
  color: #999;
}
.dialog-field .field-input,
.dialog-field input,
.dialog-field select {
  width: 100%;
  padding: 7px 12px;
  background: #1a1a1a;
  border: 1px solid #444;
  border-radius: 6px;
  color: #fff;
  font-size: 13px;
  outline: none;
}
.dialog-field .field-input:focus,
.dialog-field input:focus,
.dialog-field select:focus {
  border-color: #4a9eff;
}
</style>
