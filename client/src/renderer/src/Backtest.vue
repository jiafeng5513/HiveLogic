<template>
  <div class="backtest-app view-container">
    <!-- 左侧导航面板 -->
    <aside class="side-panel" ref="sidePanel">
      <div class="side-panel-resize-handle"></div>
      <div class="side-panel-header">回测分析</div>
      <div class="side-panel-content">
        <ul class="nav-list">
          <li
            v-for="tab in tabs"
            :key="tab.key"
            class="nav-item"
            :class="{ active: activeTab === tab.key }"
            @click="activeTab = tab.key"
          >{{ tab.label }}</li>
        </ul>
      </div>
      <div class="side-panel-footer">
        <div class="service-status" :class="serviceStatus" :title="serviceStatusTip">
          <span class="status-dot"></span>
          <span>{{ serviceStatusLabel }}</span>
        </div>
      </div>
    </aside>

    <!-- 主内容 -->
    <div class="main-view">
      <div class="main-view-content">

      <!-- 运行回测 -->
      <div v-if="activeTab === 'run'" class="tab-content">
        <div class="section">
          <div class="section-header">
            <h2>运行回测</h2>
          </div>
          <div class="run-form">
            <div class="form-grid">
              <div class="form-row">
                <label>股票代码（可选）</label>
                <input v-model="runForm.code" class="form-input" placeholder="如 600519，留空为全部" />
              </div>
              <div class="form-row">
                <label>评估窗口（交易日）</label>
                <input v-model.number="runForm.eval_window_days" type="number" class="form-input" min="1" max="120" />
              </div>
              <div class="form-row">
                <label>最小分析龄期（天）</label>
                <input v-model.number="runForm.min_age_days" type="number" class="form-input" min="0" max="365" />
              </div>
              <div class="form-row">
                <label>最大记录数</label>
                <input v-model.number="runForm.limit" type="number" class="form-input" min="1" max="2000" />
              </div>
              <div class="form-row checkbox-row">
                <label>
                  <input type="checkbox" v-model="runForm.force" />
                  强制重新计算
                </label>
              </div>
            </div>
            <div class="run-actions">
              <button class="btn-primary" @click="runBacktest" :disabled="running">
                {{ running ? '回测中...' : '开始回测' }}
              </button>
            </div>
            <div v-if="running" class="running-indicator">
              <div class="spinner"></div>
              <span>正在执行回测，请稍候...</span>
            </div>
            <div v-if="runResult" class="run-result" :class="{ success: runResult.errors === 0 }">
              <h3>回测完成</h3>
              <div class="result-grid">
                <div class="result-item">
                  <span class="result-label">处理记录</span>
                  <span class="result-value">{{ runResult.processed }}</span>
                </div>
                <div class="result-item">
                  <span class="result-label">保存结果</span>
                  <span class="result-value">{{ runResult.saved }}</span>
                </div>
                <div class="result-item">
                  <span class="result-label">完成评估</span>
                  <span class="result-value">{{ runResult.completed }}</span>
                </div>
                <div class="result-item">
                  <span class="result-label">数据不足</span>
                  <span class="result-value warning">{{ runResult.insufficient }}</span>
                </div>
                <div class="result-item">
                  <span class="result-label">错误</span>
                  <span class="result-value" :class="{ negative: runResult.errors > 0 }">{{ runResult.errors }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 回测结果 -->
      <div v-if="activeTab === 'results'" class="tab-content">
        <div class="section">
          <div class="section-header">
            <h2>回测结果</h2>
            <div class="section-actions">
              <button class="btn-icon" @click="loadResults" title="刷新">🔄</button>
            </div>
          </div>
          <div class="filter-bar">
            <input v-model="resultFilter.code" placeholder="股票代码" class="filter-input" @keydown.enter="resetAndLoadResults" />
            <input v-model.number="resultFilter.eval_window_days" type="number" placeholder="窗口天数" class="filter-input filter-sm" min="1" max="120" />
            <input v-model="resultFilter.analysis_date_from" type="date" class="filter-input" />
            <input v-model="resultFilter.analysis_date_to" type="date" class="filter-input" />
            <button class="btn-secondary" @click="resetAndLoadResults">查询</button>
          </div>
          <div class="table-wrap">
            <table v-if="results.length > 0">
              <thead>
                <tr>
                  <th>分析日期</th>
                  <th>代码</th>
                  <th>名称</th>
                  <th>方向预期</th>
                  <th>仓位建议</th>
                  <th>结果</th>
                  <th>股票收益%</th>
                  <th>模拟收益%</th>
                  <th>止损触发</th>
                  <th>止盈触发</th>
                  <th>首次触发</th>
                  <th>触发天数</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in results" :key="r.id || r.analysis_history_id" @click="selectResult(r)" :class="{ selected: selectedResult === r }">
                  <td>{{ r.analysis_date }}</td>
                  <td class="mono">{{ r.code }}</td>
                  <td>{{ r.stock_name || '-' }}</td>
                  <td><span class="direction-badge" :class="r.direction_expected">{{ directionLabel(r.direction_expected) }}</span></td>
                  <td><span class="position-badge" :class="r.position_recommendation">{{ r.position_recommendation === 'long' ? '做多' : '观望' }}</span></td>
                  <td><span class="outcome-badge" :class="r.outcome">{{ outcomeLabel(r.outcome) }}</span></td>
                  <td class="num" :class="pnlClass(r.stock_return_pct)">{{ fmtPct(r.stock_return_pct) }}</td>
                  <td class="num" :class="pnlClass(r.simulated_return_pct)">{{ fmtPct(r.simulated_return_pct) }}</td>
                  <td>{{ r.hit_stop_loss ? '✓' : '-' }}</td>
                  <td>{{ r.hit_take_profit ? '✓' : '-' }}</td>
                  <td>{{ firstHitLabel(r.first_hit) }}</td>
                  <td class="num">{{ r.first_hit_trading_days != null ? r.first_hit_trading_days : '-' }}</td>
                </tr>
              </tbody>
            </table>
            <div v-else class="empty-state">{{ loading ? '加载中...' : '暂无回测结果' }}</div>
          </div>
          <div v-if="resultPagination.total > resultPagination.limit" class="pagination">
            <button :disabled="resultPagination.page <= 1" @click="resultPagination.page--; loadResults()">上一页</button>
            <span>{{ resultPagination.page }} / {{ Math.ceil(resultPagination.total / resultPagination.limit) }}</span>
            <button :disabled="resultPagination.page * resultPagination.limit >= resultPagination.total" @click="resultPagination.page++; loadResults()">下一页</button>
          </div>
        </div>

        <!-- 结果详情 -->
        <div v-if="selectedResult" class="section detail-section">
          <div class="section-header">
            <h2>详情 — {{ selectedResult.code }} {{ selectedResult.stock_name }} ({{ selectedResult.analysis_date }})</h2>
            <button class="btn-icon" @click="selectedResult = null">✕</button>
          </div>
          <div class="detail-grid">
            <div class="detail-card">
              <h3>基本信息</h3>
              <div class="detail-item"><span>评估状态</span><span>{{ selectedResult.eval_status }}</span></div>
              <div class="detail-item"><span>评估窗口</span><span>{{ selectedResult.eval_window_days }} 交易日</span></div>
              <div class="detail-item"><span>方向预期</span><span>{{ directionLabel(selectedResult.direction_expected) }}</span></div>
              <div class="detail-item"><span>仓位建议</span><span>{{ selectedResult.position_recommendation === 'long' ? '做多' : '观望' }}</span></div>
            </div>
            <div class="detail-card">
              <h3>价格与收益</h3>
              <div class="detail-item"><span>入场价</span><span class="mono">{{ fmtPrice(selectedResult.entry_price) }}</span></div>
              <div class="detail-item"><span>出场价</span><span class="mono">{{ fmtPrice(selectedResult.exit_price) }}</span></div>
              <div class="detail-item"><span>股票收益</span><span :class="pnlClass(selectedResult.stock_return_pct)">{{ fmtPct(selectedResult.stock_return_pct) }}</span></div>
              <div class="detail-item"><span>模拟收益</span><span :class="pnlClass(selectedResult.simulated_return_pct)">{{ fmtPct(selectedResult.simulated_return_pct) }}</span></div>
            </div>
            <div class="detail-card">
              <h3>风控触发</h3>
              <div class="detail-item"><span>止损价</span><span class="mono">{{ fmtPrice(selectedResult.stop_loss) }}</span></div>
              <div class="detail-item"><span>止盈价</span><span class="mono">{{ fmtPrice(selectedResult.take_profit) }}</span></div>
              <div class="detail-item"><span>触发止损</span><span>{{ selectedResult.hit_stop_loss ? '是' : '否' }}</span></div>
              <div class="detail-item"><span>触发止盈</span><span>{{ selectedResult.hit_take_profit ? '是' : '否' }}</span></div>
              <div class="detail-item"><span>首次触发</span><span>{{ firstHitLabel(selectedResult.first_hit) }}</span></div>
              <div class="detail-item"><span>触发天数</span><span>{{ selectedResult.first_hit_trading_days != null ? selectedResult.first_hit_trading_days : '-' }}</span></div>
            </div>
            <div class="detail-card">
              <h3>评估结果</h3>
              <div class="detail-item"><span>结果判定</span><span class="outcome-badge" :class="selectedResult.outcome">{{ outcomeLabel(selectedResult.outcome) }}</span></div>
            </div>
          </div>
        </div>
      </div>

      <!-- 整体绩效 -->
      <div v-if="activeTab === 'performance'" class="tab-content">
        <div class="section">
          <div class="section-header">
            <h2>整体绩效</h2>
            <div class="section-actions">
              <button class="btn-icon" @click="loadPerformance" title="刷新">🔄</button>
            </div>
          </div>
          <div v-if="performance" class="perf-content">
            <div class="summary-cards">
              <div class="card">
                <div class="card-label">总评估数</div>
                <div class="card-value">{{ performance.total_evaluations }}</div>
              </div>
              <div class="card">
                <div class="card-label">已完成</div>
                <div class="card-value">{{ performance.completed_count }}</div>
              </div>
              <div class="card">
                <div class="card-label">方向准确率</div>
                <div class="card-value" :class="accuracyClass(performance.direction_accuracy_pct)">{{ fmtPct(performance.direction_accuracy_pct) }}</div>
              </div>
              <div class="card">
                <div class="card-label">胜率</div>
                <div class="card-value" :class="accuracyClass(performance.win_rate_pct)">{{ fmtPct(performance.win_rate_pct) }}</div>
              </div>
              <div class="card">
                <div class="card-label">平均股票收益</div>
                <div class="card-value" :class="pnlClass(performance.avg_stock_return_pct)">{{ fmtPct(performance.avg_stock_return_pct) }}</div>
              </div>
              <div class="card">
                <div class="card-label">平均模拟收益</div>
                <div class="card-value" :class="pnlClass(performance.avg_simulated_return_pct)">{{ fmtPct(performance.avg_simulated_return_pct) }}</div>
              </div>
            </div>

            <div class="perf-grid">
              <div class="perf-card">
                <h3>多空分布</h3>
                <div class="bar-chart">
                  <div class="bar-row">
                    <span class="bar-label">做多</span>
                    <div class="bar-track">
                      <div class="bar-fill positive-bg" :style="{ width: barPct(performance.long_count, performance.completed_count) }"></div>
                    </div>
                    <span class="bar-val">{{ performance.long_count }}</span>
                  </div>
                  <div class="bar-row">
                    <span class="bar-label">观望</span>
                    <div class="bar-track">
                      <div class="bar-fill neutral-bg" :style="{ width: barPct(performance.cash_count, performance.completed_count) }"></div>
                    </div>
                    <span class="bar-val">{{ performance.cash_count }}</span>
                  </div>
                </div>
              </div>

              <div class="perf-card">
                <h3>胜负分布</h3>
                <div class="bar-chart">
                  <div class="bar-row">
                    <span class="bar-label">胜</span>
                    <div class="bar-track">
                      <div class="bar-fill positive-bg" :style="{ width: barPct(performance.win_count, performance.completed_count) }"></div>
                    </div>
                    <span class="bar-val">{{ performance.win_count }}</span>
                  </div>
                  <div class="bar-row">
                    <span class="bar-label">负</span>
                    <div class="bar-track">
                      <div class="bar-fill negative-bg" :style="{ width: barPct(performance.loss_count, performance.completed_count) }"></div>
                    </div>
                    <span class="bar-val">{{ performance.loss_count }}</span>
                  </div>
                  <div class="bar-row">
                    <span class="bar-label">中性</span>
                    <div class="bar-track">
                      <div class="bar-fill neutral-bg" :style="{ width: barPct(performance.neutral_count, performance.completed_count) }"></div>
                    </div>
                    <span class="bar-val">{{ performance.neutral_count }}</span>
                  </div>
                </div>
              </div>

              <div class="perf-card">
                <h3>风控指标</h3>
                <div class="detail-item"><span>止损触发率</span><span>{{ fmtPct(performance.stop_loss_trigger_rate) }}</span></div>
                <div class="detail-item"><span>止盈触发率</span><span>{{ fmtPct(performance.take_profit_trigger_rate) }}</span></div>
                <div class="detail-item"><span>模糊率</span><span>{{ fmtPct(performance.ambiguous_rate) }}</span></div>
                <div class="detail-item"><span>平均触发天数</span><span>{{ performance.avg_days_to_first_hit != null ? performance.avg_days_to_first_hit.toFixed(1) : '-' }}</span></div>
              </div>

              <div class="perf-card" v-if="performance.advice_breakdown && Object.keys(performance.advice_breakdown).length > 0">
                <h3>操作建议分布</h3>
                <div class="bar-chart">
                  <div class="bar-row" v-for="(val, key) in performance.advice_breakdown" :key="key">
                    <span class="bar-label">{{ key }}</span>
                    <div class="bar-track">
                      <div class="bar-fill accent-bg" :style="{ width: barPct(val, performance.completed_count) }"></div>
                    </div>
                    <span class="bar-val">{{ val }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div v-else class="empty-state">{{ loading ? '加载中...' : '暂无绩效数据，请先运行回测' }}</div>
        </div>
      </div>

      <!-- 个股绩效 -->
      <div v-if="activeTab === 'stock'" class="tab-content">
        <div class="section">
          <div class="section-header">
            <h2>个股绩效</h2>
          </div>
          <div class="filter-bar">
            <input v-model="stockPerfCode" placeholder="输入股票代码" class="filter-input" @keydown.enter="loadStockPerformance" />
            <button class="btn-primary" @click="loadStockPerformance" :disabled="!stockPerfCode">查询</button>
          </div>
          <div v-if="stockPerformance" class="perf-content">
            <div class="summary-cards">
              <div class="card">
                <div class="card-label">总评估数</div>
                <div class="card-value">{{ stockPerformance.total_evaluations }}</div>
              </div>
              <div class="card">
                <div class="card-label">已完成</div>
                <div class="card-value">{{ stockPerformance.completed_count }}</div>
              </div>
              <div class="card">
                <div class="card-label">方向准确率</div>
                <div class="card-value" :class="accuracyClass(stockPerformance.direction_accuracy_pct)">{{ fmtPct(stockPerformance.direction_accuracy_pct) }}</div>
              </div>
              <div class="card">
                <div class="card-label">胜率</div>
                <div class="card-value" :class="accuracyClass(stockPerformance.win_rate_pct)">{{ fmtPct(stockPerformance.win_rate_pct) }}</div>
              </div>
              <div class="card">
                <div class="card-label">平均股票收益</div>
                <div class="card-value" :class="pnlClass(stockPerformance.avg_stock_return_pct)">{{ fmtPct(stockPerformance.avg_stock_return_pct) }}</div>
              </div>
              <div class="card">
                <div class="card-label">平均模拟收益</div>
                <div class="card-value" :class="pnlClass(stockPerformance.avg_simulated_return_pct)">{{ fmtPct(stockPerformance.avg_simulated_return_pct) }}</div>
              </div>
            </div>

            <div class="perf-grid">
              <div class="perf-card">
                <h3>多空分布</h3>
                <div class="bar-chart">
                  <div class="bar-row">
                    <span class="bar-label">做多</span>
                    <div class="bar-track">
                      <div class="bar-fill positive-bg" :style="{ width: barPct(stockPerformance.long_count, stockPerformance.completed_count) }"></div>
                    </div>
                    <span class="bar-val">{{ stockPerformance.long_count }}</span>
                  </div>
                  <div class="bar-row">
                    <span class="bar-label">观望</span>
                    <div class="bar-track">
                      <div class="bar-fill neutral-bg" :style="{ width: barPct(stockPerformance.cash_count, stockPerformance.completed_count) }"></div>
                    </div>
                    <span class="bar-val">{{ stockPerformance.cash_count }}</span>
                  </div>
                </div>
              </div>

              <div class="perf-card">
                <h3>胜负分布</h3>
                <div class="bar-chart">
                  <div class="bar-row">
                    <span class="bar-label">胜</span>
                    <div class="bar-track">
                      <div class="bar-fill positive-bg" :style="{ width: barPct(stockPerformance.win_count, stockPerformance.completed_count) }"></div>
                    </div>
                    <span class="bar-val">{{ stockPerformance.win_count }}</span>
                  </div>
                  <div class="bar-row">
                    <span class="bar-label">负</span>
                    <div class="bar-track">
                      <div class="bar-fill negative-bg" :style="{ width: barPct(stockPerformance.loss_count, stockPerformance.completed_count) }"></div>
                    </div>
                    <span class="bar-val">{{ stockPerformance.loss_count }}</span>
                  </div>
                  <div class="bar-row">
                    <span class="bar-label">中性</span>
                    <div class="bar-track">
                      <div class="bar-fill neutral-bg" :style="{ width: barPct(stockPerformance.neutral_count, stockPerformance.completed_count) }"></div>
                    </div>
                    <span class="bar-val">{{ stockPerformance.neutral_count }}</span>
                  </div>
                </div>
              </div>

              <div class="perf-card">
                <h3>风控指标</h3>
                <div class="detail-item"><span>止损触发率</span><span>{{ fmtPct(stockPerformance.stop_loss_trigger_rate) }}</span></div>
                <div class="detail-item"><span>止盈触发率</span><span>{{ fmtPct(stockPerformance.take_profit_trigger_rate) }}</span></div>
                <div class="detail-item"><span>模糊率</span><span>{{ fmtPct(stockPerformance.ambiguous_rate) }}</span></div>
                <div class="detail-item"><span>平均触发天数</span><span>{{ stockPerformance.avg_days_to_first_hit != null ? stockPerformance.avg_days_to_first_hit.toFixed(1) : '-' }}</span></div>
              </div>
            </div>
          </div>
          <div v-else class="empty-state">{{ loading ? '加载中...' : '输入股票代码查询个股回测绩效' }}</div>
        </div>
      </div>

      </div>
    </div>

    <!-- Toast -->
    <div v-if="toast" class="toast" :class="toast.type">{{ toast.message }}</div>
  </div>
</template>

<script>
import '@renderer/styles/layout.css'
import { setupSidePanelWidth } from './composables/useSidePanelWidth'
import { getApiBase } from './service/serverConfig'

const API_BASE = '/api/v1/backtest'

export default {
  name: 'Backtest',
  data() {
    return {
      baseUrl: getApiBase(),
      tabs: [
        { key: 'run', label: '运行回测' },
        { key: 'results', label: '回测结果' },
        { key: 'performance', label: '整体绩效' },
        { key: 'stock', label: '个股绩效' }
      ],
      activeTab: 'run',
      // Service
      serviceStatus: 'checking',
      serviceStatusLabel: '检查中...',
      serviceStatusTip: '',
      loading: false,
      // Run
      runForm: { code: '', eval_window_days: 10, min_age_days: 14, limit: 200, force: false },
      running: false,
      runResult: null,
      // Results
      results: [],
      resultFilter: { code: '', eval_window_days: null, analysis_date_from: '', analysis_date_to: '' },
      resultPagination: { page: 1, limit: 20, total: 0 },
      selectedResult: null,
      // Performance
      performance: null,
      // Stock Performance
      stockPerfCode: '',
      stockPerformance: null,
      // Toast
      toast: null,
      toastTimer: null
    }
  },
  watch: {
    activeTab(tab) {
      if (tab === 'results') this.loadResults()
      else if (tab === 'performance') this.loadPerformance()
    }
  },
  async mounted() {
    // 同步侧栏宽度并启用拖拽调整
    setupSidePanelWidth(this.$refs.sidePanel)

    await this.checkService()
  },
  methods: {
    // ---- API ----
    async api(path, options = {}) {
      const url = `${this.baseUrl}${API_BASE}${path}`
      const res = await fetch(url, {
        headers: { 'Content-Type': 'application/json', ...options.headers },
        ...options
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || err.message || `HTTP ${res.status}`)
      }
      return res.json()
    },

    // ---- Service ----
    async checkService() {
      try {
        await fetch(`${this.baseUrl}/health`, { signal: AbortSignal.timeout(3000) })
        this.serviceStatus = 'online'
        this.serviceStatusLabel = '在线'
        this.serviceStatusTip = 'DSA 服务运行中'
      } catch {
        this.serviceStatus = 'offline'
        this.serviceStatusLabel = '离线'
        this.serviceStatusTip = 'DSA 服务未运行'
      }
    },

    // ---- Run Backtest ----
    async runBacktest() {
      this.running = true
      this.runResult = null
      try {
        const params = new URLSearchParams()
        if (this.runForm.code) params.set('code', this.runForm.code)
        if (this.runForm.force) params.set('force', 'true')
        params.set('eval_window_days', this.runForm.eval_window_days)
        params.set('min_age_days', this.runForm.min_age_days)
        params.set('limit', this.runForm.limit)
        this.runResult = await this.api(`/run?${params}`, { method: 'POST' })
        this.showToast(`回测完成：处理 ${this.runResult.processed} 条，完成 ${this.runResult.completed} 条`)
      } catch (e) {
        this.showToast('回测失败: ' + e.message, 'error')
      } finally {
        this.running = false
      }
    },

    // ---- Results ----
    resetAndLoadResults() {
      this.resultPagination.page = 1
      this.loadResults()
    },
    async loadResults() {
      this.loading = true
      try {
        const params = new URLSearchParams({ page: this.resultPagination.page, limit: this.resultPagination.limit })
        if (this.resultFilter.code) params.set('code', this.resultFilter.code)
        if (this.resultFilter.eval_window_days) params.set('eval_window_days', this.resultFilter.eval_window_days)
        if (this.resultFilter.analysis_date_from) params.set('analysis_date_from', this.resultFilter.analysis_date_from)
        if (this.resultFilter.analysis_date_to) params.set('analysis_date_to', this.resultFilter.analysis_date_to)
        const data = await this.api(`/results?${params}`)
        this.results = data.items || data.results || data
        if (Array.isArray(this.results)) {
          this.resultPagination.total = data.total || this.results.length
        }
      } catch (e) {
        this.showToast('加载结果失败: ' + e.message, 'error')
      } finally {
        this.loading = false
      }
    },
    selectResult(r) {
      this.selectedResult = this.selectedResult === r ? null : r
    },

    // ---- Performance ----
    async loadPerformance() {
      this.loading = true
      try {
        this.performance = await this.api('/performance')
      } catch (e) {
        this.showToast('加载绩效失败: ' + e.message, 'error')
      } finally {
        this.loading = false
      }
    },

    // ---- Stock Performance ----
    async loadStockPerformance() {
      if (!this.stockPerfCode) return
      this.loading = true
      this.stockPerformance = null
      try {
        this.stockPerformance = await this.api(`/performance/${encodeURIComponent(this.stockPerfCode)}`)
      } catch (e) {
        this.showToast('加载个股绩效失败: ' + e.message, 'error')
      } finally {
        this.loading = false
      }
    },

    // ---- Formatting ----
    fmtPct(val) {
      if (val == null) return '-'
      return (typeof val === 'number') ? val.toFixed(2) + '%' : val
    },
    fmtPrice(val) {
      if (val == null) return '-'
      return val.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
    },
    pnlClass(val) {
      if (val > 0) return 'positive'
      if (val < 0) return 'negative'
      return ''
    },
    accuracyClass(val) {
      if (val >= 60) return 'positive'
      if (val >= 50) return 'warning'
      return 'negative'
    },
    barPct(part, total) {
      if (!total) return '0%'
      return Math.min((part / total) * 100, 100).toFixed(1) + '%'
    },
    directionLabel(d) {
      return { up: '看涨', down: '看跌', not_down: '不跌', flat: '震荡' }[d] || d || '-'
    },
    outcomeLabel(o) {
      return { win: '胜', loss: '负', neutral: '中性' }[o] || o || '-'
    },
    firstHitLabel(f) {
      return { take_profit: '止盈', stop_loss: '止损', ambiguous: '模糊', neither: '无', not_applicable: 'N/A' }[f] || f || '-'
    },

    // ---- Toast ----
    showToast(message, type = 'success') {
      clearTimeout(this.toastTimer)
      this.toast = { message, type }
      this.toastTimer = setTimeout(() => { this.toast = null }, 3000)
    }
  }
}
</script>

<style scoped>
.backtest-app {
  height: 100vh;
  color: #ccc;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 13px;
}

/* Service status */
.service-status {
  display: flex; align-items: center; gap: 4px; font-size: 11px; padding: 2px 0;
}
.service-status .status-dot { width: 6px; height: 6px; border-radius: 50%; }
.service-status.online .status-dot { background: #4caf50; }
.service-status.offline .status-dot { background: #f44336; }
.service-status.checking .status-dot { background: #ff9800; }

/* Main */
.main-view-content { padding: 16px; }
.tab-content { animation: fadeIn 0.15s; }
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

/* Section */
.section { margin-bottom: 24px; }
.section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.section-header h2 { font-size: 15px; font-weight: 600; color: #e0e0e0; margin: 0; }
.section-actions { display: flex; gap: 8px; align-items: center; }

/* Cards */
.summary-cards {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; margin-bottom: 20px;
}
.card {
  background: #2d2d2d; border: 1px solid #3a3a3a; border-radius: 6px; padding: 14px;
}
.card-label { font-size: 11px; color: #888; margin-bottom: 6px; }
.card-value { font-size: 18px; font-weight: 600; color: #e0e0e0; }

/* Run form */
.run-form { max-width: 600px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 16px; }
.form-row { display: flex; flex-direction: column; gap: 4px; }
.form-row label { font-size: 12px; color: #999; }
.form-input {
  background: #1e1e1e; color: #ccc; border: 1px solid #555; padding: 7px 10px; border-radius: 4px; font-size: 13px;
}
.form-input:focus { border-color: #0078d4; outline: none; }
.checkbox-row { flex-direction: row; align-items: center; }
.checkbox-row label { display: flex; align-items: center; gap: 6px; color: #ccc; cursor: pointer; }
.run-actions { margin-top: 16px; }

.running-indicator {
  display: flex; align-items: center; gap: 10px; margin-top: 16px; color: #999;
}
.spinner {
  width: 18px; height: 18px; border: 2px solid #555; border-top-color: #0078d4;
  border-radius: 50%; animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.run-result {
  margin-top: 20px; padding: 16px; background: #2d2d2d; border: 1px solid #3a3a3a; border-radius: 6px;
}
.run-result.success { border-color: #4caf50; }
.run-result h3 { margin: 0 0 12px 0; font-size: 14px; color: #e0e0e0; }
.result-grid { display: flex; gap: 20px; flex-wrap: wrap; }
.result-item { display: flex; flex-direction: column; gap: 4px; }
.result-label { font-size: 11px; color: #888; }
.result-value { font-size: 16px; font-weight: 600; color: #e0e0e0; }

/* Filter */
.filter-bar { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.filter-input {
  background: #333; color: #ccc; border: 1px solid #555; padding: 5px 10px; border-radius: 4px; font-size: 12px; min-width: 100px;
}
.filter-input:focus { border-color: #0078d4; outline: none; }
.filter-sm { max-width: 100px; }

/* Table */
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #333; font-size: 12px; white-space: nowrap; }
th { color: #999; font-weight: 500; background: #252526; position: sticky; top: 0; }
td { color: #ccc; }
.mono { font-family: 'Consolas', 'Courier New', monospace; }
.num { text-align: right; font-family: 'Consolas', monospace; }
tbody tr { cursor: pointer; }
tbody tr:hover { background: #2a2d2e; }
tbody tr.selected { background: #094771; }

.positive { color: #4caf50; }
.negative { color: #f44336; }
.warning { color: #ff9800; }

/* Badges */
.direction-badge, .position-badge, .outcome-badge {
  padding: 2px 8px; border-radius: 3px; font-size: 11px; display: inline-block;
}
.direction-badge.up { background: rgba(76,175,80,0.15); color: #4caf50; }
.direction-badge.down { background: rgba(244,67,54,0.15); color: #f44336; }
.direction-badge.not_down { background: rgba(33,150,243,0.15); color: #2196f3; }
.direction-badge.flat { background: rgba(158,158,158,0.15); color: #9e9e9e; }
.position-badge.long { background: rgba(76,175,80,0.15); color: #4caf50; }
.position-badge.cash { background: rgba(158,158,158,0.15); color: #9e9e9e; }
.outcome-badge.win { background: rgba(76,175,80,0.15); color: #4caf50; }
.outcome-badge.loss { background: rgba(244,67,54,0.15); color: #f44336; }
.outcome-badge.neutral { background: rgba(158,158,158,0.15); color: #9e9e9e; }

/* Pagination */
.pagination { display: flex; align-items: center; gap: 12px; justify-content: center; margin-top: 12px; }
.pagination button { background: #3a3a3a; color: #ccc; border: 1px solid #555; padding: 4px 12px; border-radius: 3px; cursor: pointer; font-size: 12px; }
.pagination button:disabled { opacity: 0.4; cursor: not-allowed; }
.pagination span { font-size: 12px; color: #999; }

/* Detail */
.detail-section { margin-top: 8px; }
.detail-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
.detail-card {
  background: #2d2d2d; border: 1px solid #3a3a3a; border-radius: 6px; padding: 14px;
}
.detail-card h3 { margin: 0 0 10px 0; font-size: 13px; color: #e0e0e0; }
.detail-item { display: flex; justify-content: space-between; align-items: center; padding: 5px 0; border-bottom: 1px solid #333; font-size: 12px; }

/* Performance */
.perf-content { }
.perf-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.perf-card {
  background: #2d2d2d; border: 1px solid #3a3a3a; border-radius: 6px; padding: 16px;
}
.perf-card h3 { margin: 0 0 12px 0; font-size: 13px; color: #e0e0e0; }

.bar-chart { display: flex; flex-direction: column; gap: 8px; }
.bar-row { display: flex; align-items: center; gap: 10px; }
.bar-label { width: 40px; font-size: 12px; color: #999; text-align: right; flex-shrink: 0; }
.bar-track { flex: 1; height: 10px; background: #333; border-radius: 5px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 5px; transition: width 0.3s; }
.bar-val { width: 40px; font-size: 12px; color: #ccc; font-family: 'Consolas', monospace; }
.positive-bg { background: #4caf50; }
.negative-bg { background: #f44336; }
.neutral-bg { background: #9e9e9e; }
.accent-bg { background: #0078d4; }

/* Buttons */
.btn-primary {
  background: #0078d4; color: #fff; border: none; padding: 6px 16px; border-radius: 4px; cursor: pointer; font-size: 12px;
}
.btn-primary:hover { background: #1a8ae8; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary {
  background: #3a3a3a; color: #ccc; border: 1px solid #555; padding: 6px 16px; border-radius: 4px; cursor: pointer; font-size: 12px;
}
.btn-secondary:hover { background: #444; }
.btn-icon { background: none; border: none; color: #ccc; cursor: pointer; font-size: 16px; padding: 4px; }
.btn-icon:hover { color: #fff; }

/* Empty */
.empty-state { text-align: center; padding: 40px; color: #666; font-size: 13px; }

/* Toast */
.toast {
  position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
  padding: 10px 24px; border-radius: 6px; font-size: 13px; z-index: 2000; animation: slideUp 0.2s;
}
.toast.success { background: #2e7d32; color: #fff; }
.toast.error { background: #c62828; color: #fff; }
@keyframes slideUp { from { transform: translateX(-50%) translateY(20px); opacity: 0; } to { transform: translateX(-50%) translateY(0); opacity: 1; } }
</style>
