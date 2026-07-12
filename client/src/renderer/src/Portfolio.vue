<template>
  <div class="portfolio-app view-container">
    <!-- 左侧导航面板 -->
    <aside class="side-panel" ref="sidePanel">
      <div class="side-panel-resize-handle"></div>
      <div class="side-panel-header">持仓管理</div>
      <div class="account-selector-wrap">
        <select v-model="selectedAccountId" class="account-select" @change="onAccountChange">
          <option :value="null">全部账户</option>
          <option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.name }} ({{ a.broker || '未知' }})</option>
        </select>
      </div>
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

    <!-- 主内容区 -->
    <div class="main-view">
      <div class="main-view-content">
      <!-- 概览 -->
      <div v-if="activeTab === 'overview'" class="tab-content">
        <div class="summary-cards">
          <div class="card">
            <div class="card-label">总资产</div>
            <div class="card-value">{{ fmtMoney(snapshot.total_equity) }}</div>
          </div>
          <div class="card">
            <div class="card-label">持仓市值</div>
            <div class="card-value">{{ fmtMoney(snapshot.total_market_value) }}</div>
          </div>
          <div class="card">
            <div class="card-label">现金</div>
            <div class="card-value">{{ fmtMoney(snapshot.total_cash) }}</div>
          </div>
          <div class="card">
            <div class="card-label">未实现盈亏</div>
            <div class="card-value" :class="pnlClass(snapshot.unrealized_pnl)">{{ fmtMoney(snapshot.unrealized_pnl) }}</div>
          </div>
          <div class="card">
            <div class="card-label">已实现盈亏</div>
            <div class="card-value" :class="pnlClass(snapshot.realized_pnl)">{{ fmtMoney(snapshot.realized_pnl) }}</div>
          </div>
          <div class="card">
            <div class="card-label">总手续费/税</div>
            <div class="card-value negative">{{ fmtMoney((snapshot.fee_total || 0) + (snapshot.tax_total || 0)) }}</div>
          </div>
        </div>

        <div class="section">
          <div class="section-header">
            <h2>持仓明细</h2>
            <div class="section-actions">
              <select v-model="costMethod" @change="loadSnapshot" class="small-select">
                <option value="fifo">FIFO</option>
                <option value="avg">均价法</option>
              </select>
              <button class="btn-icon" @click="loadSnapshot" title="刷新">🔄</button>
            </div>
          </div>
          <div class="table-wrap">
            <table v-if="positions.length > 0">
              <thead>
                <tr>
                  <th>账户</th>
                  <th>代码</th>
                  <th>市场</th>
                  <th>数量</th>
                  <th>成本价</th>
                  <th>现价</th>
                  <th>市值</th>
                  <th>盈亏</th>
                  <th>盈亏%</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(pos, i) in positions" :key="i">
                  <td>{{ pos._accountName }}</td>
                  <td class="mono">{{ pos.symbol }}</td>
                  <td>{{ marketLabel(pos.market) }}</td>
                  <td class="num">{{ pos.quantity }}</td>
                  <td class="num">{{ fmtPrice(pos.avg_cost) }}</td>
                  <td class="num">{{ fmtPrice(pos.last_price) }}</td>
                  <td class="num">{{ fmtMoney(pos.market_value_base) }}</td>
                  <td class="num" :class="pnlClass(pos.unrealized_pnl_base)">{{ fmtMoney(pos.unrealized_pnl_base) }}</td>
                  <td class="num" :class="pnlClass(pos.unrealized_pnl_base)">{{ fmtPct(pos.unrealized_pnl_base, pos.total_cost) }}</td>
                </tr>
              </tbody>
            </table>
            <div v-else class="empty-state">暂无持仓数据</div>
          </div>
        </div>
      </div>

      <!-- 交易记录 -->
      <div v-if="activeTab === 'trades'" class="tab-content">
        <div class="section">
          <div class="section-header">
            <h2>交易记录</h2>
            <div class="section-actions">
              <button class="btn-primary" @click="showTradeForm = true">+ 录入交易</button>
            </div>
          </div>
          <div class="filter-bar">
            <input v-model="tradeFilter.symbol" placeholder="代码" class="filter-input" @keydown.enter="loadTrades" />
            <select v-model="tradeFilter.side" class="filter-input">
              <option value="">全部方向</option>
              <option value="buy">买入</option>
              <option value="sell">卖出</option>
            </select>
            <input v-model="tradeFilter.date_from" type="date" class="filter-input" />
            <input v-model="tradeFilter.date_to" type="date" class="filter-input" />
            <button class="btn-secondary" @click="loadTrades">查询</button>
          </div>
          <div class="table-wrap">
            <table v-if="trades.length > 0">
              <thead>
                <tr>
                  <th>日期</th>
                  <th>代码</th>
                  <th>方向</th>
                  <th>数量</th>
                  <th>价格</th>
                  <th>手续费</th>
                  <th>税费</th>
                  <th>备注</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="t in trades" :key="t.id">
                  <td>{{ t.trade_date }}</td>
                  <td class="mono">{{ t.symbol }}</td>
                  <td><span class="side-badge" :class="t.side">{{ t.side === 'buy' ? '买入' : '卖出' }}</span></td>
                  <td class="num">{{ t.quantity }}</td>
                  <td class="num">{{ fmtPrice(t.price) }}</td>
                  <td class="num">{{ fmtMoney(t.fee) }}</td>
                  <td class="num">{{ fmtMoney(t.tax) }}</td>
                  <td>{{ t.note || '-' }}</td>
                  <td><button class="btn-danger-sm" @click="deleteTrade(t.id)">删除</button></td>
                </tr>
              </tbody>
            </table>
            <div v-else class="empty-state">暂无交易记录</div>
          </div>
          <div v-if="tradePagination.total > tradePagination.page_size" class="pagination">
            <button :disabled="tradePagination.page <= 1" @click="tradePagination.page--; loadTrades()">上一页</button>
            <span>{{ tradePagination.page }} / {{ Math.ceil(tradePagination.total / tradePagination.page_size) }}</span>
            <button :disabled="tradePagination.page * tradePagination.page_size >= tradePagination.total" @click="tradePagination.page++; loadTrades()">下一页</button>
          </div>
        </div>
      </div>

      <!-- 现金流水 -->
      <div v-if="activeTab === 'cash'" class="tab-content">
        <div class="section">
          <div class="section-header">
            <h2>现金流水</h2>
            <div class="section-actions">
              <button class="btn-primary" @click="showCashForm = true">+ 记录出入金</button>
            </div>
          </div>
          <div class="filter-bar">
            <select v-model="cashFilter.direction" class="filter-input">
              <option value="">全部方向</option>
              <option value="in">入金</option>
              <option value="out">出金</option>
            </select>
            <input v-model="cashFilter.date_from" type="date" class="filter-input" />
            <input v-model="cashFilter.date_to" type="date" class="filter-input" />
            <button class="btn-secondary" @click="loadCashLedger">查询</button>
          </div>
          <div class="table-wrap">
            <table v-if="cashItems.length > 0">
              <thead>
                <tr>
                  <th>日期</th>
                  <th>方向</th>
                  <th>金额</th>
                  <th>币种</th>
                  <th>备注</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="c in cashItems" :key="c.id">
                  <td>{{ c.event_date }}</td>
                  <td><span class="side-badge" :class="c.direction">{{ c.direction === 'in' ? '入金' : '出金' }}</span></td>
                  <td class="num">{{ fmtMoney(c.amount) }}</td>
                  <td>{{ c.currency }}</td>
                  <td>{{ c.note || '-' }}</td>
                  <td><button class="btn-danger-sm" @click="deleteCashEntry(c.id)">删除</button></td>
                </tr>
              </tbody>
            </table>
            <div v-else class="empty-state">暂无现金流水</div>
          </div>
          <div v-if="cashPagination.total > cashPagination.page_size" class="pagination">
            <button :disabled="cashPagination.page <= 1" @click="cashPagination.page--; loadCashLedger()">上一页</button>
            <span>{{ cashPagination.page }} / {{ Math.ceil(cashPagination.total / cashPagination.page_size) }}</span>
            <button :disabled="cashPagination.page * cashPagination.page_size >= cashPagination.total" @click="cashPagination.page++; loadCashLedger()">下一页</button>
          </div>
        </div>
      </div>

      <!-- 公司行动 -->
      <div v-if="activeTab === 'actions'" class="tab-content">
        <div class="section">
          <div class="section-header">
            <h2>公司行动</h2>
            <div class="section-actions">
              <button class="btn-primary" @click="showActionForm = true">+ 添加行动</button>
            </div>
          </div>
          <div class="table-wrap">
            <table v-if="corpActions.length > 0">
              <thead>
                <tr>
                  <th>生效日期</th>
                  <th>代码</th>
                  <th>类型</th>
                  <th>每股分红</th>
                  <th>拆股比例</th>
                  <th>备注</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="a in corpActions" :key="a.id">
                  <td>{{ a.effective_date }}</td>
                  <td class="mono">{{ a.symbol }}</td>
                  <td>{{ actionTypeLabel(a.action_type) }}</td>
                  <td class="num">{{ a.cash_dividend_per_share != null ? fmtPrice(a.cash_dividend_per_share) : '-' }}</td>
                  <td class="num">{{ a.split_ratio != null ? a.split_ratio : '-' }}</td>
                  <td>{{ a.note || '-' }}</td>
                  <td><button class="btn-danger-sm" @click="deleteCorpAction(a.id)">删除</button></td>
                </tr>
              </tbody>
            </table>
            <div v-else class="empty-state">暂无公司行动记录</div>
          </div>
          <div v-if="actionPagination.total > actionPagination.page_size" class="pagination">
            <button :disabled="actionPagination.page <= 1" @click="actionPagination.page--; loadCorpActions()">上一页</button>
            <span>{{ actionPagination.page }} / {{ Math.ceil(actionPagination.total / actionPagination.page_size) }}</span>
            <button :disabled="actionPagination.page * actionPagination.page_size >= actionPagination.total" @click="actionPagination.page++; loadCorpActions()">下一页</button>
          </div>
        </div>
      </div>

      <!-- 账户管理 -->
      <div v-if="activeTab === 'accounts'" class="tab-content">
        <div class="section">
          <div class="section-header">
            <h2>账户管理</h2>
            <div class="section-actions">
              <button class="btn-primary" @click="showAccountForm = true">+ 新建账户</button>
            </div>
          </div>
          <div class="table-wrap">
            <table v-if="accounts.length > 0">
              <thead>
                <tr>
                  <th>名称</th>
                  <th>券商</th>
                  <th>市场</th>
                  <th>基础币种</th>
                  <th>状态</th>
                  <th>创建时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="a in accounts" :key="a.id">
                  <td>{{ a.name }}</td>
                  <td>{{ a.broker || '-' }}</td>
                  <td>{{ marketLabel(a.market) }}</td>
                  <td>{{ a.base_currency }}</td>
                  <td><span class="status-tag" :class="{ active: a.is_active }">{{ a.is_active ? '活跃' : '停用' }}</span></td>
                  <td>{{ formatDate(a.created_at) }}</td>
                  <td>
                    <button class="btn-secondary-sm" @click="editAccount(a)">编辑</button>
                    <button class="btn-danger-sm" @click="deleteAccount(a.id)">停用</button>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-else class="empty-state">暂无账户，请创建一个账户开始使用</div>
          </div>
        </div>
      </div>

      <!-- CSV 导入 -->
      <div v-if="activeTab === 'import'" class="tab-content">
        <div class="section">
          <div class="section-header">
            <h2>CSV 导入</h2>
          </div>
          <div class="import-flow">
            <div class="import-step">
              <h3>1. 选择券商和账户</h3>
              <div class="form-row">
                <label>券商格式</label>
                <select v-model="importBroker" class="form-input">
                  <option value="">请选择</option>
                  <option v-for="b in brokerList" :key="b.broker" :value="b.broker">{{ b.display_name }}</option>
                </select>
              </div>
              <div class="form-row">
                <label>目标账户</label>
                <select v-model="importAccountId" class="form-input">
                  <option :value="null">请选择</option>
                  <option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.name }}</option>
                </select>
              </div>
            </div>
            <div class="import-step">
              <h3>2. 上传文件</h3>
              <div class="file-upload" @click="triggerFileInput" @dragover.prevent @drop.prevent="handleFileDrop">
                <input ref="fileInput" type="file" accept=".csv" @change="handleFileSelect" style="display:none" />
                <div v-if="!importFile" class="upload-placeholder">
                  📁 点击选择或拖拽 CSV 文件
                </div>
                <div v-else class="upload-info">
                  📄 {{ importFile.name }} ({{ fmtFileSize(importFile.size) }})
                  <button class="btn-link" @click.stop="importFile = null; importPreview = null">移除</button>
                </div>
              </div>
            </div>
            <div class="import-step">
              <h3>3. 预览与提交</h3>
              <div class="import-actions">
                <button class="btn-secondary" @click="parseCSV" :disabled="!canParse">预览解析</button>
                <button class="btn-primary" @click="commitCSV" :disabled="!canCommit">确认导入</button>
              </div>
              <div v-if="importPreview" class="import-preview">
                <p>解析 {{ importPreview.record_count }} 条记录，跳过 {{ importPreview.skipped_count }} 条，错误 {{ importPreview.error_count }} 条</p>
                <div class="table-wrap" v-if="importPreview.records && importPreview.records.length > 0">
                  <table>
                    <thead>
                      <tr>
                        <th>日期</th>
                        <th>代码</th>
                        <th>方向</th>
                        <th>数量</th>
                        <th>价格</th>
                        <th>手续费</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="(r, i) in importPreview.records.slice(0, 20)" :key="i">
                        <td>{{ r.trade_date }}</td>
                        <td class="mono">{{ r.symbol }}</td>
                        <td>{{ r.side === 'buy' ? '买入' : '卖出' }}</td>
                        <td class="num">{{ r.quantity }}</td>
                        <td class="num">{{ fmtPrice(r.price) }}</td>
                        <td class="num">{{ fmtMoney(r.fee) }}</td>
                      </tr>
                    </tbody>
                  </table>
                  <p v-if="importPreview.records.length > 20" class="text-muted">仅显示前 20 条...</p>
                </div>
              </div>
              <div v-if="importResult" class="import-result" :class="{ success: importResult.failed_count === 0 }">
                <p>导入完成：插入 {{ importResult.inserted_count }} 条，重复跳过 {{ importResult.duplicate_count }} 条，失败 {{ importResult.failed_count }} 条</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 风险分析 -->
      <div v-if="activeTab === 'risk'" class="tab-content">
        <div class="section">
          <div class="section-header">
            <h2>风险分析</h2>
            <div class="section-actions">
              <button class="btn-icon" @click="loadRisk" title="刷新">🔄</button>
              <button class="btn-secondary" @click="refreshFx">刷新汇率</button>
            </div>
          </div>
          <div v-if="risk" class="risk-grid">
            <div class="risk-card">
              <h3>回撤</h3>
              <div class="risk-item">
                <span>最大回撤</span>
                <span class="risk-val" :class="pnlClass(risk.drawdown?.max_drawdown)">{{ fmtPctVal(risk.drawdown?.max_drawdown) }}</span>
              </div>
              <div class="risk-item">
                <span>当前回撤</span>
                <span class="risk-val" :class="pnlClass(risk.drawdown?.current_drawdown)">{{ fmtPctVal(risk.drawdown?.current_drawdown) }}</span>
              </div>
            </div>
            <div class="risk-card">
              <h3>止损预警</h3>
              <div class="risk-item">
                <span>严重</span>
                <span class="risk-val negative">{{ risk.stop_loss?.critical || 0 }}</span>
              </div>
              <div class="risk-item">
                <span>警告</span>
                <span class="risk-val warning">{{ risk.stop_loss?.warning || 0 }}</span>
              </div>
            </div>
            <div class="risk-card wide">
              <h3>集中度 - 前5大持仓</h3>
              <div class="concentration-list" v-if="risk.concentration?.top_5">
                <div v-for="(item, i) in risk.concentration.top_5" :key="i" class="concentration-item">
                  <span class="mono">{{ item.symbol }}</span>
                  <div class="bar-wrap">
                    <div class="bar-fill" :style="{ width: (item.weight * 100) + '%' }"></div>
                  </div>
                  <span class="num">{{ (item.weight * 100).toFixed(1) }}%</span>
                </div>
              </div>
              <div v-else class="empty-state">暂无数据</div>
            </div>
          </div>
          <div v-else class="empty-state">点击刷新获取风险分析</div>
        </div>
      </div>
      </div>
    </div>

    <!-- 交易录入弹窗 -->
    <div v-if="showTradeForm" class="modal-overlay" @click.self="showTradeForm = false">
      <div class="modal">
        <div class="modal-header">
          <h3>录入交易</h3>
          <button class="btn-icon" @click="showTradeForm = false">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-row">
            <label>账户</label>
            <select v-model="tradeForm.account_id" class="form-input">
              <option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.name }}</option>
            </select>
          </div>
          <div class="form-row">
            <label>代码</label>
            <input v-model="tradeForm.symbol" class="form-input" placeholder="如 600519" />
          </div>
          <div class="form-row">
            <label>日期</label>
            <input v-model="tradeForm.trade_date" type="date" class="form-input" />
          </div>
          <div class="form-row">
            <label>方向</label>
            <select v-model="tradeForm.side" class="form-input">
              <option value="buy">买入</option>
              <option value="sell">卖出</option>
            </select>
          </div>
          <div class="form-row">
            <label>数量</label>
            <input v-model.number="tradeForm.quantity" type="number" class="form-input" min="0" step="1" />
          </div>
          <div class="form-row">
            <label>价格</label>
            <input v-model.number="tradeForm.price" type="number" class="form-input" min="0" step="0.01" />
          </div>
          <div class="form-row">
            <label>手续费</label>
            <input v-model.number="tradeForm.fee" type="number" class="form-input" min="0" step="0.01" />
          </div>
          <div class="form-row">
            <label>税费</label>
            <input v-model.number="tradeForm.tax" type="number" class="form-input" min="0" step="0.01" />
          </div>
          <div class="form-row">
            <label>备注</label>
            <input v-model="tradeForm.note" class="form-input" placeholder="可选" />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-secondary" @click="showTradeForm = false">取消</button>
          <button class="btn-primary" @click="submitTrade">确认</button>
        </div>
      </div>
    </div>

    <!-- 现金出入金弹窗 -->
    <div v-if="showCashForm" class="modal-overlay" @click.self="showCashForm = false">
      <div class="modal">
        <div class="modal-header">
          <h3>记录出入金</h3>
          <button class="btn-icon" @click="showCashForm = false">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-row">
            <label>账户</label>
            <select v-model="cashForm.account_id" class="form-input">
              <option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.name }}</option>
            </select>
          </div>
          <div class="form-row">
            <label>日期</label>
            <input v-model="cashForm.event_date" type="date" class="form-input" />
          </div>
          <div class="form-row">
            <label>方向</label>
            <select v-model="cashForm.direction" class="form-input">
              <option value="in">入金</option>
              <option value="out">出金</option>
            </select>
          </div>
          <div class="form-row">
            <label>金额</label>
            <input v-model.number="cashForm.amount" type="number" class="form-input" min="0" step="0.01" />
          </div>
          <div class="form-row">
            <label>币种</label>
            <input v-model="cashForm.currency" class="form-input" placeholder="CNY" />
          </div>
          <div class="form-row">
            <label>备注</label>
            <input v-model="cashForm.note" class="form-input" placeholder="可选" />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-secondary" @click="showCashForm = false">取消</button>
          <button class="btn-primary" @click="submitCash">确认</button>
        </div>
      </div>
    </div>

    <!-- 公司行动弹窗 -->
    <div v-if="showActionForm" class="modal-overlay" @click.self="showActionForm = false">
      <div class="modal">
        <div class="modal-header">
          <h3>添加公司行动</h3>
          <button class="btn-icon" @click="showActionForm = false">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-row">
            <label>账户</label>
            <select v-model="actionForm.account_id" class="form-input">
              <option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.name }}</option>
            </select>
          </div>
          <div class="form-row">
            <label>代码</label>
            <input v-model="actionForm.symbol" class="form-input" placeholder="如 600519" />
          </div>
          <div class="form-row">
            <label>生效日期</label>
            <input v-model="actionForm.effective_date" type="date" class="form-input" />
          </div>
          <div class="form-row">
            <label>类型</label>
            <select v-model="actionForm.action_type" class="form-input">
              <option value="cash_dividend">现金分红</option>
              <option value="split_adjustment">拆股/合股</option>
            </select>
          </div>
          <div class="form-row" v-if="actionForm.action_type === 'cash_dividend'">
            <label>每股分红</label>
            <input v-model.number="actionForm.cash_dividend_per_share" type="number" class="form-input" min="0" step="0.01" />
          </div>
          <div class="form-row" v-if="actionForm.action_type === 'split_adjustment'">
            <label>拆股比例</label>
            <input v-model.number="actionForm.split_ratio" type="number" class="form-input" min="0" step="0.1" />
          </div>
          <div class="form-row">
            <label>备注</label>
            <input v-model="actionForm.note" class="form-input" placeholder="可选" />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-secondary" @click="showActionForm = false">取消</button>
          <button class="btn-primary" @click="submitCorpAction">确认</button>
        </div>
      </div>
    </div>

    <!-- 账户编辑弹窗 -->
    <div v-if="showAccountForm" class="modal-overlay" @click.self="showAccountForm = false">
      <div class="modal">
        <div class="modal-header">
          <h3>{{ accountForm.id ? '编辑账户' : '新建账户' }}</h3>
          <button class="btn-icon" @click="showAccountForm = false">✕</button>
        </div>
        <div class="modal-body">
          <div class="form-row">
            <label>名称</label>
            <input v-model="accountForm.name" class="form-input" placeholder="如 我的A股账户" />
          </div>
          <div class="form-row">
            <label>券商</label>
            <input v-model="accountForm.broker" class="form-input" placeholder="如 华泰" />
          </div>
          <div class="form-row">
            <label>市场</label>
            <select v-model="accountForm.market" class="form-input">
              <option value="cn">A 股</option>
              <option value="hk">港股</option>
              <option value="us">美股</option>
            </select>
          </div>
          <div class="form-row">
            <label>基础币种</label>
            <input v-model="accountForm.base_currency" class="form-input" placeholder="CNY" />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-secondary" @click="showAccountForm = false">取消</button>
          <button class="btn-primary" @click="submitAccount">确认</button>
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

const API_BASE = '/api/v1/portfolio'

export default {
  name: 'Portfolio',
  data() {
    return {
      baseUrl: getApiBase(),
      // Tabs
      tabs: [
        { key: 'overview', label: '概览' },
        { key: 'trades', label: '交易记录' },
        { key: 'cash', label: '现金流水' },
        { key: 'actions', label: '公司行动' },
        { key: 'accounts', label: '账户管理' },
        { key: 'import', label: 'CSV 导入' },
        { key: 'risk', label: '风险分析' }
      ],
      activeTab: 'overview',
      // Service
      serviceStatus: 'checking',
      serviceStatusLabel: '检查中...',
      serviceStatusTip: '',
      // Accounts
      accounts: [],
      selectedAccountId: null,
      // Snapshot
      snapshot: { total_equity: 0, total_market_value: 0, total_cash: 0, unrealized_pnl: 0, realized_pnl: 0, fee_total: 0, tax_total: 0 },
      positions: [],
      costMethod: 'fifo',
      // Trades
      trades: [],
      tradeFilter: { symbol: '', side: '', date_from: '', date_to: '' },
      tradePagination: { page: 1, page_size: 20, total: 0 },
      // Cash
      cashItems: [],
      cashFilter: { direction: '', date_from: '', date_to: '' },
      cashPagination: { page: 1, page_size: 20, total: 0 },
      // Corp Actions
      corpActions: [],
      actionPagination: { page: 1, page_size: 20, total: 0 },
      // Risk
      risk: null,
      // CSV Import
      brokerList: [],
      importBroker: '',
      importAccountId: null,
      importFile: null,
      importPreview: null,
      importResult: null,
      // Forms
      showTradeForm: false,
      tradeForm: this.emptyTradeForm(),
      showCashForm: false,
      cashForm: this.emptyCashForm(),
      showActionForm: false,
      actionForm: this.emptyActionForm(),
      showAccountForm: false,
      accountForm: this.emptyAccountForm(),
      // Toast
      toast: null,
      toastTimer: null
    }
  },
  computed: {
    canParse() {
      return this.importBroker && this.importFile
    },
    canCommit() {
      return this.importBroker && this.importAccountId && this.importFile
    }
  },
  watch: {
    activeTab(tab) {
      if (tab === 'overview') this.loadSnapshot()
      else if (tab === 'trades') this.loadTrades()
      else if (tab === 'cash') this.loadCashLedger()
      else if (tab === 'actions') this.loadCorpActions()
      else if (tab === 'accounts') this.loadAccounts()
      else if (tab === 'import') this.loadBrokers()
      else if (tab === 'risk') this.loadRisk()
    }
  },
  async mounted() {
    // 同步侧栏宽度并启用拖拽调整
    setupSidePanelWidth(this.$refs.sidePanel)

    await this.checkService()
    await this.loadAccounts()
    await this.loadSnapshot()
  },
  methods: {
    emptyTradeForm() {
      return { account_id: null, symbol: '', trade_date: new Date().toISOString().slice(0, 10), side: 'buy', quantity: 0, price: 0, fee: 0, tax: 0, note: '' }
    },
    emptyCashForm() {
      return { account_id: null, event_date: new Date().toISOString().slice(0, 10), direction: 'in', amount: 0, currency: 'CNY', note: '' }
    },
    emptyActionForm() {
      return { account_id: null, symbol: '', effective_date: new Date().toISOString().slice(0, 10), action_type: 'cash_dividend', cash_dividend_per_share: 0, split_ratio: 1, note: '' }
    },
    emptyAccountForm() {
      return { id: null, name: '', broker: '', market: 'cn', base_currency: 'CNY' }
    },

    // ---- API helpers ----
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
    async apiUpload(path, formData) {
      const url = `${this.baseUrl}${API_BASE}${path}`
      const res = await fetch(url, { method: 'POST', body: formData })
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

    // ---- Accounts ----
    async loadAccounts() {
      try {
        const data = await this.api('/accounts?include_inactive=true')
        this.accounts = data.accounts || []
      } catch (e) {
        this.showToast('加载账户失败: ' + e.message, 'error')
      }
    },
    async submitAccount() {
      try {
        if (this.accountForm.id) {
          await this.api(`/accounts/${this.accountForm.id}`, { method: 'PUT', body: JSON.stringify(this.accountForm) })
        } else {
          await this.api('/accounts', { method: 'POST', body: JSON.stringify(this.accountForm) })
        }
        this.showAccountForm = false
        this.accountForm = this.emptyAccountForm()
        await this.loadAccounts()
        this.showToast('账户保存成功')
      } catch (e) {
        this.showToast('保存失败: ' + e.message, 'error')
      }
    },
    editAccount(a) {
      this.accountForm = { id: a.id, name: a.name, broker: a.broker || '', market: a.market, base_currency: a.base_currency }
      this.showAccountForm = true
    },
    async deleteAccount(id) {
      if (!confirm('确定要停用此账户吗？')) return
      try {
        await this.api(`/accounts/${id}`, { method: 'DELETE' })
        await this.loadAccounts()
        this.showToast('账户已停用')
      } catch (e) {
        this.showToast('操作失败: ' + e.message, 'error')
      }
    },
    onAccountChange() {
      if (this.activeTab === 'overview') this.loadSnapshot()
      else if (this.activeTab === 'trades') this.loadTrades()
      else if (this.activeTab === 'cash') this.loadCashLedger()
      else if (this.activeTab === 'actions') this.loadCorpActions()
      else if (this.activeTab === 'risk') this.loadRisk()
    },

    // ---- Snapshot ----
    async loadSnapshot() {
      try {
        const params = new URLSearchParams({ cost_method: this.costMethod })
        if (this.selectedAccountId) params.set('account_id', this.selectedAccountId)
        const data = await this.api(`/snapshot?${params}`)
        this.snapshot = data
        // flatten positions from all accounts
        const positions = []
        for (const acct of (data.accounts || [])) {
          for (const pos of (acct.positions || [])) {
            positions.push({ ...pos, _accountName: acct.account_name })
          }
        }
        this.positions = positions
      } catch (e) {
        this.showToast('加载快照失败: ' + e.message, 'error')
      }
    },

    // ---- Trades ----
    async loadTrades() {
      try {
        const params = new URLSearchParams({ page: this.tradePagination.page, page_size: this.tradePagination.page_size })
        if (this.selectedAccountId) params.set('account_id', this.selectedAccountId)
        if (this.tradeFilter.symbol) params.set('symbol', this.tradeFilter.symbol)
        if (this.tradeFilter.side) params.set('side', this.tradeFilter.side)
        if (this.tradeFilter.date_from) params.set('date_from', this.tradeFilter.date_from)
        if (this.tradeFilter.date_to) params.set('date_to', this.tradeFilter.date_to)
        const data = await this.api(`/trades?${params}`)
        this.trades = data.items || []
        this.tradePagination.total = data.total || 0
      } catch (e) {
        this.showToast('加载交易记录失败: ' + e.message, 'error')
      }
    },
    async submitTrade() {
      try {
        const body = { ...this.tradeForm }
        if (!body.account_id) body.account_id = this.accounts[0]?.id
        await this.api('/trades', { method: 'POST', body: JSON.stringify(body) })
        this.showTradeForm = false
        this.tradeForm = this.emptyTradeForm()
        await this.loadTrades()
        this.showToast('交易录入成功')
      } catch (e) {
        this.showToast('录入失败: ' + e.message, 'error')
      }
    },
    async deleteTrade(id) {
      if (!confirm('确定删除此交易记录？')) return
      try {
        await this.api(`/trades/${id}`, { method: 'DELETE' })
        await this.loadTrades()
        this.showToast('已删除')
      } catch (e) {
        this.showToast('删除失败: ' + e.message, 'error')
      }
    },

    // ---- Cash Ledger ----
    async loadCashLedger() {
      try {
        const params = new URLSearchParams({ page: this.cashPagination.page, page_size: this.cashPagination.page_size })
        if (this.selectedAccountId) params.set('account_id', this.selectedAccountId)
        if (this.cashFilter.direction) params.set('direction', this.cashFilter.direction)
        if (this.cashFilter.date_from) params.set('date_from', this.cashFilter.date_from)
        if (this.cashFilter.date_to) params.set('date_to', this.cashFilter.date_to)
        const data = await this.api(`/cash-ledger?${params}`)
        this.cashItems = data.items || []
        this.cashPagination.total = data.total || 0
      } catch (e) {
        this.showToast('加载现金流水失败: ' + e.message, 'error')
      }
    },
    async submitCash() {
      try {
        const body = { ...this.cashForm }
        if (!body.account_id) body.account_id = this.accounts[0]?.id
        await this.api('/cash-ledger', { method: 'POST', body: JSON.stringify(body) })
        this.showCashForm = false
        this.cashForm = this.emptyCashForm()
        await this.loadCashLedger()
        this.showToast('记录成功')
      } catch (e) {
        this.showToast('记录失败: ' + e.message, 'error')
      }
    },
    async deleteCashEntry(id) {
      if (!confirm('确定删除此流水记录？')) return
      try {
        await this.api(`/cash-ledger/${id}`, { method: 'DELETE' })
        await this.loadCashLedger()
        this.showToast('已删除')
      } catch (e) {
        this.showToast('删除失败: ' + e.message, 'error')
      }
    },

    // ---- Corporate Actions ----
    async loadCorpActions() {
      try {
        const params = new URLSearchParams({ page: this.actionPagination.page, page_size: this.actionPagination.page_size })
        if (this.selectedAccountId) params.set('account_id', this.selectedAccountId)
        const data = await this.api(`/corporate-actions?${params}`)
        this.corpActions = data.items || []
        this.actionPagination.total = data.total || 0
      } catch (e) {
        this.showToast('加载公司行动失败: ' + e.message, 'error')
      }
    },
    async submitCorpAction() {
      try {
        const body = { ...this.actionForm }
        if (!body.account_id) body.account_id = this.accounts[0]?.id
        if (body.action_type === 'cash_dividend') delete body.split_ratio
        else delete body.cash_dividend_per_share
        await this.api('/corporate-actions', { method: 'POST', body: JSON.stringify(body) })
        this.showActionForm = false
        this.actionForm = this.emptyActionForm()
        await this.loadCorpActions()
        this.showToast('添加成功')
      } catch (e) {
        this.showToast('添加失败: ' + e.message, 'error')
      }
    },
    async deleteCorpAction(id) {
      if (!confirm('确定删除此公司行动？')) return
      try {
        await this.api(`/corporate-actions/${id}`, { method: 'DELETE' })
        await this.loadCorpActions()
        this.showToast('已删除')
      } catch (e) {
        this.showToast('删除失败: ' + e.message, 'error')
      }
    },

    // ---- Risk ----
    async loadRisk() {
      try {
        const params = new URLSearchParams({ cost_method: this.costMethod })
        if (this.selectedAccountId) params.set('account_id', this.selectedAccountId)
        const data = await this.api(`/risk?${params}`)
        this.risk = data
      } catch (e) {
        this.showToast('加载风险分析失败: ' + e.message, 'error')
      }
    },
    async refreshFx() {
      try {
        const params = new URLSearchParams()
        if (this.selectedAccountId) params.set('account_id', this.selectedAccountId)
        const data = await this.api(`/fx/refresh?${params}`, { method: 'POST' })
        this.showToast(`汇率刷新完成：更新 ${data.updated_count} 对`)
        if (this.activeTab === 'overview') await this.loadSnapshot()
      } catch (e) {
        this.showToast('刷新汇率失败: ' + e.message, 'error')
      }
    },

    // ---- CSV Import ----
    async loadBrokers() {
      try {
        const data = await this.api('/imports/csv/brokers')
        this.brokerList = data.brokers || []
      } catch (e) {
        this.showToast('加载券商列表失败: ' + e.message, 'error')
      }
    },
    triggerFileInput() {
      this.$refs.fileInput.click()
    },
    handleFileSelect(e) {
      this.importFile = e.target.files[0] || null
      this.importPreview = null
      this.importResult = null
    },
    handleFileDrop(e) {
      const file = e.dataTransfer.files[0]
      if (file && file.name.endsWith('.csv')) {
        this.importFile = file
        this.importPreview = null
        this.importResult = null
      }
    },
    async parseCSV() {
      try {
        const fd = new FormData()
        fd.append('broker', this.importBroker)
        fd.append('file', this.importFile)
        this.importPreview = await this.apiUpload('/imports/csv/parse', fd)
      } catch (e) {
        this.showToast('解析失败: ' + e.message, 'error')
      }
    },
    async commitCSV() {
      if (!confirm('确认导入这些交易记录吗？')) return
      try {
        const fd = new FormData()
        fd.append('account_id', this.importAccountId)
        fd.append('broker', this.importBroker)
        fd.append('file', this.importFile)
        this.importResult = await this.apiUpload('/imports/csv/commit', fd)
        this.showToast('导入完成')
      } catch (e) {
        this.showToast('导入失败: ' + e.message, 'error')
      }
    },

    // ---- Formatting ----
    fmtMoney(val) {
      if (val == null) return '-'
      return val.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    },
    fmtPrice(val) {
      if (val == null) return '-'
      return val.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
    },
    fmtPct(pnl, cost) {
      if (!cost || cost === 0) return '-'
      return ((pnl / cost) * 100).toFixed(2) + '%'
    },
    fmtPctVal(val) {
      if (val == null) return '-'
      return (val * 100).toFixed(2) + '%'
    },
    fmtFileSize(bytes) {
      if (bytes < 1024) return bytes + ' B'
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
      return (bytes / 1024 / 1024).toFixed(1) + ' MB'
    },
    formatDate(d) {
      if (!d) return '-'
      return new Date(d).toLocaleDateString('zh-CN')
    },
    pnlClass(val) {
      if (val > 0) return 'positive'
      if (val < 0) return 'negative'
      return ''
    },
    marketLabel(m) {
      return { cn: 'A 股', hk: '港股', us: '美股' }[m] || m || '-'
    },
    actionTypeLabel(t) {
      return { cash_dividend: '现金分红', split_adjustment: '拆股/合股' }[t] || t
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
/* ---- Layout ---- */
.portfolio-app {
  height: 100vh;
  color: #ccc;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 13px;
}

/* ---- Side Panel ---- */
.account-selector-wrap {
  padding: 8px 12px;
  border-bottom: 1px solid var(--panel-border-color, #333);
}
.account-select {
  width: 100%;
  background: #333;
  color: #ccc;
  border: 1px solid #555;
  padding: 5px 8px;
  border-radius: 4px;
  font-size: 12px;
  box-sizing: border-box;
}
.account-select:focus {
  border-color: #0078d4;
  outline: none;
}

.service-status {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  padding: 2px 0;
}
.service-status .status-dot { width: 6px; height: 6px; border-radius: 50%; }
.service-status.online .status-dot { background: #4caf50; }
.service-status.offline .status-dot { background: #f44336; }
.service-status.checking .status-dot { background: #ff9800; }

/* ---- Main ---- */
.main-view-content {
  padding: 16px;
}
.tab-content { animation: fadeIn 0.15s; }
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

/* ---- Cards ---- */
.summary-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}
.card {
  background: #2d2d2d;
  border: 1px solid #3a3a3a;
  border-radius: 6px;
  padding: 14px;
}
.card-label { font-size: 11px; color: #888; margin-bottom: 6px; }
.card-value { font-size: 18px; font-weight: 600; color: #e0e0e0; }

/* ---- Section ---- */
.section { margin-bottom: 24px; }
.section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.section-header h2 { font-size: 15px; font-weight: 600; color: #e0e0e0; margin: 0; }
.section-actions { display: flex; gap: 8px; align-items: center; }

/* ---- Table ---- */
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #333; font-size: 12px; white-space: nowrap; }
th { color: #999; font-weight: 500; background: #252526; position: sticky; top: 0; }
td { color: #ccc; }
.mono { font-family: 'Consolas', 'Courier New', monospace; }
.num { text-align: right; font-family: 'Consolas', monospace; }
tbody tr:hover { background: #2a2d2e; }

.positive { color: #4caf50; }
.negative { color: #f44336; }
.warning { color: #ff9800; }

/* ---- Badges ---- */
.side-badge { padding: 2px 8px; border-radius: 3px; font-size: 11px; }
.side-badge.buy { background: rgba(76,175,80,0.15); color: #4caf50; }
.side-badge.sell { background: rgba(244,67,54,0.15); color: #f44336; }
.side-badge.in { background: rgba(76,175,80,0.15); color: #4caf50; }
.side-badge.out { background: rgba(244,67,54,0.15); color: #f44336; }
.status-tag { padding: 2px 8px; border-radius: 3px; font-size: 11px; background: #444; }
.status-tag.active { background: rgba(76,175,80,0.15); color: #4caf50; }

/* ---- Filter ---- */
.filter-bar { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.filter-input {
  background: #333;
  color: #ccc;
  border: 1px solid #555;
  padding: 5px 10px;
  border-radius: 4px;
  font-size: 12px;
  min-width: 100px;
}
.filter-input:focus { border-color: #0078d4; outline: none; }

/* ---- Buttons ---- */
.btn-primary {
  background: #0078d4;
  color: #fff;
  border: none;
  padding: 6px 16px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}
.btn-primary:hover { background: #1a8ae8; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary {
  background: #3a3a3a;
  color: #ccc;
  border: 1px solid #555;
  padding: 6px 16px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}
.btn-secondary:hover { background: #444; }
.btn-secondary-sm { background: #3a3a3a; color: #ccc; border: 1px solid #555; padding: 3px 10px; border-radius: 3px; cursor: pointer; font-size: 11px; }
.btn-secondary-sm:hover { background: #444; }
.btn-danger-sm { background: transparent; color: #f44336; border: 1px solid #f44336; padding: 3px 10px; border-radius: 3px; cursor: pointer; font-size: 11px; }
.btn-danger-sm:hover { background: rgba(244,67,54,0.1); }
.btn-icon { background: none; border: none; color: #ccc; cursor: pointer; font-size: 16px; padding: 4px; }
.btn-icon:hover { color: #fff; }
.btn-link { background: none; border: none; color: #4fc3f7; cursor: pointer; font-size: 12px; text-decoration: underline; }
.small-select { background: #333; color: #ccc; border: 1px solid #555; padding: 3px 8px; border-radius: 3px; font-size: 11px; }

/* ---- Pagination ---- */
.pagination { display: flex; align-items: center; gap: 12px; justify-content: center; margin-top: 12px; }
.pagination button { background: #3a3a3a; color: #ccc; border: 1px solid #555; padding: 4px 12px; border-radius: 3px; cursor: pointer; font-size: 12px; }
.pagination button:disabled { opacity: 0.4; cursor: not-allowed; }
.pagination span { font-size: 12px; color: #999; }

/* ---- Modal ---- */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal {
  background: #2d2d2d;
  border: 1px solid #444;
  border-radius: 8px;
  width: 420px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
}
.modal-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; border-bottom: 1px solid #3a3a3a; }
.modal-header h3 { margin: 0; font-size: 14px; color: #e0e0e0; }
.modal-body { padding: 16px; overflow-y: auto; flex: 1; }
.modal-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 16px; border-top: 1px solid #3a3a3a; }
.form-row { display: flex; flex-direction: column; gap: 4px; margin-bottom: 12px; }
.form-row label { font-size: 12px; color: #999; }
.form-input {
  background: #1e1e1e;
  color: #ccc;
  border: 1px solid #555;
  padding: 7px 10px;
  border-radius: 4px;
  font-size: 13px;
}
.form-input:focus { border-color: #0078d4; outline: none; }

/* ---- CSV Import ---- */
.import-flow { display: flex; flex-direction: column; gap: 20px; }
.import-step { background: #2d2d2d; border: 1px solid #3a3a3a; border-radius: 6px; padding: 16px; }
.import-step h3 { margin: 0 0 12px 0; font-size: 13px; color: #e0e0e0; }
.file-upload {
  border: 2px dashed #555;
  border-radius: 6px;
  padding: 24px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.15s;
}
.file-upload:hover { border-color: #0078d4; }
.upload-placeholder { color: #888; font-size: 13px; }
.upload-info { color: #ccc; font-size: 13px; }
.import-actions { display: flex; gap: 8px; margin-bottom: 12px; }
.import-preview { margin-top: 12px; }
.import-result { padding: 10px; border-radius: 4px; background: rgba(244,67,54,0.1); border: 1px solid #f44336; margin-top: 12px; }
.import-result.success { background: rgba(76,175,80,0.1); border-color: #4caf50; }
.text-muted { color: #888; font-size: 12px; }

/* ---- Risk ---- */
.risk-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.risk-card { background: #2d2d2d; border: 1px solid #3a3a3a; border-radius: 6px; padding: 16px; }
.risk-card.wide { grid-column: span 2; }
.risk-card h3 { margin: 0 0 12px 0; font-size: 13px; color: #e0e0e0; }
.risk-item { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid #333; }
.risk-val { font-family: 'Consolas', monospace; font-weight: 600; }
.concentration-list { display: flex; flex-direction: column; gap: 8px; }
.concentration-item { display: flex; align-items: center; gap: 10px; }
.bar-wrap { flex: 1; height: 8px; background: #333; border-radius: 4px; overflow: hidden; }
.bar-fill { height: 100%; background: #0078d4; border-radius: 4px; transition: width 0.3s; }

/* ---- Empty ---- */
.empty-state { text-align: center; padding: 40px; color: #666; font-size: 13px; }

/* ---- Toast ---- */
.toast {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  padding: 10px 24px;
  border-radius: 6px;
  font-size: 13px;
  z-index: 2000;
  animation: slideUp 0.2s;
}
.toast.success { background: #2e7d32; color: #fff; }
.toast.error { background: #c62828; color: #fff; }
@keyframes slideUp { from { transform: translateX(-50%) translateY(20px); opacity: 0; } to { transform: translateX(-50%) translateY(0); opacity: 1; } }
</style>
