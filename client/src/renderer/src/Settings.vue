<template>
  <div class="settings-page view-container">
    <!-- 保存提示 -->
    <div class="toast-bar" v-if="toast">
      <div :class="['toast', toast.type]">{{ toast.message }}</div>
    </div>

    <!-- 左侧面板 -->
    <aside class="category-nav side-panel" ref="sidePanelRef">
      <div class="side-panel-resize-handle"></div>
      <div class="side-panel-header">
        <span>系统设置</span>
      </div>
      <div class="side-panel-content">
        <div class="nav-group-label">本地配置</div>
        <template v-for="cat in localCategories" :key="cat.key">
          <div
            :class="['nav-item', { active: activeCategory === cat.key }]"
            @click="activeCategory = cat.key"
          >
            <span class="nav-icon">{{ cat.icon }}</span>
            <div class="nav-text">
              <div class="nav-title">{{ cat.title }}</div>
              <div class="nav-desc">{{ cat.description }}</div>
            </div>
            <span class="nav-badge" v-if="cat.count">{{ cat.count }}</span>
          </div>
        </template>
        <div class="nav-group-label">DSA 后端配置</div>
        <template v-for="cat in dsaCategories" :key="cat.key">
          <div
            :class="['nav-item', { active: activeCategory === cat.key }]"
            @click="activeCategory = cat.key"
          >
            <span class="nav-icon">{{ cat.icon }}</span>
            <div class="nav-text">
              <div class="nav-title">{{ cat.title }}</div>
              <div class="nav-desc">{{ cat.description }}</div>
            </div>
            <span class="nav-badge" v-if="cat.count">{{ cat.count }}</span>
          </div>
        </template>
      </div>
      <!-- 操作按钮 -->
      <div class="side-panel-footer" v-if="activeCategory !== 'local' && activeCategory !== 'server' && activeCategory !== 'dsa_service' && activeCategory !== 'admin'">
        <button class="panel-btn" @click="importConfig" :disabled="!dsaServerRunning || isSaving" title="从 .env 文件导入配置">导入</button>
        <button class="panel-btn" @click="exportConfig" :disabled="!dsaServerRunning || dsaItems.length === 0" title="导出当前配置为 .env 文件">导出</button>
        <button class="panel-btn" @click="resetDraft" :disabled="!hasDirty || isSaving">重置</button>
        <button class="panel-btn btn-primary" @click="saveDsaBackendConfig" :disabled="!hasDirty || isSaving">
          {{ isSaving ? '保存中...' : `保存配置${dirtyCount ? ` (${dirtyCount})` : ''}` }}
        </button>
      </div>
    </aside>

    <!-- 主视图 -->
    <section class="settings-content main-view">
        <!-- 本地设置 -->
        <template v-if="activeCategory === 'local'">
          <div class="section-card">
            <div class="section-title">应用设置</div>
            <div class="section-desc">工作区目录、主题与图表数据源配置。</div>

            <div class="field-item">
              <label>工作区目录</label>
              <div class="field-row">
                <input type="text" :value="localConfig.workspacePath" readonly class="field-input flex-1" />
                <button class="btn btn-browse" @click="browseWorkspace">浏览...</button>
              </div>
              <div class="field-desc">工作区用于存储项目文件和 Python 脚本</div>
            </div>

            <div class="field-item">
              <label>主题</label>
              <select v-model="localConfig.theme" @change="saveLocalSetting('theme', localConfig.theme)" class="field-input">
                <option value="dark">深色</option>
                <option value="light">浅色</option>
                <option value="auto">跟随系统</option>
              </select>
              <div class="field-desc">选择应用程序的主题</div>
            </div>

            <div class="field-item">
              <label>数据源</label>
              <select v-model="localConfig.dataSource" @change="onDataSourceChange" class="field-input">
                <option value="binance">Binance</option>
                <option value="okx">OKX</option>
              </select>
              <div class="field-desc">选择图表数据源，切换数据源将关闭所有已打开的图表页面</div>
            </div>
          </div>

          <div class="section-card">
            <div class="section-title">标签页设置</div>
            <div class="section-desc">标签页行为与限制配置。</div>

            <div class="field-item">
              <label class="checkbox-row">
                <input type="checkbox" v-model="localConfig.closeWarning"
                  @change="saveLocalSetting('close-warning', localConfig.closeWarning)" />
                <span>关闭标签页时显示警告</span>
              </label>
              <div class="field-desc">关闭标签页前显示确认对话框</div>
            </div>

            <div class="field-item">
              <label>最大标签页数量</label>
              <input type="number" v-model.number="localConfig.maxTabs" min="1" max="20"
                @change="saveLocalSetting('max-tabs', localConfig.maxTabs)" class="field-input" />
              <div class="field-desc">允许同时打开的最大标签页数量</div>
            </div>
          </div>

          <div class="section-card">
            <div class="section-title">自定义指标</div>
            <div class="section-desc">外部代码编辑器配置。</div>

            <div class="field-item">
              <label>外部编辑器</label>
              <select v-model="localConfig.externalEditor" @change="saveExternalEditor" class="field-input">
                <option value="auto">自动检测（Cursor → VS Code → 系统默认）</option>
                <option value="vscode">Visual Studio Code</option>
                <option value="cursor">Cursor</option>
                <option value="custom">自定义路径...</option>
              </select>
              <div class="field-desc">指标编辑器中"用外部编辑器打开"时使用的编辑器</div>
            </div>

            <div class="field-item" v-if="localConfig.externalEditor === 'custom'">
              <label>自定义编辑器路径</label>
              <input type="text" v-model="localConfig.externalEditorPath"
                @change="saveExternalEditor"
                placeholder="例如: C:\Program Files\Notepad++\notepad++.exe"
                class="field-input" />
              <div class="field-desc">编辑器可执行文件的完整路径</div>
            </div>
          </div>
        </template>

        <!-- 服务端连接设置 -->
        <template v-if="activeCategory === 'server'">
          <div class="section-card">
            <div class="section-title">服务端连接模式</div>
            <div class="section-desc">选择内置本地后端或连接远程常驻服务端。</div>

            <div class="field-item">
              <label>连接模式</label>
              <select v-model="serverConfig.mode" class="field-input">
                <option value="local">本地内置（自动拉起后端进程）</option>
                <option value="remote">远程服务端（连接 7×24 常驻后端）</option>
              </select>
              <div class="field-desc">本地模式由客户端自动管理后端进程；远程模式连接独立部署的服务端。</div>
            </div>
          </div>

          <div class="section-card" v-if="serverConfig.mode === 'remote'">
            <div class="section-title">远程服务端地址</div>
            <div class="section-desc">填入远程服务端的 HTTP 地址（含端口）。</div>

            <div class="field-item">
              <label>服务端地址</label>
              <div class="field-row">
                <input type="text" v-model="serverConfig.remoteBaseUrl"
                  placeholder="例如 http://192.168.50.7:8100"
                  class="field-input flex-1" />
                <button class="btn btn-browse" @click="testServerConnection" :disabled="serverTesting">
                  {{ serverTesting ? '测试中...' : '测试连接' }}
                </button>
              </div>
              <div class="field-desc" v-if="serverTestResult" :style="{ color: serverTestResult.success ? '#2ea043' : '#da3633' }">
                {{ serverTestResult.message }}
              </div>
              <div class="field-desc" v-else>点击「测试连接」探测服务端 /api/health 是否可达。</div>
            </div>

            <div class="field-item">
              <label>访问令牌（可选）</label>
              <input type="password" v-model="serverConfig.token"
                placeholder="预留，Phase 5 启用"
                class="field-input" />
              <div class="field-desc">远程服务端的访问令牌，当前内网阶段可留空。</div>
            </div>
          </div>

          <div class="section-card" v-if="serverConfig.mode === 'local'">
            <div class="section-title">本地模式</div>
            <div class="section-desc">客户端启动时自动拉起内置后端进程，退出时自动停止。</div>
            <div class="field-item">
              <div class="field-desc">如需修改端口，请在「DSA 服务」页面配置。</div>
            </div>
          </div>

          <div class="section-card">
            <div class="field-item">
              <button class="btn btn-primary" @click="saveServerConfig" :disabled="serverSaving">
                {{ serverSaving ? '保存中...' : '保存并应用' }}
              </button>
              <div class="field-desc" v-if="serverSaved">已保存。切换模式后需重启客户端生效。</div>
            </div>
          </div>

          <div class="section-card" v-if="dsaServerRunning">
            <div class="section-title">客户端账号</div>
            <div class="section-desc">订阅账号登录。启用后需登录才能访问数据接口。</div>

            <div v-if="clientAuthLoading" class="field-item">
              <div class="field-desc">正在检查客户端认证状态...</div>
            </div>

            <template v-else-if="!clientAuthEnabled">
              <div class="field-item">
                <div class="field-desc">客户端认证未启用。在 .env 中设置 <code>CLIENT_AUTH_ENABLED=true</code> 后重启服务即可开启。</div>
              </div>
            </template>

            <template v-else-if="clientAccount">
              <div class="field-item">
                <label>当前账号</label>
                <div class="kv-inline-row"><span class="kv-inline-label">邮箱</span><span class="kv-inline-value">{{ clientAccount.email }}</span></div>
                <div class="kv-inline-row"><span class="kv-inline-label">显示名</span><span class="kv-inline-value">{{ clientAccount.display_name || '-' }}</span></div>
                <div class="kv-inline-row"><span class="kv-inline-label">订阅等级</span><span class="kv-inline-value"><span :class="['tier-badge', tierBadgeClass(clientTier)]">{{ tierBadgeLabel(clientTier) }}</span></span></div>
              </div>
              <div class="field-item" v-if="clientUsage">
                <label>用量统计（近30天）</label>
                <div class="kv-inline-row"><span class="kv-inline-label">总请求</span><span class="kv-inline-value">{{ clientUsage.total_requests ?? 0 }}</span></div>
                <div class="kv-inline-row"><span class="kv-inline-label">今日请求</span><span class="kv-inline-value">{{ clientUsage.today_requests ?? 0 }}</span></div>
                <div class="kv-inline-row"><span class="kv-inline-label">Token 消耗</span><span class="kv-inline-value">{{ clientUsage.total_tokens ?? 0 }}</span></div>
              </div>
              <div class="field-item">
                <button class="btn btn-secondary" @click="clientLogout" :disabled="clientLoggingOut">
                  {{ clientLoggingOut ? '登出中...' : '退出登录' }}
                </button>
              </div>
            </template>

            <template v-else>
              <div class="field-item">
                <label>邮箱</label>
                <input type="email" v-model="clientLoginEmail" class="field-input" placeholder="请输入邮箱" @keyup.enter="clientLogin" />
              </div>
              <div class="field-item">
                <label>密码</label>
                <input type="password" v-model="clientLoginPassword" class="field-input" placeholder="请输入密码" @keyup.enter="clientLogin" />
              </div>
              <div class="field-item">
                <button class="btn btn-primary" @click="clientLogin" :disabled="clientLoggingIn || !clientLoginEmail || !clientLoginPassword">
                  {{ clientLoggingIn ? '登录中...' : '登录' }}
                </button>
                <div class="field-desc" v-if="clientLoginError" style="color:#da3633;">{{ clientLoginError }}</div>
              </div>
            </template>
          </div>
        </template>

        <!-- DSA 服务设置 -->
        <template v-if="activeCategory === 'dsa_service'">
          <div class="section-card">
            <div class="section-title">DSA 服务连接</div>
            <div class="section-desc">后端服务已内置在项目中，使用 uv 自动管理 Python 虚拟环境与依赖。</div>

            <div class="field-item">
              <label>后端路径（内置）</label>
              <div class="field-row">
                <input type="text" :value="dsaLocal.backendPath" readonly class="field-input flex-1" />
              </div>
              <div class="field-desc">内置后端目录，由应用自动管理，无需手动修改</div>
            </div>

            <div class="field-item">
              <label>服务端口</label>
              <input type="number" v-model.number="dsaLocal.port" min="1024" max="65535"
                @change="saveDsaLocal" class="field-input" />
              <div class="field-desc">FastAPI 服务监听端口，默认 8100</div>
            </div>
          </div>

          <div class="section-card">
            <div class="section-title">服务状态</div>
            <div class="section-desc">管理 DSA 后端服务的运行状态。</div>

            <div class="field-item">
              <div class="status-row">
                <span class="status-dot" :style="{ background: statusInfo.color }"></span>
                <span class="status-text">{{ statusInfo.text }}</span>
                <button v-if="statusInfo.showStart" class="btn btn-start" @click="startServer">启动服务</button>
                <button v-if="statusInfo.showStop" class="btn btn-stop" @click="stopServer">停止服务</button>
              </div>
              <div class="field-desc">{{ statusDesc }}</div>
            </div>
          </div>
        </template>

        <!-- 管理面板 -->
        <template v-else-if="activeCategory === 'admin'">
          <AdminPanel />
        </template>

        <!-- DSA 后端配置分类（schema 驱动） -->
        <template v-if="isDsaCategory">
          <div v-if="!dsaServerRunning" class="empty-state">
            <div class="empty-icon">⚙️</div>
            <div class="empty-title">DSA 服务未运行</div>
            <div class="empty-desc">请先在「DSA 服务」页面启动后端服务，然后即可管理此分类的配置项。</div>
          </div>

          <div v-else-if="isLoadingDsa" class="loading-state">
            <div class="spinner"></div>
            <div>正在加载配置...</div>
          </div>

          <div v-else-if="dsaLoadError" class="error-state">
            <div class="error-title">加载失败</div>
            <div class="error-desc">{{ dsaLoadError }}</div>
            <button class="btn btn-primary" @click="loadDsaConfig">重试</button>
          </div>

          <!-- LLM 渠道编辑器 -->
          <div v-else-if="activeCategory === 'ai_model'" class="llm-editor">

            <!-- ① 快速添加渠道 -->
            <div class="llm-group">
              <div class="llm-group-title">快速添加渠道</div>
              <div class="channel-add-bar">
                <select v-model="addPresetKey" class="field-input channel-add-select">
                  <option value="">选择服务商...</option>
                  <option v-for="(p, pk) in channelPresets" :key="pk" :value="pk">{{ p.label }}</option>
                </select>
                <button class="btn btn-primary" @click="addChannelFromPreset" :disabled="!addPresetKey">+ 添加渠道</button>
                <span class="channel-count-badge" v-if="channels.length">{{ enabledChannelCount }}/{{ channels.length }} 已启用</span>
              </div>
            </div>

            <!-- ② 渠道列表 -->
            <div class="llm-group">
              <div class="llm-group-title">渠道列表</div>
              <div class="channels-wrapper" v-if="channels.length">
                <div v-for="(ch, idx) in channels" :key="idx" class="channel-card" :class="{ expanded: expandedChannels[idx] }">
                  <!-- 折叠行 -->
                  <div class="channel-row" @click="toggleChannelExpand(idx)">
                    <span class="channel-expand-arrow" :class="{ open: expandedChannels[idx] }">▶</span>
                    <label class="channel-enable-check" @click.stop>
                      <input type="checkbox" v-model="ch.enabled" @change="markChannelsDirty" />
                    </label>
                    <span class="channel-row-name">{{ ch.name || '未命名渠道' }}</span>
                    <span class="channel-row-badge">{{ protocolLabel(ch.protocol) }}</span>
                    <span class="channel-row-models">{{ channelModelCount(ch) }}个模型</span>
                    <span class="channel-status-dot" :class="channelStatusClass(ch)"></span>
                    <span v-if="!ch.apiKey" class="channel-row-warn">未填 Key</span>
                    <button class="btn btn-icon btn-danger-icon channel-row-delete" @click.stop="removeChannel(idx)" title="删除渠道">✕</button>
                  </div>
                  <!-- 展开区 -->
                  <div v-show="expandedChannels[idx]" class="channel-body">
                    <div class="channel-field">
                      <label>渠道名称</label>
                      <input type="text" v-model="ch.name" class="field-input" placeholder="如 my_deepseek" @change="markChannelsDirty" />
                    </div>
                    <div class="channel-field">
                      <label>协议</label>
                      <select v-model="ch.protocol" class="field-input" @change="markChannelsDirty">
                        <option v-for="po in protocolOptions" :key="po.value" :value="po.value">{{ po.label }}</option>
                      </select>
                    </div>
                    <div class="channel-field">
                      <label>Base URL</label>
                      <input type="text" v-model="ch.baseUrl" class="field-input" placeholder="留空使用默认" @change="markChannelsDirty" />
                    </div>
                    <div class="channel-field">
                      <label>API Key</label>
                      <div class="field-row">
                        <input :type="ch.showKey ? 'text' : 'password'" v-model="ch.apiKey"
                          class="field-input flex-1" placeholder="输入 API Key" @change="markChannelsDirty" />
                        <button class="btn btn-browse" @click="ch.showKey = !ch.showKey">{{ ch.showKey ? '隐藏' : '显示' }}</button>
                      </div>
                    </div>
                    <div class="channel-field">
                      <label>模型列表</label>
                      <input type="text" v-model="ch.models" class="field-input"
                        :placeholder="channelPresets[ch.preset]?.placeholder || 'model-1,model-2'" @change="markChannelsDirty" />
                      <div class="field-desc">逗号分隔的模型名称</div>
                    </div>
                    <div class="channel-actions">
                      <button class="btn btn-secondary" @click="discoverModels(idx)"
                        :disabled="ch.discovering || !ch.apiKey || !ch.name">
                        {{ ch.discovering ? '发现中...' : '获取模型' }}
                      </button>
                      <button class="btn btn-secondary" @click="testChannel(idx)"
                        :disabled="ch.testing || !ch.apiKey || !ch.name">
                        {{ ch.testing ? '测试中...' : '测试连接' }}
                      </button>
                      <span v-if="ch.testResult" :class="['test-result', ch.testResult.ok ? 'success' : 'error']">
                        {{ ch.testResult.message }}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
              <div v-else class="channel-empty-hint">暂无渠道，请在上方选择服务商添加。</div>
            </div>

            <!-- ③ 运行时参数 -->
            <div class="llm-group">
              <div class="llm-group-title">运行时参数</div>
              <div class="runtime-params-list">
                <!-- 分析主模型 -->
                <div class="field-item">
                  <div class="field-label-row"><label>分析主模型</label></div>
                  <select :value="getDraftValue('LITELLM_MODEL')"
                    @change="setDraft('LITELLM_MODEL', $event.target.value)"
                    class="field-input">
                    <option value="">自动（使用第一个可用模型）</option>
                    <option v-for="m in allChannelModels" :key="m.value" :value="m.value">{{ m.label }}</option>
                  </select>
                  <div class="field-desc">分析和对话使用的默认模型。自动模式下按渠道优先级选取第一个可用模型。</div>
                </div>
                <!-- Agent 主模型 -->
                <div class="field-item">
                  <div class="field-label-row"><label>Agent 主模型</label></div>
                  <select :value="getDraftValue('AGENT_LITELLM_MODEL')"
                    @change="setDraft('AGENT_LITELLM_MODEL', $event.target.value)"
                    class="field-input">
                    <option value="">自动（继承分析主模型）</option>
                    <option v-for="m in allChannelModels" :key="m.value" :value="m.value">{{ m.label }}</option>
                  </select>
                  <div class="field-desc">Agent 专用模型。自动模式下直接使用分析主模型。</div>
                </div>
                <!-- 备选模型（多选） -->
                <div class="field-item">
                  <div class="field-label-row"><label>备选模型</label></div>
                  <div class="fallback-model-list" v-if="allChannelModels.length">
                    <label v-for="m in allChannelModels" :key="m.value" class="fallback-model-option">
                      <input type="checkbox"
                        :checked="isFallbackSelected(m.value)"
                        @change="toggleFallbackModel(m.value, $event.target.checked)" />
                      <span>{{ m.label }}</span>
                    </label>
                  </div>
                  <div v-else class="field-desc" style="color:#666;">请先在渠道中配置模型</div>
                  <div class="field-desc">主模型失败时按勾选顺序依次尝试</div>
                </div>
                <!-- Vision 模型 -->
                <div class="field-item">
                  <div class="field-label-row"><label>Vision 模型</label></div>
                  <select :value="getDraftValue('VISION_MODEL')"
                    @change="setDraft('VISION_MODEL', $event.target.value)"
                    class="field-input">
                    <option value="">自动（跟随 Vision 默认逻辑）</option>
                    <option v-for="m in allChannelModels" :key="m.value" :value="m.value">{{ m.label }}</option>
                  </select>
                  <div class="field-desc">图片理解专用模型。自动模式下优先使用分析主模型，再按 Gemini → Anthropic → OpenAI 推断。</div>
                </div>
              </div>
              <!-- Temperature 滑动条 -->
              <div class="field-item temperature-field">
                <div class="field-label-row">
                  <label>Temperature</label>
                  <span class="temperature-value">{{ temperatureDisplay }}</span>
                </div>
                <input type="range" min="0" max="2" step="0.1"
                  :value="getDraftValue('LLM_TEMPERATURE') || '0.7'"
                  @input="setDraft('LLM_TEMPERATURE', $event.target.value)"
                  class="temperature-slider" />
                <div class="temperature-labels">
                  <span>精确 (0)</span>
                  <span>平衡 (1)</span>
                  <span>创意 (2)</span>
                </div>
              </div>
            </div>

            <!-- ④ 高级路由配置 -->
            <div class="llm-group">
              <div class="llm-group-title">高级路由配置</div>
              <div class="field-item">
                <div class="field-label-row"><label>高级模型路由 YAML 配置文件路径</label></div>
                <input type="text" :value="getDraftValue('LITELLM_CONFIG')"
                  @input="setDraft('LITELLM_CONFIG', $event.target.value)"
                  class="field-input" placeholder="如 /path/to/litellm_config.yaml" />
                <div class="field-desc">指定 LiteLLM 路由配置文件。配置此项后将使用高级路由模式。</div>
              </div>
            </div>

            <!-- 保存按钮 -->
            <div class="channel-save-row" v-if="channelsDirty">
              <button class="btn btn-primary" @click="saveChannels" :disabled="isSavingChannels">
                {{ isSavingChannels ? '保存中...' : '保存 AI 配置' }}
              </button>
            </div>
          </div>

          <!-- 数据源渠道编辑器 -->
          <div v-else-if="activeCategory === 'data_source' && dsaServerRunning && !isLoadingDsa && !dsaLoadError" class="ds-editor">

            <!-- ① 行情数据源渠道 -->
            <div class="llm-group">
              <div class="llm-group-title">行情数据源渠道</div>
              <div class="channel-add-bar">
                <select v-model="dsAddPresetKey" class="field-input channel-add-select">
                  <option value="">选择数据源...</option>
                  <option v-for="(p, pk) in availableDsPresets" :key="pk" :value="pk">{{ p.label }}</option>
                </select>
                <button class="btn btn-primary" @click="addDsChannel" :disabled="!dsAddPresetKey">+ 添加渠道</button>
                <span class="channel-count-badge" v-if="dsChannels.length">{{ enabledDsCount }}/{{ dsChannels.length }} 已启用</span>
              </div>

              <!-- 渠道列表 -->
              <div class="channels-wrapper" ref="dsListRef" v-if="dsChannels.length">
                <div v-for="(ch, idx) in dsChannels" :key="ch.id" class="channel-card" :class="{ expanded: dsExpanded[idx] }" :data-id="ch.id">
                  <div class="channel-row">
                    <span class="drag-handle" title="拖拽排序">⠿</span>
                    <label class="channel-enable-check" @click.stop>
                      <input type="checkbox" v-model="ch.enabled" @change="dsChannelsDirty = true" />
                    </label>
                    <span class="channel-row-name">{{ getDsLabel(ch.preset) }}</span>
                    <span class="channel-row-badge" :class="dsAuthBadgeClass(ch)">{{ dsAuthBadgeText(ch) }}</span>
                    <span class="channel-expand-arrow" :class="{ open: dsExpanded[idx] }" @click="dsExpanded[idx] = !dsExpanded[idx]">▶</span>
                    <button class="btn btn-icon btn-danger-icon channel-row-delete" @click.stop="removeDsChannel(idx)" title="删除渠道">✕</button>
                  </div>
                  <div v-show="dsExpanded[idx]" class="channel-body">
                    <div class="channel-field" v-if="ch.authType === 'apiKey'">
                      <label>API Key</label>
                      <div class="field-row">
                        <input :type="ch.showKey ? 'text' : 'password'" v-model="ch.credentials.apiKey" class="field-input flex-1" placeholder="输入 API Key" @input="dsChannelsDirty = true" />
                        <button class="btn btn-browse" @click="ch.showKey = !ch.showKey">{{ ch.showKey ? '隐藏' : '显示' }}</button>
                      </div>
                    </div>
                    <div class="channel-field" v-if="ch.authType === 'token'">
                      <label>Token</label>
                      <div class="field-row">
                        <input :type="ch.showKey ? 'text' : 'password'" v-model="ch.credentials.token" class="field-input flex-1" placeholder="输入 Token" @input="dsChannelsDirty = true" />
                        <button class="btn btn-browse" @click="ch.showKey = !ch.showKey">{{ ch.showKey ? '隐藏' : '显示' }}</button>
                      </div>
                    </div>
                    <template v-if="ch.authType === 'server'">
                      <div class="channel-field">
                        <label>服务器地址</label>
                        <input type="text" v-model="ch.credentials.host" class="field-input" placeholder="如 127.0.0.1" @input="dsChannelsDirty = true" />
                      </div>
                      <div class="channel-field">
                        <label>端口</label>
                        <input type="number" v-model="ch.credentials.port" class="field-input" placeholder="7709" @input="dsChannelsDirty = true" />
                      </div>
                      <div class="channel-field">
                        <label>服务器列表</label>
                        <input type="text" v-model="ch.credentials.servers" class="field-input" placeholder="逗号分隔多个服务器" @input="dsChannelsDirty = true" />
                      </div>
                    </template>
                    <template v-if="ch.authType === 'multi'">
                      <div class="channel-field" v-for="(fieldKey, fIdx) in getDsPresetFields(ch.preset)" :key="fieldKey">
                        <label>{{ getDsPresetFieldLabel(ch.preset, fIdx) }}</label>
                        <div class="field-row">
                          <input :type="(fIdx === 0 && ch.showKey) ? 'text' : 'password'" v-model="ch.credentials[fieldKey]" class="field-input flex-1" :placeholder="getDsPresetFieldLabel(ch.preset, fIdx)" @input="dsChannelsDirty = true" />
                          <button v-if="fIdx === 0" class="btn btn-browse" @click="ch.showKey = !ch.showKey">{{ ch.showKey ? '隐藏' : '显示' }}</button>
                        </div>
                      </div>
                      <div v-if="getDsPresetOptional(ch.preset)" class="field-desc" style="padding: 4px 0; color: var(--color-text-muted);">💡 公开市场数据无需 API Key，但有速率限制。配置后可提升请求配额。</div>
                    </template>
                    <div v-if="ch.authType === 'none'" class="field-desc" style="padding: 4px 0;">此数据源无需配置凭证，开箱即用。</div>
                  </div>
                </div>
              </div>
              <div v-else class="channel-empty-hint">暂无数据源渠道，请在上方选择数据源添加。</div>

              <!-- 开关 -->
              <div class="ds-switches">
                <label class="checkbox-row">
                  <input type="checkbox" :checked="getDraftValue('ENABLE_REALTIME_TECHNICAL_INDICATORS') === 'true'" @change="setDraft('ENABLE_REALTIME_TECHNICAL_INDICATORS', $event.target.checked ? 'true' : 'false')" />
                  <span>盘中实时技术面</span>
                </label>
                <label class="checkbox-row">
                  <input type="checkbox" :checked="getDraftValue('ENABLE_REALTIME_QUOTE') === 'true'" @change="setDraft('ENABLE_REALTIME_QUOTE', $event.target.checked ? 'true' : 'false')" />
                  <span>实时行情</span>
                </label>
                <label class="checkbox-row">
                  <input type="checkbox" :checked="getDraftValue('ENABLE_CHIP_DISTRIBUTION') === 'true'" @change="setDraft('ENABLE_CHIP_DISTRIBUTION', $event.target.checked ? 'true' : 'false')" />
                  <span>筹码分布</span>
                </label>
              </div>
            </div>

            <!-- ①-b 本地缓存管理 -->
            <div class="llm-group">
              <div class="llm-group-title">💾 本地缓存管理</div>
              <CacheTimeline :baseUrl="baseUrl" />
            </div>

            <!-- ② 新闻搜索源渠道 -->
            <div class="llm-group">
              <div class="llm-group-title">新闻搜索源渠道</div>
              <div class="channel-add-bar">
                <select v-model="nsAddPresetKey" class="field-input channel-add-select">
                  <option value="">选择搜索源...</option>
                  <option v-for="(p, pk) in availableNsPresets" :key="pk" :value="pk">{{ p.label }}</option>
                </select>
                <button class="btn btn-primary" @click="addNsChannel" :disabled="!nsAddPresetKey">+ 添加渠道</button>
                <span class="channel-count-badge" v-if="nsChannels.length">{{ enabledNsCount }}/{{ nsChannels.length }} 已启用</span>
              </div>

              <!-- 渠道列表 -->
              <div class="channels-wrapper" ref="nsListRef" v-if="nsChannels.length">
                <div v-for="(ch, idx) in nsChannels" :key="ch.id" class="channel-card" :class="{ expanded: nsExpanded[idx] }" :data-id="ch.id">
                  <div class="channel-row">
                    <span class="drag-handle" title="拖拽排序">⠿</span>
                    <label class="channel-enable-check" @click.stop>
                      <input type="checkbox" v-model="ch.enabled" @change="nsChannelsDirty = true" />
                    </label>
                    <span class="channel-row-name">{{ getNsLabel(ch.preset) }}</span>
                    <span class="channel-row-badge" :class="nsAuthBadgeClass(ch)">{{ nsAuthBadgeText(ch) }}</span>
                    <span class="channel-expand-arrow" :class="{ open: nsExpanded[idx] }" @click="nsExpanded[idx] = !nsExpanded[idx]">▶</span>
                    <button class="btn btn-icon btn-danger-icon channel-row-delete" @click.stop="removeNsChannel(idx)" title="删除渠道">✕</button>
                  </div>
                  <div v-show="nsExpanded[idx]" class="channel-body">
                    <div class="channel-field" v-if="ch.authType === 'apiKey'">
                      <label>API Keys</label>
                      <div class="field-row">
                        <input :type="ch.showKey ? 'text' : 'password'" v-model="ch.credentials.apiKeys" class="field-input flex-1" placeholder="逗号分隔多个 Key" @input="nsChannelsDirty = true" />
                        <button class="btn btn-browse" @click="ch.showKey = !ch.showKey">{{ ch.showKey ? '隐藏' : '显示' }}</button>
                      </div>
                      <div class="field-desc">支持逗号分隔多个 Key，自动轮换。</div>
                    </div>
                    <div class="channel-field" v-if="ch.authType === 'url'">
                      <label>Base URLs</label>
                      <input type="text" v-model="ch.credentials.baseUrls" class="field-input" placeholder="逗号分隔 SearXNG 实例地址" @input="nsChannelsDirty = true" />
                      <div class="field-desc">多个实例地址用逗号分隔。</div>
                    </div>
                    <div v-if="ch.authType === 'none'" class="field-desc" style="padding: 4px 0;">此搜索源无需配置，自动从 searx.space 发现公共实例。</div>
                  </div>
                </div>
              </div>
              <div v-else class="channel-empty-hint">暂无搜索源渠道，请在上方选择搜索源添加。</div>

              <!-- 参数 -->
              <div class="ds-params">
                <div class="channel-field">
                  <label>最大时效（天）</label>
                  <input type="number" :value="getDraftValue('NEWS_MAX_AGE_DAYS')" @input="setDraft('NEWS_MAX_AGE_DAYS', $event.target.value)" class="field-input" style="width:120px" min="1" />
                </div>
                <div class="channel-field">
                  <label>策略窗口档位</label>
                  <select :value="getDraftValue('NEWS_STRATEGY_PROFILE')" @change="setDraft('NEWS_STRATEGY_PROFILE', $event.target.value)" class="field-input" style="width:160px">
                    <option value="ultra_short">超短线 (1天)</option>
                    <option value="short">短线 (3天)</option>
                    <option value="medium">中线 (7天)</option>
                    <option value="long">长线 (30天)</option>
                  </select>
                </div>
                <div class="channel-field">
                  <label>偏离阈值 (%)</label>
                  <input type="number" :value="getDraftValue('BIAS_THRESHOLD')" @input="setDraft('BIAS_THRESHOLD', $event.target.value)" class="field-input" style="width:120px" min="0" step="0.5" />
                </div>
              </div>
            </div>

            <!-- ③ 高级参数（基本面管线等，保留分组渲染） -->
            <div class="llm-group" v-if="dsAdvancedItems.length">
              <div class="llm-group-title">高级参数</div>
              <div class="settings-group-body">
                <div v-for="item in dsAdvancedItems" :key="item.key" class="field-item">
                  <div class="field-label-row">
                    <label>{{ getFieldTitle(item.key, item.schema?.title) }}</label>
                  </div>
                  <label v-if="item.schema?.uiControl === 'switch'" class="checkbox-row">
                    <input type="checkbox" :checked="getDraftValue(item.key) === 'true'" @change="setDraft(item.key, $event.target.checked ? 'true' : 'false')" />
                    <span>{{ getDraftValue(item.key) === 'true' ? '已启用' : '已禁用' }}</span>
                  </label>
                  <input v-else-if="item.schema?.uiControl === 'number'" type="number" :value="getDraftValue(item.key)" @input="setDraft(item.key, $event.target.value)" class="field-input" :min="item.schema?.validation?.min" :max="item.schema?.validation?.max" />
                  <input v-else type="text" :value="getDraftValue(item.key)" @input="setDraft(item.key, $event.target.value)" class="field-input" :placeholder="item.schema?.defaultValue || ''" />
                  <div class="field-desc">{{ getFieldDesc(item.key, item.schema?.description) }}</div>
                </div>
              </div>
            </div>

            <!-- 保存按钮 -->
            <div class="channel-save-row" v-if="dsChannelsDirty || nsChannelsDirty">
              <button class="btn btn-primary" @click="saveDsNsChannels" :disabled="isSavingDsChannels || isSavingNsChannels">
                {{ (isSavingDsChannels || isSavingNsChannels) ? '保存中...' : '保存数据源配置' }}
              </button>
            </div>
          </div>

          <!-- 通用 schema 字段列表（ai_model / data_source 已由专用编辑器处理） -->
          <div v-if="dsaServerRunning && !isLoadingDsa && !dsaLoadError && filteredActiveItems.length && activeCategory !== 'ai_model' && activeCategory !== 'data_source'" class="section-card">
            <div class="section-title">{{ currentCategoryTitle }}</div>
            <div class="section-desc">{{ currentCategoryDesc }}</div>

            <!-- 分组渲染模式 -->
            <template v-if="groupedActiveItems.length">
              <div v-for="group in groupedActiveItems" :key="group.key" class="settings-group">
                <div class="settings-group-title">{{ group.title }}</div>
                <div class="settings-group-desc" v-if="group.desc">{{ group.desc }}</div>
                <div class="settings-group-body">
                  <template v-for="item in group.items" :key="item.key">
                    <div class="field-item">
                      <div class="field-label-row">
                        <label>{{ getFieldTitle(item.key, item.schema?.title) }}</label>
                        <span v-if="item.schema?.isSensitive" class="badge sensitive">敏感</span>
                        <span v-if="item.schema && !item.schema.isEditable" class="badge readonly">只读</span>
                      </div>
                      <label v-if="item.schema?.uiControl === 'switch'" class="checkbox-row">
                        <input type="checkbox" :checked="getDraftValue(item.key) === 'true'"
                          @change="setDraft(item.key, $event.target.checked ? 'true' : 'false')"
                          :disabled="item.schema && !item.schema.isEditable" />
                        <span>{{ getDraftValue(item.key) === 'true' ? '已启用' : '已禁用' }}</span>
                      </label>
                      <select v-else-if="item.schema?.uiControl === 'select'"
                        :value="getDraftValue(item.key)" @change="setDraft(item.key, $event.target.value)"
                        class="field-input" :disabled="item.schema && !item.schema.isEditable">
                        <option value="">-- 请选择 --</option>
                        <option v-for="opt in normalizeOptions(item.schema?.options)" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                      </select>
                      <textarea v-else-if="item.schema?.uiControl === 'textarea'"
                        :value="getDraftValue(item.key)" @input="setDraft(item.key, $event.target.value)"
                        class="field-input field-textarea" :disabled="item.schema && !item.schema.isEditable" rows="3"></textarea>
                      <div v-else-if="item.schema?.uiControl === 'password'" class="field-row">
                        <input :type="passwordVisibility[item.key] ? 'text' : 'password'"
                          :value="getDraftValue(item.key)" @input="setDraft(item.key, $event.target.value)"
                          class="field-input flex-1" :placeholder="item.schema?.defaultValue || ''"
                          :disabled="item.schema && !item.schema.isEditable" />
                        <button class="btn btn-browse" @click="togglePasswordVisibility(item.key)">{{ passwordVisibility[item.key] ? '隐藏' : '显示' }}</button>
                      </div>
                      <input v-else-if="item.schema?.uiControl === 'number'" type="number"
                        :value="getDraftValue(item.key)" @input="setDraft(item.key, $event.target.value)"
                        class="field-input" :min="item.schema?.validation?.min" :max="item.schema?.validation?.max"
                        :step="item.schema?.dataType === 'number' ? 0.1 : 1" :disabled="item.schema && !item.schema.isEditable" />
                      <input v-else-if="item.schema?.uiControl === 'time'" type="time"
                        :value="getDraftValue(item.key)" @input="setDraft(item.key, $event.target.value)"
                        class="field-input" :disabled="item.schema && !item.schema.isEditable" />
                      <input v-else type="text"
                        :value="getDraftValue(item.key)" @input="setDraft(item.key, $event.target.value)"
                        class="field-input" :placeholder="item.schema?.defaultValue || ''"
                        :disabled="item.schema && !item.schema.isEditable" />
                      <div class="field-desc">{{ getFieldDesc(item.key, item.schema?.description) }}</div>
                    </div>
                  </template>
                </div>
              </div>
            </template>

            <!-- 无分组的平铺渲染 -->
            <template v-else>
              <div v-for="item in filteredActiveItems" :key="item.key" class="field-item">
                <div class="field-label-row">
                  <label>{{ getFieldTitle(item.key, item.schema?.title) }}</label>
                  <span v-if="item.schema?.isSensitive" class="badge sensitive">敏感</span>
                  <span v-if="item.schema && !item.schema.isEditable" class="badge readonly">只读</span>
                </div>
                <label v-if="item.schema?.uiControl === 'switch'" class="checkbox-row">
                  <input type="checkbox" :checked="getDraftValue(item.key) === 'true'"
                    @change="setDraft(item.key, $event.target.checked ? 'true' : 'false')"
                    :disabled="item.schema && !item.schema.isEditable" />
                  <span>{{ getDraftValue(item.key) === 'true' ? '已启用' : '已禁用' }}</span>
                </label>
                <select v-else-if="item.schema?.uiControl === 'select'"
                  :value="getDraftValue(item.key)" @change="setDraft(item.key, $event.target.value)"
                  class="field-input" :disabled="item.schema && !item.schema.isEditable">
                  <option value="">-- 请选择 --</option>
                  <option v-for="opt in normalizeOptions(item.schema?.options)" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                </select>
                <textarea v-else-if="item.schema?.uiControl === 'textarea'"
                  :value="getDraftValue(item.key)" @input="setDraft(item.key, $event.target.value)"
                  class="field-input field-textarea" :disabled="item.schema && !item.schema.isEditable" rows="3"></textarea>
                <div v-else-if="item.schema?.uiControl === 'password'" class="field-row">
                  <input :type="passwordVisibility[item.key] ? 'text' : 'password'"
                    :value="getDraftValue(item.key)" @input="setDraft(item.key, $event.target.value)"
                    class="field-input flex-1" :placeholder="item.schema?.defaultValue || ''"
                    :disabled="item.schema && !item.schema.isEditable" />
                  <button class="btn btn-browse" @click="togglePasswordVisibility(item.key)">{{ passwordVisibility[item.key] ? '隐藏' : '显示' }}</button>
                </div>
                <input v-else-if="item.schema?.uiControl === 'number'" type="number"
                  :value="getDraftValue(item.key)" @input="setDraft(item.key, $event.target.value)"
                  class="field-input" :min="item.schema?.validation?.min" :max="item.schema?.validation?.max"
                  :step="item.schema?.dataType === 'number' ? 0.1 : 1" :disabled="item.schema && !item.schema.isEditable" />
                <input v-else-if="item.schema?.uiControl === 'time'" type="time"
                  :value="getDraftValue(item.key)" @input="setDraft(item.key, $event.target.value)"
                  class="field-input" :disabled="item.schema && !item.schema.isEditable" />
                <input v-else type="text"
                  :value="getDraftValue(item.key)" @input="setDraft(item.key, $event.target.value)"
                  class="field-input" :placeholder="item.schema?.defaultValue || ''"
                  :disabled="item.schema && !item.schema.isEditable" />
                <div class="field-desc">{{ getFieldDesc(item.key, item.schema?.description) }}</div>
              </div>
            </template>
          </div>

          <div v-else-if="dsaServerRunning && !isLoadingDsa && !dsaLoadError && filteredActiveItems.length === 0 && activeCategory !== 'ai_model' && activeCategory !== 'data_source'" class="empty-state">
            <div class="empty-title">当前分类下暂无配置项</div>
            <div class="empty-desc">可切换左侧分类继续查看其它系统配置。</div>
          </div>
        </template>
      </section>

    <!-- 确认对话框 -->
    <div v-if="confirmDialog.show" class="dialog-overlay" @click.self="confirmDialog.onCancel">
      <div class="dialog-box">
        <h3>{{ confirmDialog.title }}</h3>
        <p>{{ confirmDialog.message }}</p>
        <div class="dialog-actions">
          <button class="btn btn-secondary" @click="confirmDialog.onCancel">{{ confirmDialog.cancelText }}</button>
          <button class="btn btn-primary" @click="confirmDialog.onConfirm">{{ confirmDialog.confirmText }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import Sortable from 'sortablejs'
import '@renderer/styles/layout.css'
import { useSidePanelWidth } from './composables/useSidePanelWidth'
import CacheTimeline from './components/cache-timeline/CacheTimeline.vue'
import { getApiBase } from './service/serverConfig'
import AdminPanel from './components/AdminPanel.vue'

const sidePanelRef = ref(null)
useSidePanelWidth(sidePanelRef)

// =============================
// i18n 翻译
// =============================
const categoryTitleMap = {
  base: '基础设置',
  data_source: '数据源',
  ai_model: 'AI 模型',
  notification: '通知渠道',
  system: '系统设置',
  agent: 'Agent 设置',
  backtest: '回测配置',
  uncategorized: '其他',
}
const categoryDescMap = {
  base: '管理自选股与基础运行参数。',
  data_source: '管理行情数据源与优先级策略。',
  ai_model: '管理模型供应商、模型名称与推理参数。',
  notification: '管理机器人、Webhook 和消息推送配置。',
  system: '管理调度、日志、端口等系统级参数。',
  agent: '管理 Agent 模式、策略与多 Agent 编排配置。',
  backtest: '管理回测开关、评估窗口和引擎参数。',
  uncategorized: '其他未归类的配置项。',
}
const fieldTitleMap = {
  STOCK_LIST: '自选股列表',
  TUSHARE_TOKEN: 'Tushare Token',
  TICKFLOW_API_KEY: 'TickFlow API Key',
  BOCHA_API_KEYS: 'Bocha API Keys',
  TAVILY_API_KEYS: 'Tavily API Keys',
  ANSPIRE_API_KEYS: 'Anspire API Keys',
  SERPAPI_API_KEYS: 'SerpAPI API Keys',
  BRAVE_API_KEYS: 'Brave API Keys',
  SEARXNG_BASE_URLS: 'SearXNG Base URLs',
  SEARXNG_PUBLIC_INSTANCES_ENABLED: 'SearXNG 公共实例自动发现',
  MINIMAX_API_KEYS: 'MiniMax API Keys',
  NEWS_STRATEGY_PROFILE: '新闻策略窗口档位',
  NEWS_MAX_AGE_DAYS: '新闻最大时效（天）',
  REALTIME_SOURCE_PRIORITY: '实时数据源优先级',
  ENABLE_REALTIME_TECHNICAL_INDICATORS: '盘中实时技术面',
  ENABLE_REALTIME_QUOTE: '启用实时行情',
  ENABLE_CHIP_DISTRIBUTION: '启用筹码分布',
  BIAS_THRESHOLD: '偏离阈值 (%)',
  PYTDX_HOST: 'Pytdx 服务器',
  PYTDX_PORT: 'Pytdx 端口',
  PYTDX_SERVERS: 'Pytdx 服务器列表',
  LITELLM_MODEL: '主模型',
  AGENT_LITELLM_MODEL: 'Agent 主模型',
  LITELLM_FALLBACK_MODELS: '备选模型',
  LITELLM_CONFIG: '高级模型路由配置',
  LLM_CHANNELS: 'LLM 渠道列表',
  LLM_TEMPERATURE: '采样温度',
  AIHUBMIX_KEY: 'AIHubmix Key',
  DEEPSEEK_API_KEY: 'DeepSeek API Key',
  DEEPSEEK_API_KEYS: 'DeepSeek API Keys (Multi)',
  GEMINI_API_KEY: 'Gemini API Key',
  GEMINI_API_KEYS: 'Gemini API Keys (Multi)',
  GEMINI_MODEL: 'Gemini 模型',
  GEMINI_MODEL_FALLBACK: 'Gemini 备选模型',
  GEMINI_TEMPERATURE: 'Gemini 温度参数',
  ANTHROPIC_API_KEY: 'Anthropic API Key',
  ANTHROPIC_API_KEYS: 'Anthropic API Keys (Multi)',
  ANTHROPIC_MODEL: 'Anthropic 模型',
  ANTHROPIC_TEMPERATURE: 'Anthropic 温度',
  ANTHROPIC_MAX_TOKENS: 'Anthropic Max Tokens',
  OPENAI_API_KEY: 'OpenAI API Key',
  OPENAI_API_KEYS: 'OpenAI API Keys (Multi)',
  OPENAI_BASE_URL: 'OpenAI Base URL',
  OPENAI_MODEL: 'OpenAI 模型',
  OPENAI_VISION_MODEL: 'OpenAI 视觉模型',
  OPENAI_TEMPERATURE: 'OpenAI 温度',
  VISION_MODEL: '视觉模型',
  WECHAT_WEBHOOK_URL: '企业微信 Webhook',
  FEISHU_WEBHOOK_URL: '飞书群机器人 Webhook',
  FEISHU_WEBHOOK_SECRET: '飞书 Webhook 签名密钥',
  FEISHU_WEBHOOK_KEYWORD: '飞书 Webhook 关键词',
  FEISHU_APP_ID: '飞书应用 App ID',
  FEISHU_APP_SECRET: '飞书应用 App Secret',
  DINGTALK_APP_KEY: '钉钉 App Key',
  DINGTALK_APP_SECRET: '钉钉 App Secret',
  PUSHPLUS_TOKEN: 'PushPlus Token',
  REPORT_SUMMARY_ONLY: '仅分析结果摘要',
  MAX_WORKERS: '最大并发线程数',
  SCHEDULE_TIME: '定时任务时间',
  HTTP_PROXY: 'HTTP 代理',
  LOG_LEVEL: '日志级别',
  WEBUI_PORT: 'WebUI 端口',
  ADMIN_AUTH_ENABLED: '启用管理认证',
  AGENT_MODE: '启用 Agent 策略问股',
  AGENT_MAX_STEPS: 'Agent 最大步数',
  AGENT_SKILLS: 'Agent 激活策略',
  AGENT_SKILL_DIR: 'Agent 策略目录',
  AGENT_ARCH: 'Agent 架构模式',
  AGENT_ORCHESTRATOR_MODE: '编排模式',
  AGENT_ORCHESTRATOR_TIMEOUT_S: 'Agent 超时（秒）',
  AGENT_RISK_OVERRIDE: '风控 Agent 否决',
  AGENT_SKILL_AUTOWEIGHT: '策略自动加权',
  AGENT_SKILL_ROUTING: '策略路由模式',
  AGENT_MEMORY_ENABLED: '记忆与校准',
  AGENT_PARALLEL_PIPELINE: '并行管线',
  AGENT_DEBATE_ENABLED: '多空辩论',
  AGENT_DEBATE_ROUNDS: '辩论轮数',
  AGENT_RISK_DEBATE_ENABLED: '多视角风险讨论',
  AGENT_REFLECTION_ENABLED: '反思机制',
  AGENT_REFLECTION_LOOKBACK_DAYS: '反思回溯天数',
  AGENT_DEEP_THINK_MODEL: '深度推理模型',
  AGENT_QUICK_THINK_MODEL: '快速推理模型',
  AGENT_MODEL_ASSIGNMENT: 'Agent 模型分配',
  BACKTEST_ENABLED: '启用回测',
  BACKTEST_EVAL_WINDOW_DAYS: '回测评估窗口（交易日）',
  BACKTEST_MIN_AGE_DAYS: '回测最小历史天数',
  BACKTEST_ENGINE_VERSION: '回测引擎版本',
  BACKTEST_NEUTRAL_BAND_PCT: '回测中性区间阈值（%）',
  // 报告配置
  REPORT_TYPE: '报告类型',
  REPORT_LANGUAGE: '报告语言',
  REPORT_TEMPLATES_DIR: '报告模板目录',
  REPORT_RENDERER_ENABLED: '启用报告渲染',
  REPORT_INTEGRITY_ENABLED: '报告完整性校验',
  REPORT_INTEGRITY_RETRY: '完整性校验重试次数',
  REPORT_HISTORY_COMPARE_N: '历史对比报告数',
  // Telegram
  TELEGRAM_BOT_TOKEN: 'Telegram Bot Token',
  TELEGRAM_CHAT_ID: 'Telegram Chat ID',
  TELEGRAM_MESSAGE_THREAD_ID: 'Telegram 消息线程 ID',
  TELEGRAM_WEBHOOK_SECRET: 'Telegram Webhook Secret',
  // Email
  EMAIL_SENDER: '发件人邮箱',
  EMAIL_SENDER_NAME: '发件人名称',
  EMAIL_PASSWORD: '邮箱密码/授权码',
  EMAIL_RECEIVERS: '收件人列表',
  // Discord
  DISCORD_BOT_TOKEN: 'Discord Bot Token',
  DISCORD_BOT_STATUS: 'Discord Bot 状态',
  DISCORD_MAIN_CHANNEL_ID: 'Discord 主频道 ID',
  DISCORD_WEBHOOK_URL: 'Discord Webhook URL',
  DISCORD_INTERACTIONS_PUBLIC_KEY: 'Discord 交互公钥',
  // Slack
  SLACK_WEBHOOK_URL: 'Slack Webhook URL',
  SLACK_BOT_TOKEN: 'Slack Bot Token',
  SLACK_CHANNEL_ID: 'Slack 频道 ID',
  // 飞书扩展
  FEISHU_VERIFICATION_TOKEN: '飞书验证 Token',
  FEISHU_ENCRYPT_KEY: '飞书加密密钥',
  FEISHU_STREAM_ENABLED: '飞书事件流模式',
  FEISHU_FOLDER_TOKEN: '飞书文档目录 Token',
  FEISHU_MAX_BYTES: '飞书消息最大字节',
  // 钉钉扩展
  DINGTALK_STREAM_ENABLED: '钉钉事件流模式',
  // 企业微信扩展
  WECOM_CORPID: '企业微信 Corp ID',
  WECOM_TOKEN: '企业微信 Token',
  WECOM_ENCODING_AES_KEY: '企业微信加密密钥',
  WECOM_AGENT_ID: '企业微信 Agent ID',
  WECHAT_MAX_BYTES: '微信消息最大字节',
  WECHAT_MSG_TYPE: '微信消息类型',
  // PushPlus / PushOver / ServerChan
  PUSHPLUS_TOPIC: 'PushPlus 话题',
  PUSHOVER_USER_KEY: 'Pushover User Key',
  PUSHOVER_API_TOKEN: 'Pushover API Token',
  SERVERCHAN3_SENDKEY: 'Server酱 SendKey',
  // 自定义 Webhook
  CUSTOM_WEBHOOK_URLS: '自定义 Webhook URLs',
  CUSTOM_WEBHOOK_BEARER_TOKEN: 'Webhook Bearer Token',
  WEBHOOK_VERIFY_SSL: 'Webhook 验证 SSL',
  // AstrBot
  ASTRBOT_TOKEN: 'AstrBot Token',
  ASTRBOT_URL: 'AstrBot URL',
  // 通知行为
  SINGLE_STOCK_NOTIFY: '单股通知模式',
  ANALYSIS_DELAY: '分析延迟（秒）',
  MERGE_EMAIL_NOTIFICATION: '合并邮件通知',
  MARKDOWN_TO_IMAGE_CHANNELS: 'MD 转图渠道',
  MARKDOWN_TO_IMAGE_MAX_CHARS: 'MD 转图最大字符数',
  MD2IMG_ENGINE: 'MD 转图引擎',
  DISCORD_MAX_WORDS: 'Discord 最大字数',
  // Longbridge 数据源
  LONGBRIDGE_APP_KEY: 'Longbridge App Key',
  LONGBRIDGE_APP_SECRET: 'Longbridge App Secret',
  LONGBRIDGE_ACCESS_TOKEN: 'Longbridge Access Token',
  // 实时数据扩展
  ENABLE_EASTMONEY_PATCH: '东方财富增强',
  REALTIME_CACHE_TTL: '实时缓存 TTL（秒）',
  CIRCUIT_BREAKER_COOLDOWN: '熔断冷却（秒）',
  PREFETCH_REALTIME_QUOTES: '预取实时行情',
  // 基本面管线
  ENABLE_FUNDAMENTAL_PIPELINE: '启用基本面管线',
  FUNDAMENTAL_STAGE_TIMEOUT_SECONDS: '阶段超时（秒）',
  FUNDAMENTAL_FETCH_TIMEOUT_SECONDS: '请求超时（秒）',
  FUNDAMENTAL_RETRY_MAX: '最大重试次数',
  FUNDAMENTAL_CACHE_TTL_SECONDS: '缓存 TTL（秒）',
  FUNDAMENTAL_CACHE_MAX_ENTRIES: '最大缓存条数',
  // 组合风控
  PORTFOLIO_RISK_CONCENTRATION_ALERT_PCT: '集中度预警(%)',
  PORTFOLIO_RISK_DRAWDOWN_ALERT_PCT: '回撤预警(%)',
  PORTFOLIO_RISK_STOP_LOSS_ALERT_PCT: '止损预警(%)',
  PORTFOLIO_RISK_STOP_LOSS_NEAR_RATIO: '止损接近比率',
  PORTFOLIO_RISK_LOOKBACK_DAYS: '风控回看天数',
  PORTFOLIO_FX_UPDATE_ENABLED: '外汇更新',
  // Agent 扩展
  AGENT_NL_ROUTING: '自然语言路由',
  AGENT_DEEP_RESEARCH_BUDGET: '深度研究 Token 预算',
  AGENT_DEEP_RESEARCH_TIMEOUT: '深度研究超时（秒）',
  AGENT_EVENT_MONITOR_ENABLED: '事件监控',
  AGENT_EVENT_MONITOR_INTERVAL_MINUTES: '监控间隔（分钟）',
  AGENT_EVENT_ALERT_RULES_JSON: '事件告警规则 JSON',
  // 视觉模型
  VISION_PROVIDER_PRIORITY: '视觉模型优先级',
  // Gemini 扩展
  GEMINI_REQUEST_DELAY: 'Gemini 请求间隔（秒）',
  GEMINI_MAX_RETRIES: 'Gemini 最大重试',
  GEMINI_RETRY_DELAY: 'Gemini 重试延迟（秒）',
  // 社交情绪
  SOCIAL_SENTIMENT_API_KEY: '社交情绪 API Key',
  SOCIAL_SENTIMENT_API_URL: '社交情绪 API URL',
  // 调度扩展
  SCHEDULE_ENABLED: '启用定时任务',
  SCHEDULE_RUN_IMMEDIATELY: '启动时立即执行',
  RUN_IMMEDIATELY: '立即运行一次',
  MARKET_REVIEW_ENABLED: '市场复盘',
  MARKET_REVIEW_REGION: '市场复盘区域',
  TRADING_DAY_CHECK_ENABLED: '交易日检查',
  // 系统扩展
  HTTPS_PROXY: 'HTTPS 代理',
  LOG_DIR: '日志目录',
  DEBUG: '调试模式',
  ADMIN_AUTH_ENABLED: '启用管理认证',
  DATABASE_PATH: '数据库路径',
  CONFIG_VALIDATE_MODE: '配置验证模式',
  PYTDX_HOST: 'Pytdx 服务器',
  PYTDX_PORT: 'Pytdx 端口',
  PYTDX_SERVERS: 'Pytdx 服务器列表',
}
const fieldDescMap = {
  STOCK_LIST: '使用逗号分隔股票代码，例如：600519,300750。',
  TUSHARE_TOKEN: '用于接入 Tushare Pro 数据服务的凭据。',
  TICKFLOW_API_KEY: '用于 TickFlow 行情增强的密钥（A 股指数+市场统计）。',
  BOCHA_API_KEYS: '用于新闻检索的 Bocha 密钥，支持逗号分隔多个（最高优先级）。',
  TAVILY_API_KEYS: '用于新闻检索的 Tavily 密钥，支持逗号分隔多个。',
  ANSPIRE_API_KEYS: '用于新闻检索的 Anspire 密钥，支持逗号分隔多个。',
  SERPAPI_API_KEYS: '用于新闻检索的 SerpAPI 密钥，支持逗号分隔多个。',
  BRAVE_API_KEYS: '用于新闻检索的 Brave Search 密钥，支持逗号分隔多个。',
  SEARXNG_BASE_URLS: 'SearXNG 自建实例地址（逗号分隔，无配额兜底）。',
  SEARXNG_PUBLIC_INSTANCES_ENABLED: '当未配置 SearXNG 自建实例时，自动从 searx.space 获取公共实例并轮询使用。',
  MINIMAX_API_KEYS: '用于新闻检索的 MiniMax 密钥，支持逗号分隔多个（最低优先级）。',
  NEWS_STRATEGY_PROFILE: '新闻窗口档位：ultra_short=1天，short=3天，medium=7天，long=30天。',
  NEWS_MAX_AGE_DAYS: '新闻最大时效上限。实际窗口 = min(策略档位天数, NEWS_MAX_AGE_DAYS)。',
  REALTIME_SOURCE_PRIORITY: '按逗号分隔填写数据源调用优先级。',
  ENABLE_REALTIME_TECHNICAL_INDICATORS: '盘中分析时用实时价计算 MA5/MA10/MA20 与多头排列；关闭则用昨日收盘。',
  ENABLE_REALTIME_QUOTE: '启用实时行情，关闭后仅使用历史收盘价。',
  ENABLE_CHIP_DISTRIBUTION: '启用筹码分布分析。可能不稳定，建议云部署关闭。',
  BIAS_THRESHOLD: 'MA5 偏离阈值(%)，超过时触发"不追高"警告。',
  LITELLM_MODEL: '主模型，格式 provider/model（如 gemini/gemini-2.5-flash）。配置渠道后自动推断。',
  AGENT_LITELLM_MODEL: 'Agent 专用主模型。留空时继承主模型。',
  LITELLM_FALLBACK_MODELS: '备选模型，逗号分隔，主模型失败时按序尝试。',
  LLM_CHANNELS: '渠道名称列表（逗号分隔）。推荐使用上方渠道编辑器管理。',
  LLM_TEMPERATURE: '控制模型输出随机性，0 为确定性输出，2 为最大随机性，推荐 0.7。',
  AIHUBMIX_KEY: 'AIHubmix 一站式密钥，自动指向 aihubmix.com/v1。',
  DEEPSEEK_API_KEY: 'DeepSeek 官方 API 密钥。填写后自动使用 deepseek-chat 模型。',
  WECHAT_WEBHOOK_URL: '企业微信机器人 Webhook 地址。',
  FEISHU_WEBHOOK_URL: '飞书自定义机器人 Webhook。',
  FEISHU_WEBHOOK_SECRET: '飞书群机器人安全设置里的"签名校验"密钥。',
  FEISHU_WEBHOOK_KEYWORD: '飞书群机器人安全设置里的"关键词"。',
  DINGTALK_APP_KEY: '钉钉应用模式 App Key。',
  DINGTALK_APP_SECRET: '钉钉应用模式 App Secret。',
  PUSHPLUS_TOKEN: 'PushPlus 推送令牌。',
  REPORT_SUMMARY_ONLY: '仅推送分析结果摘要，不包含个股详情。',
  MAX_WORKERS: '异步任务队列最大并发数。',
  SCHEDULE_TIME: '每日定时任务执行时间，格式为 HH:MM。',
  HTTP_PROXY: '网络代理地址，可留空。',
  LOG_LEVEL: '设置日志输出级别。',
  WEBUI_PORT: 'Web 页面服务监听端口。',
  AGENT_MODE: '是否启用 ReAct Agent 策略问股。',
  AGENT_MAX_STEPS: 'Agent 最大推理步数上限。',
  AGENT_SKILLS: '逗号分隔的交易策略列表。留空使用默认策略，填 all 启用全部。',
  AGENT_SKILL_DIR: '存放 Agent 策略定义文件的目录路径。',
  AGENT_ARCH: 'Agent 执行架构。single 为经典单 Agent；multi 为多 Agent 编排。',
  AGENT_ORCHESTRATOR_MODE: 'Multi-Agent 编排深度。quick（快速分析）/ deep（深度分析，含辩论+策略）。',
  AGENT_ORCHESTRATOR_TIMEOUT_S: 'Agent 执行总超时预算（秒），0 表示不限制。',
  AGENT_RISK_OVERRIDE: '允许风控 Agent 在发现关键风险时否决买入信号。',
  AGENT_SKILL_AUTOWEIGHT: '根据回测表现自动调整策略权重。',
  AGENT_SKILL_ROUTING: '策略选择方式。auto 按市场状态自动选择，manual 使用 AGENT_SKILLS 列表。',
  AGENT_MEMORY_ENABLED: '启用记忆与校准系统，追踪历史分析准确率并自动调节置信度。',
  BACKTEST_ENABLED: '是否启用回测功能（true/false）。',
  BACKTEST_EVAL_WINDOW_DAYS: '回测评估窗口长度，单位为交易日。',
  BACKTEST_MIN_AGE_DAYS: '仅回测早于该天数的分析记录。',
  BACKTEST_ENGINE_VERSION: '回测引擎版本标识，用于区分结果版本。',
  BACKTEST_NEUTRAL_BAND_PCT: '中性区间阈值百分比，例如 2 表示 -2%~+2%。',
  // 报告
  REPORT_TYPE: '默认报告类型：brief / detailed。',
  REPORT_LANGUAGE: '报告语言：zh（中文） / en（英文） / auto（自动检测）。',
  REPORT_TEMPLATES_DIR: '自定义 Jinja2 报告模板所在目录。',
  REPORT_RENDERER_ENABLED: '启用服务端报告渲染器。',
  REPORT_INTEGRITY_ENABLED: '启用报告完整性校验，确保关键字段不为空。',
  REPORT_INTEGRITY_RETRY: '完整性校验失败时的最大重试次数。',
  REPORT_HISTORY_COMPARE_N: '生成报告时对比的历史报告数量。',
  // Telegram
  TELEGRAM_BOT_TOKEN: 'Telegram Bot Token，从 @BotFather 获取。',
  TELEGRAM_CHAT_ID: '目标 Chat ID（群组或个人）。',
  TELEGRAM_MESSAGE_THREAD_ID: '话题群组的线程 ID（可选）。',
  TELEGRAM_WEBHOOK_SECRET: 'Telegram Webhook 回调签名密钥。',
  // Email
  EMAIL_SENDER: '发件人邮箱地址。',
  EMAIL_SENDER_NAME: '邮件显示的发件人名称。',
  EMAIL_PASSWORD: 'SMTP 授权码或邮箱密码。',
  EMAIL_RECEIVERS: '收件人邮箱列表，逗号分隔。',
  // Discord
  DISCORD_BOT_TOKEN: 'Discord Bot Token，从 Developer Portal 获取。',
  DISCORD_WEBHOOK_URL: 'Discord 频道 Webhook URL。',
  // Slack
  SLACK_WEBHOOK_URL: 'Slack Incoming Webhook URL。',
  SLACK_BOT_TOKEN: 'Slack Bot OAuth Token。',
  SLACK_CHANNEL_ID: '目标 Slack 频道 ID。',
  // 飞书扩展
  FEISHU_VERIFICATION_TOKEN: '飞书事件回调验证 Token。',
  FEISHU_ENCRYPT_KEY: '飞书事件订阅加密密钥。',
  FEISHU_STREAM_ENABLED: '启用飞书长连接事件流模式。',
  FEISHU_FOLDER_TOKEN: '飞书云文档目标文件夹 Token。',
  FEISHU_MAX_BYTES: '飞书单条消息最大字节数。',
  // 钉钉
  DINGTALK_STREAM_ENABLED: '启用钉钉 Stream 事件流模式。',
  // 企业微信
  WECOM_CORPID: '企业微信企业 ID。',
  WECOM_TOKEN: '企业微信应用回调 Token。',
  WECOM_ENCODING_AES_KEY: '企业微信应用回调加密密钥。',
  WECOM_AGENT_ID: '企业微信应用 Agent ID。',
  WECHAT_MAX_BYTES: '微信消息最大字节数。',
  WECHAT_MSG_TYPE: '微信消息格式：text / markdown。',
  // PushPlus / PushOver / ServerChan
  PUSHPLUS_TOPIC: 'PushPlus 群组推送话题 ID。',
  PUSHOVER_USER_KEY: 'Pushover User Key，从 Dashboard 获取。',
  PUSHOVER_API_TOKEN: 'Pushover Application API Token。',
  SERVERCHAN3_SENDKEY: 'Server酱 V3 SendKey。',
  // 自定义 Webhook
  CUSTOM_WEBHOOK_URLS: '自定义 Webhook 地址，逗号分隔。',
  CUSTOM_WEBHOOK_BEARER_TOKEN: '自定义 Webhook Bearer Token 认证。',
  WEBHOOK_VERIFY_SSL: '发送 Webhook 时是否验证 SSL 证书。',
  // AstrBot
  ASTRBOT_TOKEN: 'AstrBot 认证 Token。',
  ASTRBOT_URL: 'AstrBot 服务地址。',
  // 通知行为
  SINGLE_STOCK_NOTIFY: '启用后每只股票单独发送一条通知。',
  ANALYSIS_DELAY: '每支股票分析之间的延迟（秒）。',
  MERGE_EMAIL_NOTIFICATION: '将多只股票分析合并为一封邮件发送。',
  MARKDOWN_TO_IMAGE_CHANNELS: '自动将 Markdown 转为图片的通知渠道列表。',
  MARKDOWN_TO_IMAGE_MAX_CHARS: '超过此字符数时自动转为图片。',
  MD2IMG_ENGINE: 'Markdown 转图引擎：playwright / imgkit。',
  DISCORD_MAX_WORDS: 'Discord 单条消息最大字数限制。',
  // Longbridge
  LONGBRIDGE_APP_KEY: 'Longbridge OpenAPI App Key。',
  LONGBRIDGE_APP_SECRET: 'Longbridge OpenAPI App Secret。',
  LONGBRIDGE_ACCESS_TOKEN: 'Longbridge OpenAPI Access Token。',
  // 实时数据扩展
  ENABLE_EASTMONEY_PATCH: '启用东方财富增强数据补丁。',
  REALTIME_CACHE_TTL: '实时行情缓存有效期（秒）。',
  CIRCUIT_BREAKER_COOLDOWN: '数据源熔断冷却时间（秒）。',
  PREFETCH_REALTIME_QUOTES: '分析前预取实时行情数据。',
  // 基本面管线
  ENABLE_FUNDAMENTAL_PIPELINE: '启用基本面数据获取管线。',
  FUNDAMENTAL_STAGE_TIMEOUT_SECONDS: '管线每阶段超时时间（秒）。',
  FUNDAMENTAL_FETCH_TIMEOUT_SECONDS: '单次数据请求超时时间（秒）。',
  FUNDAMENTAL_RETRY_MAX: '数据获取失败时最大重试次数。',
  FUNDAMENTAL_CACHE_TTL_SECONDS: '基本面数据缓存有效期（秒）。',
  FUNDAMENTAL_CACHE_MAX_ENTRIES: '基本面缓存最大条目数。',
  // 组合风控
  PORTFOLIO_RISK_CONCENTRATION_ALERT_PCT: '单一持仓占比超过此阈值时触发预警。',
  PORTFOLIO_RISK_DRAWDOWN_ALERT_PCT: '组合最大回撤超过此阈值时触发预警。',
  PORTFOLIO_RISK_STOP_LOSS_ALERT_PCT: '止损位触发预警的百分比阈值。',
  PORTFOLIO_RISK_STOP_LOSS_NEAR_RATIO: '价格接近止损位时的预警比率。',
  PORTFOLIO_RISK_LOOKBACK_DAYS: '风控回溯计算的天数。',
  PORTFOLIO_FX_UPDATE_ENABLED: '启用港股/美股汇率自动更新。',
  // Agent 扩展
  AGENT_NL_ROUTING: '启用自然语言智能路由匹配策略。',
  AGENT_DEEP_RESEARCH_BUDGET: '深度研究模式的 Token 预算上限。',
  AGENT_DEEP_RESEARCH_TIMEOUT: '深度研究模式的执行超时（秒）。',
  AGENT_EVENT_MONITOR_ENABLED: '启用事件监控，自动检测重大市场事件。',
  AGENT_EVENT_MONITOR_INTERVAL_MINUTES: '事件监控检查间隔（分钟）。',
  AGENT_EVENT_ALERT_RULES_JSON: '事件告警规则 JSON 配置。',
  // 视觉
  VISION_PROVIDER_PRIORITY: '视觉模型供应商优先级，逗号分隔。',
  // Gemini 扩展
  GEMINI_REQUEST_DELAY: 'Gemini API 请求间隔（秒），防限流。',
  GEMINI_MAX_RETRIES: 'Gemini API 最大重试次数。',
  GEMINI_RETRY_DELAY: 'Gemini API 重试间隔（秒）。',
  // 社交情绪
  SOCIAL_SENTIMENT_API_KEY: '社交情绪分析 API 密钥。',
  SOCIAL_SENTIMENT_API_URL: '社交情绪分析 API 地址。',
  // 调度
  SCHEDULE_ENABLED: '是否启用定时任务调度器。',
  SCHEDULE_RUN_IMMEDIATELY: '应用启动时立即执行一次分析。',
  RUN_IMMEDIATELY: '强制立即运行一次分析。',
  MARKET_REVIEW_ENABLED: '启用每日市场复盘功能。',
  MARKET_REVIEW_REGION: '市场复盘区域：cn（A股） / us（美股） / hk（港股）。',
  TRADING_DAY_CHECK_ENABLED: '启用交易日检查，非交易日跳过定时任务。',
  // 系统
  HTTPS_PROXY: 'HTTPS 代理地址，可留空。',
  LOG_DIR: '日志文件存储目录。',
  DEBUG: '启用调试模式，输出详细日志。',
  DATABASE_PATH: 'SQLite 数据库文件路径。',
  CONFIG_VALIDATE_MODE: '配置验证模式：strict / warn / off。',
}

function getFieldTitle(key, fallback) {
  return fieldTitleMap[key] || fallback || key
}
function getFieldDesc(key, fallback) {
  return fieldDescMap[key] || fallback || ''
}

// =============================
// LLM 渠道预设
// =============================
const channelPresets = {
  aihubmix: { label: 'AIHubmix（聚合平台）', protocol: 'openai', baseUrl: 'https://aihubmix.com/v1', placeholder: 'gpt-4o-mini,claude-3-5-sonnet,qwen-plus' },
  deepseek: { label: 'DeepSeek 官方', protocol: 'deepseek', baseUrl: 'https://api.deepseek.com/v1', placeholder: 'deepseek-chat,deepseek-reasoner' },
  dashscope: { label: '通义千问（Dashscope）', protocol: 'openai', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', placeholder: 'qwen-plus,qwen-turbo' },
  zhipu: { label: '智谱 GLM', protocol: 'openai', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', placeholder: 'glm-4-flash,glm-4-plus' },
  moonshot: { label: 'Moonshot（月之暗面）', protocol: 'openai', baseUrl: 'https://api.moonshot.cn/v1', placeholder: 'moonshot-v1-8k' },
  siliconflow: { label: '硅基流动（SiliconFlow）', protocol: 'openai', baseUrl: 'https://api.siliconflow.cn/v1', placeholder: 'Qwen/Qwen3-8B,deepseek-ai/DeepSeek-V3' },
  openrouter: { label: 'OpenRouter', protocol: 'openai', baseUrl: 'https://openrouter.ai/api/v1', placeholder: 'openai/gpt-4o,anthropic/claude-3-5-sonnet' },
  gemini: { label: 'Gemini 官方', protocol: 'gemini', baseUrl: '', placeholder: 'gemini-2.5-flash,gemini-2.5-pro' },
  anthropic: { label: 'Anthropic 官方', protocol: 'anthropic', baseUrl: '', placeholder: 'claude-3-5-sonnet-20241022' },
  openai: { label: 'OpenAI 官方', protocol: 'openai', baseUrl: 'https://api.openai.com/v1', placeholder: 'gpt-4o,gpt-4o-mini' },
  ollama: { label: 'Ollama（本地）', protocol: 'ollama', baseUrl: 'http://127.0.0.1:11434', placeholder: 'llama3.2,qwen2.5' },
  custom: { label: '自定义渠道', protocol: 'openai', baseUrl: '', placeholder: 'model-name-1,model-name-2' },
}
const protocolOptions = [
  { value: 'openai', label: 'OpenAI Compatible' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'gemini', label: 'Gemini' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'vertex_ai', label: 'Vertex AI' },
  { value: 'ollama', label: 'Ollama' },
]

// =============================
// 数据源 & 新闻源渠道预设
// =============================
const dataSourcePresets = {
  akshare:    { label: 'AKShare（新浪/东财/腾讯）', authType: 'none', defaultEnabled: true, subSources: ['tencent', 'akshare_sina', 'akshare_em'], desc: '聚合免费数据源，含新浪/东财/腾讯实时行情' },
  efinance:   { label: 'Efinance（东方财富）', authType: 'none', defaultEnabled: true, desc: '东方财富爬虫封装，免费' },
  pytdx:      { label: '通达信 (Pytdx)', authType: 'server', fields: ['host', 'port', 'servers'], keys: ['PYTDX_HOST', 'PYTDX_PORT', 'PYTDX_SERVERS'], defaultEnabled: false, desc: '需自行部署通达信数据服务器' },
  tushare:    { label: 'Tushare Pro', authType: 'token', fields: ['token'], keys: ['TUSHARE_TOKEN'], defaultEnabled: false, desc: '付费金融数据 API' },
  tickflow:   { label: 'TickFlow', authType: 'apiKey', fields: ['apiKey'], keys: ['TICKFLOW_API_KEY'], defaultEnabled: false, desc: '支持 A/港/美股，REST+WebSocket' },
  longbridge: { label: 'Longbridge（长桥）', authType: 'multi', fields: ['appKey', 'appSecret', 'accessToken'], fieldLabels: ['App Key', 'App Secret', 'Access Token'], keys: ['LONGBRIDGE_APP_KEY', 'LONGBRIDGE_APP_SECRET', 'LONGBRIDGE_ACCESS_TOKEN'], defaultEnabled: false, desc: '长桥证券数据接口' },
  binance:    { label: 'Binance（币安）', authType: 'multi', fields: ['apiKey', 'apiSecret'], fieldLabels: ['API Key', 'API Secret'], keys: ['BINANCE_API_KEY', 'BINANCE_API_SECRET'], defaultEnabled: false, optional: true, desc: '加密货币行情，公开市场数据无需Key（有速率限制）' },
  okx:        { label: 'OKX（欧易）', authType: 'multi', fields: ['apiKey', 'secretKey', 'passphrase'], fieldLabels: ['API Key', 'Secret Key', 'Passphrase'], keys: ['OKX_API_KEY', 'OKX_SECRET_KEY', 'OKX_PASSPHRASE'], defaultEnabled: false, optional: true, desc: '加密货币行情，公开市场数据无需Key（有速率限制）' },
}

const newsSourcePresets = {
  bocha:       { label: 'Bocha', authType: 'apiKey', keys: ['BOCHA_API_KEYS'], desc: '博查搜索' },
  anspire:     { label: 'Anspire', authType: 'apiKey', keys: ['ANSPIRE_API_KEYS'], desc: '新闻检索' },
  tavily:      { label: 'Tavily', authType: 'apiKey', keys: ['TAVILY_API_KEYS'], desc: 'AI 搜索引擎' },
  serpapi:     { label: 'SerpAPI', authType: 'apiKey', keys: ['SERPAPI_API_KEYS'], desc: 'Google 搜索代理' },
  brave:       { label: 'Brave Search', authType: 'apiKey', keys: ['BRAVE_API_KEYS'], desc: 'Brave 搜索' },
  minimax:     { label: 'MiniMax', authType: 'apiKey', keys: ['MINIMAX_API_KEYS'], desc: 'MiniMax 搜索' },
  searxng:     { label: 'SearXNG（自建）', authType: 'url', keys: ['SEARXNG_BASE_URLS'], desc: '自建实例，无配额' },
  searxng_pub: { label: 'SearXNG（公共实例）', authType: 'none', keys: ['SEARXNG_PUBLIC_INSTANCES_ENABLED'], desc: '自动从 searx.space 发现公共实例' },
}

// =============================
// 状态
// =============================
const activeCategory = ref('local')
const dsaServerRunning = ref(false)
const dsaStatus = ref('stopped')
const statusDesc = ref('启动 DSA 后端服务后，可使用股票分析和问股功能')

// 本地设置
const localConfig = reactive({
  workspacePath: '',
  theme: 'dark',
  dataSource: 'binance',
  closeWarning: false,
  maxTabs: 10,
  externalEditor: 'auto',
  externalEditorPath: '',
})

// DSA 本地连接配置
const dsaLocal = reactive({
  backendPath: '',
  port: 8100,
})

// 服务端连接配置（Phase 1.4）
const serverConfig = reactive({
  mode: 'local',
  remoteBaseUrl: '',
  token: ''
})
const serverTesting = ref(false)
const serverTestResult = ref(null)
const serverSaving = ref(false)
const serverSaved = ref(false)

const CLIENT_TOKEN_KEY = 'hivelogic:clientToken'
const clientAuthEnabled = ref(false)
const clientAuthLoading = ref(false)
const clientAccount = ref(null)
const clientTier = ref('')
const clientUsage = ref(null)
const clientLoginEmail = ref('')
const clientLoginPassword = ref('')
const clientLoggingIn = ref(false)
const clientLoggingOut = ref(false)
const clientLoginError = ref('')

// DSA 后端配置
const isLoadingDsa = ref(false)
const dsaLoadError = ref('')
const dsaConfigVersion = ref('')
const dsaMaskToken = ref('')
const dsaItems = ref([])         // 原始 items from server
const draftValues = reactive({}) // key -> draft value
const serverValues = reactive({}) // key -> server value
const passwordVisibility = reactive({})
const isSaving = ref(false)

// LLM 渠道
const channels = ref([])
const channelsDirty = ref(false)
const isSavingChannels = ref(false)
const expandedChannels = reactive({})
const addPresetKey = ref('')

// 数据源渠道
const dsChannels = ref([])
const dsChannelsDirty = ref(false)
const isSavingDsChannels = ref(false)
const dsExpanded = reactive({})
const dsAddPresetKey = ref('')

// 新闻源渠道
const nsChannels = ref([])
const nsChannelsDirty = ref(false)
const isSavingNsChannels = ref(false)
const nsExpanded = reactive({})
const nsAddPresetKey = ref('')

// toast
const toast = ref(null)
let toastTimer = null

// 确认对话框
const confirmDialog = reactive({
  show: false,
  title: '',
  message: '',
  confirmText: '确定',
  cancelText: '取消',
  onConfirm: () => {},
  onCancel: () => { confirmDialog.show = false },
})

// =============================
// 计算属性
// =============================
const baseUrl = computed(() => getApiBase())

const statusInfo = computed(() => {
  const map = {
    stopped: { color: '#666', text: '未启动', showStart: true, showStop: false },
    starting: { color: '#d29922', text: '正在启动...', showStart: false, showStop: false },
    running: { color: '#2ea043', text: '运行中', showStart: false, showStop: true },
    error: { color: '#da3633', text: '启动失败', showStart: true, showStop: false },
  }
  return map[dsaStatus.value] || map.stopped
})

const DSA_CATEGORIES = ['base', 'ai_model', 'data_source', 'notification', 'system', 'agent', 'backtest', 'uncategorized']
const isDsaCategory = computed(() => DSA_CATEGORIES.includes(activeCategory.value))

// items by category
const itemsByCategory = computed(() => {
  const map = {}
  for (const item of dsaItems.value) {
    const cat = item.schema?.category || 'uncategorized'
    if (!map[cat]) map[cat] = []
    map[cat].push(item)
  }
  return map
})

// ai_model 过滤逻辑（与 DSA SettingsPage 一致）
const AI_MODEL_HIDDEN_KEYS = new Set([
  'LLM_CHANNELS', 'LLM_TEMPERATURE', 'LITELLM_MODEL', 'AGENT_LITELLM_MODEL', 'LITELLM_FALLBACK_MODELS',
  'AIHUBMIX_KEY', 'DEEPSEEK_API_KEY', 'DEEPSEEK_API_KEYS',
  'GEMINI_API_KEY', 'GEMINI_API_KEYS', 'GEMINI_MODEL', 'GEMINI_MODEL_FALLBACK', 'GEMINI_TEMPERATURE',
  'ANTHROPIC_API_KEY', 'ANTHROPIC_API_KEYS', 'ANTHROPIC_MODEL', 'ANTHROPIC_TEMPERATURE', 'ANTHROPIC_MAX_TOKENS',
  'OPENAI_API_KEY', 'OPENAI_API_KEYS', 'OPENAI_BASE_URL', 'OPENAI_MODEL', 'OPENAI_VISION_MODEL', 'OPENAI_TEMPERATURE',
  'VISION_MODEL',
])
const LLM_CHANNEL_KEY_RE = /^LLM_[A-Z0-9]+_(PROTOCOL|BASE_URL|API_KEY|API_KEYS|MODELS|EXTRA_HEADERS|ENABLED)$/

const filteredActiveItems = computed(() => {
  const raw = itemsByCategory.value[activeCategory.value] || []
  if (activeCategory.value === 'ai_model') {
    const rawMap = new Map(raw.map(i => [i.key, String(i.value ?? '')]))
    const hasChannels = Boolean((rawMap.get('LLM_CHANNELS') || '').trim())
    const hasLitellmConfig = Boolean((rawMap.get('LITELLM_CONFIG') || '').trim())
    return raw.filter(item => {
      // 已在 AI 编辑器中手动管理的 key
      if (AI_MODEL_MANAGED_KEYS.has(item.key)) return false
      if (hasChannels && LLM_CHANNEL_KEY_RE.test(item.key)) return false
      if (hasChannels && !hasLitellmConfig && AI_MODEL_HIDDEN_KEYS.has(item.key)) return false
      return true
    })
  }
  if (activeCategory.value === 'data_source') {
    return raw.filter(item => !DATA_SOURCE_MANAGED_KEYS.has(item.key))
  }
  return raw
})

// 分类下的字段分组定义（key → group key，未列出的归入 _other）
const categoryGroupDefs = {
  data_source: {
    groups: [
      { key: 'market_data', title: '行情数据源', desc: '行情数据提供商凭证与优先级配置。' },
      { key: 'search_engine', title: '搜索引擎', desc: '网络搜索 API 密钥，用于新闻与资讯检索。' },
      { key: 'news_analysis', title: '新闻与分析参数', desc: '新闻窗口、策略档位和偏离阈值。' },
      { key: 'fundamental', title: '基本面管线', desc: '基本面数据获取与缓存策略。' },
    ],
    keyMap: {
      TUSHARE_TOKEN: 'market_data',
      TICKFLOW_API_KEY: 'market_data',
      REALTIME_SOURCE_PRIORITY: 'market_data',
      ENABLE_REALTIME_QUOTE: 'market_data',
      ENABLE_REALTIME_TECHNICAL_INDICATORS: 'market_data',
      ENABLE_CHIP_DISTRIBUTION: 'market_data',
      ENABLE_EASTMONEY_PATCH: 'market_data',
      REALTIME_CACHE_TTL: 'market_data',
      CIRCUIT_BREAKER_COOLDOWN: 'market_data',
      PREFETCH_REALTIME_QUOTES: 'market_data',
      PYTDX_HOST: 'market_data',
      PYTDX_PORT: 'market_data',
      PYTDX_SERVERS: 'market_data',
      LONGBRIDGE_APP_KEY: 'market_data',
      LONGBRIDGE_APP_SECRET: 'market_data',
      LONGBRIDGE_ACCESS_TOKEN: 'market_data',
      ANSPIRE_API_KEYS: 'search_engine',
      TAVILY_API_KEYS: 'search_engine',
      SERPAPI_API_KEYS: 'search_engine',
      BRAVE_API_KEYS: 'search_engine',
      BOCHA_API_KEYS: 'search_engine',
      MINIMAX_API_KEYS: 'search_engine',
      SEARXNG_BASE_URLS: 'search_engine',
      SEARXNG_PUBLIC_INSTANCES_ENABLED: 'search_engine',
      NEWS_MAX_AGE_DAYS: 'news_analysis',
      NEWS_STRATEGY_PROFILE: 'news_analysis',
      BIAS_THRESHOLD: 'news_analysis',
      ENABLE_FUNDAMENTAL_PIPELINE: 'fundamental',
      FUNDAMENTAL_STAGE_TIMEOUT_SECONDS: 'fundamental',
      FUNDAMENTAL_FETCH_TIMEOUT_SECONDS: 'fundamental',
      FUNDAMENTAL_RETRY_MAX: 'fundamental',
      FUNDAMENTAL_CACHE_TTL_SECONDS: 'fundamental',
      FUNDAMENTAL_CACHE_MAX_ENTRIES: 'fundamental',
    },
  },
}

const groupedActiveItems = computed(() => {
  const def = categoryGroupDefs[activeCategory.value]
  if (!def) return []
  const items = filteredActiveItems.value
  if (!items.length) return []
  const buckets = {}
  for (const g of def.groups) buckets[g.key] = []
  buckets._other = []
  for (const item of items) {
    const gk = def.keyMap[item.key] || '_other'
    if (!buckets[gk]) buckets[gk] = []
    buckets[gk].push(item)
  }
  const result = []
  for (const g of def.groups) {
    if (buckets[g.key].length) result.push({ ...g, items: buckets[g.key] })
  }
  if (buckets._other.length) result.push({ key: '_other', title: '其他', desc: '', items: buckets._other })
  return result
})

// 导航栏分类
const categoryIconMap = {
  local: '⚙️',
  dsa_service: '🔌',
  base: '📋',
  ai_model: '🧠',
  data_source: '📊',
  notification: '🔔',
  system: '🛠️',
  agent: '🤖',
  backtest: '📈',
  uncategorized: '📦',
}

const localCategories = computed(() => {
  const cats = [
    { key: 'local', icon: '⚙️', title: '本地设置', description: '工作区、主题与标签页配置。', count: 0 },
    { key: 'server', icon: '🔗', title: '服务端连接', description: '本地内置或远程服务端地址。', count: 0 },
    { key: 'dsa_service', icon: '🔌', title: 'DSA 服务', description: '后端服务连接与启停管理。', count: 0 },
  ]
  if (dsaServerRunning.value) {
    cats.push({ key: 'admin', icon: '🛡️', title: '管理面板', description: '服务状态、客户端与缓存管理。', count: 0 })
  }
  return cats
})

const dsaCategories = computed(() => {
  if (!dsaServerRunning.value || dsaItems.value.length === 0) {
    return DSA_CATEGORIES.filter(c => c !== 'uncategorized').map(c => ({
      key: c,
      icon: categoryIconMap[c] || '📦',
      title: categoryTitleMap[c] || c,
      description: categoryDescMap[c] || '',
      count: 0,
    }))
  }
  const cats = []
  for (const cat of DSA_CATEGORIES) {
    const items = itemsByCategory.value[cat]
    if (!items || items.length === 0) continue
    cats.push({
      key: cat,
      icon: categoryIconMap[cat] || '📦',
      title: categoryTitleMap[cat] || cat,
      description: categoryDescMap[cat] || '',
      count: items.length,
    })
  }
  return cats
})

const allCategories = computed(() => [
  ...localCategories.value,
  ...dsaCategories.value,
])

const currentCategoryTitle = computed(() => {
  return categoryTitleMap[activeCategory.value] || '当前分类配置项'
})
const currentCategoryDesc = computed(() => {
  return categoryDescMap[activeCategory.value] || '使用统一字段卡片维护当前分类的系统配置。'
})

const hasDirty = computed(() => {
  for (const key of Object.keys(draftValues)) {
    if (normalize(draftValues[key]) !== normalize(serverValues[key])) return true
  }
  return false
})

const dirtyCount = computed(() => {
  let count = 0
  for (const key of Object.keys(draftValues)) {
    if (normalize(draftValues[key]) !== normalize(serverValues[key])) count++
  }
  return count
})

// =============================
// 方法
// =============================
function normalize(v) {
  if (v === null || v === undefined) return ''
  return String(v).trim()
}

function normalizeOptions(opts) {
  if (!opts) return []
  return opts.map(o => {
    if (typeof o === 'string') return { label: o, value: o }
    return o
  })
}

function getDraftValue(key) {
  return key in draftValues ? draftValues[key] : ''
}

function setDraft(key, value) {
  draftValues[key] = value
}

function resetDraft() {
  for (const key of Object.keys(serverValues)) {
    draftValues[key] = serverValues[key]
  }
}

function togglePasswordVisibility(key) {
  passwordVisibility[key] = !passwordVisibility[key]
}

function showToast(type, message) {
  toast.value = { type, message }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = null }, 3200)
}

function showConfirm(title, message, confirmText = '确定', cancelText = '取消') {
  return new Promise((resolve) => {
    confirmDialog.title = title
    confirmDialog.message = message
    confirmDialog.confirmText = confirmText
    confirmDialog.cancelText = cancelText
    confirmDialog.show = true
    confirmDialog.onConfirm = () => { confirmDialog.show = false; resolve(true) }
    confirmDialog.onCancel = () => { confirmDialog.show = false; resolve(false) }
  })
}

// =============================
// 本地设置
// =============================
function saveLocalSetting(key, value) {
  localStorage.setItem(key, String(value))
}

async function saveExternalEditor() {
  const value = localConfig.externalEditor === 'custom'
    ? localConfig.externalEditorPath
    : localConfig.externalEditor
  await window.electronAPI?.setExternalEditor?.(value)
}

async function browseWorkspace() {
  if (window.electronAPI?.setWorkspacePath) {
    const newPath = await window.electronAPI.setWorkspacePath()
    if (newPath) localConfig.workspacePath = newPath
  }
}

async function onDataSourceChange() {
  const prev = await window.electronAPI?.getDataSource?.() || 'binance'
  if (localConfig.dataSource === prev) return
  const ok = await showConfirm('切换数据源', '切换数据源后，所有已打开的图表页面都会关闭。确定要继续吗？', '确定', '取消')
  if (ok) {
    localStorage.setItem('data-source', localConfig.dataSource)
    window.electronAPI?.setDataSource?.(localConfig.dataSource)
    window.electronAPI?.closeAllChartTabs?.()
  } else {
    localConfig.dataSource = prev
  }
}

// =============================
// DSA 本地连接配置
// =============================
async function loadDsaLocal() {
  if (!window.electronAPI?.getDsaConfig) return
  const cfg = await window.electronAPI.getDsaConfig()
  dsaLocal.backendPath = cfg.backendPath || ''
  dsaLocal.port = cfg.port || 8100
}

async function saveDsaLocal() {
  if (!window.electronAPI?.setDsaConfig) return
  await window.electronAPI.setDsaConfig({
    port: dsaLocal.port,
  })
}

async function loadServerConfig() {
  if (!window.electronAPI?.getServerConfig) return
  const cfg = await window.electronAPI.getServerConfig()
  serverConfig.mode = cfg.mode || 'local'
  serverConfig.remoteBaseUrl = cfg.remoteBaseUrl || ''
  serverConfig.token = cfg.token || ''
  syncServerConfigToStorage()
}

async function saveServerConfig() {
  if (!window.electronAPI?.setServerConfig) return
  serverSaving.value = true
  serverSaved.value = false
  try {
    await window.electronAPI.setServerConfig({
      mode: serverConfig.mode,
      remoteBaseUrl: serverConfig.remoteBaseUrl.trim(),
      token: serverConfig.token
    })
    syncServerConfigToStorage()
    serverSaved.value = true
  } finally {
    serverSaving.value = false
  }
}

function syncServerConfigToStorage() {
  const STORAGE_KEY = 'hivelogic:serverBaseUrl'
  if (serverConfig.mode === 'remote' && serverConfig.remoteBaseUrl.trim()) {
    localStorage.setItem(STORAGE_KEY, serverConfig.remoteBaseUrl.trim())
  } else {
    localStorage.removeItem(STORAGE_KEY)
  }
}

async function testServerConnection() {
  const url = serverConfig.remoteBaseUrl.trim()
  if (!url) {
    serverTestResult.value = { success: false, message: '请先填写服务端地址' }
    return
  }
  serverTesting.value = true
  serverTestResult.value = null
  try {
    const resp = await fetch(`${url.replace(/\/+$/, '')}/api/health`, { signal: AbortSignal.timeout(5000) })
    if (resp.ok) {
      serverTestResult.value = { success: true, message: `连接成功（HTTP ${resp.status}）` }
    } else {
      serverTestResult.value = { success: false, message: `服务端返回 HTTP ${resp.status}` }
    }
  } catch (e) {
    serverTestResult.value = { success: false, message: `连接失败: ${e.message || e}` }
  } finally {
    serverTesting.value = false
  }
}

function clientAuthHeaders() {
  const token = localStorage.getItem(CLIENT_TOKEN_KEY)
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function loadClientAuthStatus() {
  if (!dsaServerRunning.value) return
  clientAuthLoading.value = true
  try {
    const resp = await fetch(`${baseUrl.value}/api/v1/client-auth/me`, {
      headers: { ...clientAuthHeaders() },
    })
    if (resp.ok) {
      const data = await resp.json()
      clientAuthEnabled.value = true
      clientAccount.value = data.account
      clientTier.value = data.tier
      clientUsage.value = data.usage
    } else if (resp.status === 401) {
      clientAuthEnabled.value = true
      clientAccount.value = null
      clientTier.value = ''
      clientUsage.value = null
      localStorage.removeItem(CLIENT_TOKEN_KEY)
    } else {
      const statusResp = await fetch(`${baseUrl.value}/api/v1/client-auth/status`)
      if (statusResp.ok) {
        const statusData = await statusResp.json()
        clientAuthEnabled.value = !!statusData.client_auth_enabled
      }
    }
  } catch {
    clientAuthEnabled.value = false
  } finally {
    clientAuthLoading.value = false
  }
}

async function clientLogin() {
  if (!clientLoginEmail.value || !clientLoginPassword.value) return
  clientLoggingIn.value = true
  clientLoginError.value = ''
  try {
    const resp = await fetch(`${baseUrl.value}/api/v1/client-auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: clientLoginEmail.value,
        password: clientLoginPassword.value,
        deviceInfo: navigator.userAgent.slice(0, 255),
      }),
    })
    const data = await resp.json()
    if (!resp.ok) {
      clientLoginError.value = data.message || data.error || '登录失败'
      return
    }
    localStorage.setItem(CLIENT_TOKEN_KEY, data.token)
    clientAccount.value = data.account
    clientTier.value = data.tier
    clientUsage.value = null
    clientLoginPassword.value = ''
    showToast('success', '登录成功')
    await loadClientAuthStatus()
  } catch (e) {
    clientLoginError.value = e.message || '网络错误'
  } finally {
    clientLoggingIn.value = false
  }
}

async function clientLogout() {
  clientLoggingOut.value = true
  try {
    await fetch(`${baseUrl.value}/api/v1/client-auth/logout`, {
      method: 'POST',
      headers: { ...clientAuthHeaders() },
    })
  } catch {
  } finally {
    localStorage.removeItem(CLIENT_TOKEN_KEY)
    clientAccount.value = null
    clientTier.value = ''
    clientUsage.value = null
    clientLoggingOut.value = false
    showToast('success', '已退出登录')
  }
}

const TIER_LABELS = { free: '免费版', pro: '专业版', enterprise: '企业版' }
function tierBadgeLabel(tier) {
  return TIER_LABELS[tier] || tier || '-'
}
function tierBadgeClass(tier) {
  if (tier === 'enterprise') return 'tier-enterprise'
  if (tier === 'pro') return 'tier-pro'
  return 'tier-free'
}

// =============================
// DSA 服务管理
// =============================
async function startServer() {
  await saveDsaLocal()
  dsaStatus.value = 'starting'
  if (window.electronAPI?.startDsaServer) {
    const result = await window.electronAPI.startDsaServer()
    if (result.success) {
      dsaStatus.value = 'running'
      dsaServerRunning.value = true
      statusDesc.value = `服务运行在 ${baseUrl.value}`
      await loadDsaConfig()
    } else {
      dsaStatus.value = 'error'
      statusDesc.value = `启动失败: ${result.error}`
    }
  }
}

async function stopServer() {
  if (window.electronAPI?.stopDsaServer) {
    await window.electronAPI.stopDsaServer()
    dsaStatus.value = 'stopped'
    dsaServerRunning.value = false
    statusDesc.value = '启动 DSA 后端服务后，可使用股票分析和问股功能'
  }
}

function updateStatusFromEvent(data) {
  dsaStatus.value = data.status
  dsaServerRunning.value = data.status === 'running'
  if (data.status === 'running') {
    statusDesc.value = `服务运行在 ${baseUrl.value}`
    if (dsaItems.value.length === 0) loadDsaConfig()
    loadClientAuthStatus()
  }
}

// =============================
// DSA 后端配置 API
// =============================

// snake_case -> camelCase
function toCamel(obj) {
  if (Array.isArray(obj)) return obj.map(toCamel)
  if (obj && typeof obj === 'object') {
    const out = {}
    for (const [k, v] of Object.entries(obj)) {
      const ck = k.replace(/_([a-z])/g, (_, c) => c.toUpperCase())
      out[ck] = toCamel(v)
    }
    return out
  }
  return obj
}

// camelCase -> snake_case
function toSnake(obj) {
  if (Array.isArray(obj)) return obj.map(toSnake)
  if (obj && typeof obj === 'object') {
    const out = {}
    for (const [k, v] of Object.entries(obj)) {
      const sk = k.replace(/[A-Z]/g, c => `_${c.toLowerCase()}`)
      out[sk] = toSnake(v)
    }
    return out
  }
  return obj
}

async function loadDsaConfig() {
  if (!dsaServerRunning.value) return
  isLoadingDsa.value = true
  dsaLoadError.value = ''
  try {
    const resp = await fetch(`${baseUrl.value}/api/v1/system/config?include_schema=true`)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const raw = await resp.json()
    const data = toCamel(raw)
    dsaConfigVersion.value = data.configVersion || ''
    dsaMaskToken.value = data.maskToken || ''
    dsaItems.value = data.items || []
    // 初始化 draft/server values
    for (const item of dsaItems.value) {
      const val = item.value ?? ''
      serverValues[item.key] = String(val)
      draftValues[item.key] = String(val)
    }
    // 解析 LLM 渠道
    parseChannels()
    // 解析数据源 & 新闻源渠道
    parseDsChannels()
    parseNsChannels()
    nextTick(() => { initDsSortable(); initNsSortable() })
  } catch (e) {
    dsaLoadError.value = e.message || '未知错误'
  } finally {
    isLoadingDsa.value = false
  }
}

async function saveDsaBackendConfig() {
  if (!hasDirty.value || isSaving.value) return
  isSaving.value = true
  try {
    const items = []
    for (const key of Object.keys(draftValues)) {
      if (normalize(draftValues[key]) !== normalize(serverValues[key])) {
        items.push({ key, value: draftValues[key] })
      }
    }
    const body = toSnake({
      configVersion: dsaConfigVersion.value,
      maskToken: dsaMaskToken.value,
      reloadNow: true,
      items,
    })
    const resp = await fetch(`${baseUrl.value}/api/v1/system/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${resp.status}`)
    }
    showToast('success', '配置已保存')
    // 重新加载
    await loadDsaConfig()
  } catch (e) {
    showToast('error', `保存失败: ${e.message}`)
  } finally {
    isSaving.value = false
  }
}

// =============================
// 配置导入/导出
// =============================
async function exportConfig() {
  if (dsaItems.value.length === 0) return
  // 构建 .env 格式内容
  const lines = []
  lines.push(`# HiveLogic DSA Config Export`)
  lines.push(`# ${new Date().toISOString()}`)
  lines.push('')
  for (const item of dsaItems.value) {
    const val = getDraftValue(item.key)
    if (item.schema?.isSensitive && val === dsaMaskToken.value) continue
    lines.push(`${item.key}=${val}`)
  }
  const content = lines.join('\n')
  if (window.electronAPI?.exportConfig) {
    const result = await window.electronAPI.exportConfig(content, 'hivelogic-config.env')
    if (result.success) {
      showToast('success', '配置已导出')
    } else if (result.error) {
      showToast('error', `导出失败: ${result.error}`)
    }
  } else {
    // 浏览器模式降级：下载文件
    const blob = new Blob([content], { type: 'text/plain' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'hivelogic-config.env'
    a.click()
    URL.revokeObjectURL(a.href)
    showToast('success', '配置已导出')
  }
}

async function importConfig() {
  let content = ''
  let fileName = ''

  if (window.electronAPI?.importConfig) {
    const result = await window.electronAPI.importConfig()
    if (!result.success) return
    content = result.content
    fileName = result.path
  } else {
    // 浏览器模式降级：使用 file input
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.env,.json'
    const file = await new Promise(resolve => {
      input.onchange = () => resolve(input.files[0])
      input.click()
    })
    if (!file) return
    content = await file.text()
    fileName = file.name
  }

  // 解析 .env 格式
  const items = []
  const existingKeys = new Set(dsaItems.value.map(i => i.key))
  for (const line of content.split('\n')) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const eqIdx = trimmed.indexOf('=')
    if (eqIdx <= 0) continue
    const key = trimmed.substring(0, eqIdx).trim()
    const val = trimmed.substring(eqIdx + 1).trim()
    if (existingKeys.has(key)) {
      items.push({ key, value: val })
    }
  }

  if (items.length === 0) {
    showToast('error', '未找到可导入的配置项')
    return
  }

  const ok = await showConfirm(
    '导入配置',
    `将从文件导入 ${items.length} 项配置，已有值将被覆盖。确定继续？`,
    '导入',
    '取消'
  )
  if (!ok) return

  // 写入 draft
  for (const { key, value } of items) {
    draftValues[key] = value
  }
  showToast('success', `已导入 ${items.length} 项配置，请点击「保存配置」生效`)
}

// =============================
// LLM 渠道管理
// =============================
function parseChannels() {
  const channelNamesItem = dsaItems.value.find(i => i.key === 'LLM_CHANNELS')
  const channelNames = (channelNamesItem?.value || '').split(',').map(s => s.trim()).filter(Boolean)
  if (channelNames.length === 0) {
    channels.value = []
    return
  }
  const allItems = new Map(dsaItems.value.map(i => [i.key, i.value ?? '']))
  channels.value = channelNames.map(name => {
    const prefix = `LLM_${name.toUpperCase()}`
    const protocol = allItems.get(`${prefix}_PROTOCOL`) || 'openai'
    const baseUrl = allItems.get(`${prefix}_BASE_URL`) || ''
    const apiKey = allItems.get(`${prefix}_API_KEY`) || allItems.get(`${prefix}_API_KEYS`) || ''
    const models = allItems.get(`${prefix}_MODELS`) || ''
    const enabled = allItems.get(`${prefix}_ENABLED`) !== 'false'
    // 尝试匹配预设
    let preset = 'custom'
    for (const [pk, pv] of Object.entries(channelPresets)) {
      if (pk === name || (pv.protocol === protocol && pv.baseUrl && pv.baseUrl === baseUrl)) {
        preset = pk
        break
      }
    }
    return reactive({
      name,
      preset,
      protocol,
      baseUrl,
      apiKey,
      models,
      enabled,
      showKey: false,
      testing: false,
      discovering: false,
      testResult: null,
    })
  })
}

function addChannel() {
  const newIdx = channels.value.length
  channels.value.push(reactive({
    name: '',
    preset: 'custom',
    protocol: 'openai',
    baseUrl: '',
    apiKey: '',
    models: '',
    enabled: true,
    showKey: false,
    testing: false,
    discovering: false,
    testResult: null,
  }))
  expandedChannels[newIdx] = true
  channelsDirty.value = true
}

function addChannelFromPreset() {
  const pk = addPresetKey.value
  if (!pk) return
  const preset = channelPresets[pk]
  if (!preset) return
  const newIdx = channels.value.length
  channels.value.push(reactive({
    name: pk,
    preset: pk,
    protocol: preset.protocol,
    baseUrl: preset.baseUrl,
    apiKey: '',
    models: '',
    enabled: true,
    showKey: false,
    testing: false,
    discovering: false,
    testResult: null,
  }))
  expandedChannels[newIdx] = true
  channelsDirty.value = true
  addPresetKey.value = ''
}

function removeChannel(idx) {
  channels.value.splice(idx, 1)
  // re-index expandedChannels
  const updated = {}
  for (let i = 0; i < channels.value.length; i++) {
    updated[i] = i < idx ? !!expandedChannels[i] : !!expandedChannels[i + 1]
  }
  Object.keys(expandedChannels).forEach(k => delete expandedChannels[k])
  Object.assign(expandedChannels, updated)
  channelsDirty.value = true
}

function onChannelPresetChange(idx) {
  const ch = channels.value[idx]
  const preset = channelPresets[ch.preset]
  if (!preset) return
  ch.protocol = preset.protocol
  ch.baseUrl = preset.baseUrl
  if (!ch.name) ch.name = ch.preset
  channelsDirty.value = true
}

function markChannelsDirty() {
  channelsDirty.value = true
}

function toggleChannelExpand(idx) {
  expandedChannels[idx] = !expandedChannels[idx]
}

function protocolLabel(protocol) {
  const match = protocolOptions.find(p => p.value === protocol)
  return match ? match.label : protocol
}

function channelModelCount(ch) {
  if (!ch.models) return 0
  return ch.models.split(',').filter(m => m.trim()).length
}

function channelStatusClass(ch) {
  if (!ch.apiKey) return 'status-warn'
  if (ch.testResult?.ok) return 'status-ok'
  if (ch.testResult && !ch.testResult.ok) return 'status-error'
  return 'status-idle'
}

const enabledChannelCount = computed(() => channels.value.filter(c => c.enabled).length)

// 备选模型多选辅助
function isFallbackSelected(modelValue) {
  const current = getDraftValue('LITELLM_FALLBACK_MODELS') || ''
  const list = current.split(',').map(m => m.trim()).filter(Boolean)
  return list.includes(modelValue)
}

function toggleFallbackModel(modelValue, checked) {
  const current = getDraftValue('LITELLM_FALLBACK_MODELS') || ''
  const list = current.split(',').map(m => m.trim()).filter(Boolean)
  if (checked) {
    if (!list.includes(modelValue)) list.push(modelValue)
  } else {
    const idx = list.indexOf(modelValue)
    if (idx >= 0) list.splice(idx, 1)
  }
  setDraft('LITELLM_FALLBACK_MODELS', list.join(','))
}

// 运行时参数：在 dsaItems 中查找单个 key
function findDsaItem(key) {
  return (dsaItems.value || []).find(i => i.key === key)
}

const temperatureDisplay = computed(() => {
  const v = getDraftValue('LLM_TEMPERATURE')
  return v !== undefined && v !== '' ? parseFloat(v).toFixed(1) : '0.7'
})

// 从已配置渠道中收集所有可用模型（protocol/model 格式）
const allChannelModels = computed(() => {
  const result = []
  for (const ch of channels.value) {
    if (!ch.models) continue
    const models = ch.models.split(',').map(m => m.trim()).filter(Boolean)
    const protocol = ch.protocol || 'openai'
    for (const model of models) {
      // 如果模型已包含 / 前缀则原样使用，否则加上 protocol/
      const fullName = model.includes('/') ? model : `${protocol}/${model}`
      result.push({ label: `${model}  (${ch.name})`, value: fullName })
    }
  }
  return result
})

// 这些 key 已在 AI 模型编辑器中手动管理，不再显示在通用字段列表中
const AI_MODEL_MANAGED_KEYS = new Set([
  'LITELLM_MODEL', 'AGENT_LITELLM_MODEL', 'LITELLM_FALLBACK_MODELS',
  'VISION_MODEL', 'LLM_TEMPERATURE', 'LITELLM_CONFIG',
])

async function saveChannels() {
  isSavingChannels.value = true
  try {
    const items = []
    const names = channels.value.map(c => c.name).filter(Boolean)
    items.push({ key: 'LLM_CHANNELS', value: names.join(',') })
    for (const ch of channels.value) {
      if (!ch.name) continue
      const prefix = `LLM_${ch.name.toUpperCase()}`
      items.push({ key: `${prefix}_PROTOCOL`, value: ch.protocol })
      items.push({ key: `${prefix}_BASE_URL`, value: ch.baseUrl })
      items.push({ key: `${prefix}_API_KEY`, value: ch.apiKey })
      items.push({ key: `${prefix}_MODELS`, value: ch.models })
      items.push({ key: `${prefix}_ENABLED`, value: ch.enabled ? 'true' : 'false' })
    }
    const body = toSnake({
      configVersion: dsaConfigVersion.value,
      maskToken: dsaMaskToken.value,
      reloadNow: true,
      items,
    })
    const resp = await fetch(`${baseUrl.value}/api/v1/system/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${resp.status}`)
    }
    showToast('success', '渠道配置已保存')
    channelsDirty.value = false
    await loadDsaConfig()
  } catch (e) {
    showToast('error', `保存失败: ${e.message}`)
  } finally {
    isSavingChannels.value = false
  }
}

async function testChannel(idx) {
  const ch = channels.value[idx]
  ch.testing = true
  ch.testResult = null
  try {
    const resp = await fetch(`${baseUrl.value}/api/v1/system/config/llm/test-channel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: ch.name,
        protocol: ch.protocol,
        base_url: ch.baseUrl,
        api_key: ch.apiKey,
        models: ch.models ? ch.models.split(',').map(m => m.trim()).filter(Boolean) : [],
        enabled: ch.enabled,
      }),
    })
    const data = toCamel(await resp.json())
    ch.testResult = {
      ok: data.success ?? resp.ok,
      message: data.message || (resp.ok ? '连接成功' : '连接失败'),
    }
  } catch (e) {
    ch.testResult = { ok: false, message: e.message || '请求失败' }
  } finally {
    ch.testing = false
  }
}

async function discoverModels(idx) {
  const ch = channels.value[idx]
  ch.discovering = true
  ch.testResult = null
  try {
    const resp = await fetch(`${baseUrl.value}/api/v1/system/config/llm/discover-models`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: ch.name,
        protocol: ch.protocol,
        base_url: ch.baseUrl,
        api_key: ch.apiKey,
      }),
    })
    const data = toCamel(await resp.json())
    if (data.models && data.models.length > 0) {
      ch.models = data.models.join(',')
      channelsDirty.value = true
      ch.testResult = { ok: true, message: `发现 ${data.models.length} 个模型` }
    } else {
      ch.testResult = { ok: false, message: data.message || '未发现模型' }
    }
  } catch (e) {
    ch.testResult = { ok: false, message: e.message || '请求失败' }
  } finally {
    ch.discovering = false
  }
}

// =============================
// 数据源 & 新闻源渠道管理
// =============================
let dsNextId = 1
let nsNextId = 1
const dsListRef = ref(null)
const nsListRef = ref(null)
let dsSortable = null
let nsSortable = null

// 已在渠道编辑器管理的 key 集合
const DATA_SOURCE_MANAGED_KEYS = new Set([
  'REALTIME_SOURCE_PRIORITY',
  'ENABLE_REALTIME_TECHNICAL_INDICATORS', 'ENABLE_REALTIME_QUOTE', 'ENABLE_CHIP_DISTRIBUTION',
  'TUSHARE_TOKEN', 'TICKFLOW_API_KEY',
  'PYTDX_HOST', 'PYTDX_PORT', 'PYTDX_SERVERS',
  'LONGBRIDGE_APP_KEY', 'LONGBRIDGE_APP_SECRET', 'LONGBRIDGE_ACCESS_TOKEN',
  'BINANCE_API_KEY', 'BINANCE_API_SECRET',
  'OKX_API_KEY', 'OKX_SECRET_KEY', 'OKX_PASSPHRASE',
  'BOCHA_API_KEYS', 'ANSPIRE_API_KEYS', 'TAVILY_API_KEYS', 'SERPAPI_API_KEYS',
  'BRAVE_API_KEYS', 'MINIMAX_API_KEYS', 'SEARXNG_BASE_URLS', 'SEARXNG_PUBLIC_INSTANCES_ENABLED',
  'NEWS_MAX_AGE_DAYS', 'NEWS_STRATEGY_PROFILE', 'BIAS_THRESHOLD',
])

// 计算属性：可添加的预设（排除已添加的）
const availableDsPresets = computed(() => {
  const existing = new Set(dsChannels.value.map(c => c.preset))
  const result = {}
  for (const [k, v] of Object.entries(dataSourcePresets)) {
    if (!existing.has(k)) result[k] = v
  }
  return result
})

const availableNsPresets = computed(() => {
  const existing = new Set(nsChannels.value.map(c => c.preset))
  const result = {}
  for (const [k, v] of Object.entries(newsSourcePresets)) {
    if (!existing.has(k)) result[k] = v
  }
  return result
})

const enabledDsCount = computed(() => dsChannels.value.filter(c => c.enabled).length)
const enabledNsCount = computed(() => nsChannels.value.filter(c => c.enabled).length)

// 高级参数（data_source 中不被管理的项）
const dsAdvancedItems = computed(() => {
  const items = itemsByCategory.value['data_source'] || []
  return items.filter(i => !DATA_SOURCE_MANAGED_KEYS.has(i.key))
})

function getDsLabel(preset) {
  return dataSourcePresets[preset]?.label || preset
}
function getDsPresetFields(preset) {
  return dataSourcePresets[preset]?.fields || []
}
function getDsPresetFieldLabel(preset, idx) {
  const labels = dataSourcePresets[preset]?.fieldLabels
  if (labels && labels[idx]) return labels[idx]
  const fields = dataSourcePresets[preset]?.fields
  return fields?.[idx] || ''
}
function getDsPresetOptional(preset) {
  return dataSourcePresets[preset]?.optional || false
}
function getNsLabel(preset) {
  return newsSourcePresets[preset]?.label || preset
}

function dsAuthBadgeClass(ch) {
  if (ch.authType === 'none') return 'badge-free'
  if (ch.authType === 'apiKey' && ch.credentials.apiKey) return 'badge-ok'
  if (ch.authType === 'token' && ch.credentials.token) return 'badge-ok'
  if (ch.authType === 'server' && ch.credentials.host) return 'badge-ok'
  if (ch.authType === 'multi') {
    const preset = dataSourcePresets[ch.preset]
    if (preset?.optional) return ch.credentials[preset.fields?.[0]] ? 'badge-ok' : 'badge-free'
    return ch.credentials[preset?.fields?.[0]] ? 'badge-ok' : 'badge-warn'
  }
  return 'badge-warn'
}
function dsAuthBadgeText(ch) {
  if (ch.authType === 'none') return '免费'
  if (ch.authType === 'apiKey') return ch.credentials.apiKey ? '✓Key' : '⚠Key'
  if (ch.authType === 'token') return ch.credentials.token ? '✓Token' : '⚠Token'
  if (ch.authType === 'server') return ch.credentials.host ? '✓服务器' : '⚠服务器'
  if (ch.authType === 'multi') {
    const preset = dataSourcePresets[ch.preset]
    const firstField = preset?.fields?.[0]
    if (preset?.optional) return ch.credentials[firstField] ? '✓已配置' : '可选'
    return ch.credentials[firstField] ? '✓已配置' : '⚠未配置'
  }
  return ''
}
function nsAuthBadgeClass(ch) {
  if (ch.authType === 'none') return 'badge-free'
  if (ch.authType === 'apiKey' && ch.credentials.apiKeys) return 'badge-ok'
  if (ch.authType === 'url' && ch.credentials.baseUrls) return 'badge-ok'
  return 'badge-warn'
}
function nsAuthBadgeText(ch) {
  if (ch.authType === 'none') return '自动'
  if (ch.authType === 'apiKey') return ch.credentials.apiKeys ? '✓Key' : '⚠Key'
  if (ch.authType === 'url') return ch.credentials.baseUrls ? '✓URL' : '⚠URL'
  return ''
}

function addDsChannel() {
  const pk = dsAddPresetKey.value
  if (!pk) return
  const preset = dataSourcePresets[pk]
  if (!preset) return
  dsChannels.value.push(reactive({
    id: dsNextId++,
    preset: pk,
    authType: preset.authType,
    enabled: true,
    showKey: false,
    credentials: reactive({}),
  }))
  dsChannelsDirty.value = true
  dsAddPresetKey.value = ''
  nextTick(initDsSortable)
}

function addNsChannel() {
  const pk = nsAddPresetKey.value
  if (!pk) return
  const preset = newsSourcePresets[pk]
  if (!preset) return
  nsChannels.value.push(reactive({
    id: nsNextId++,
    preset: pk,
    authType: preset.authType,
    enabled: true,
    showKey: false,
    credentials: reactive({}),
  }))
  nsChannelsDirty.value = true
  nsAddPresetKey.value = ''
  nextTick(initNsSortable)
}

function removeDsChannel(idx) {
  dsChannels.value.splice(idx, 1)
  dsChannelsDirty.value = true
}
function removeNsChannel(idx) {
  nsChannels.value.splice(idx, 1)
  nsChannelsDirty.value = true
}

// 从后端配置反推渠道列表
function parseDsChannels() {
  const allItems = new Map(dsaItems.value.map(i => [i.key, String(i.value ?? '')]))
  const priorityStr = allItems.get('REALTIME_SOURCE_PRIORITY') || 'tencent,akshare_sina,efinance,akshare_em'
  const priorityList = priorityStr.split(',').map(s => s.trim()).filter(Boolean)

  // 把优先级列表中的子源映射回渠道
  const channelOrder = []
  const seen = new Set()
  for (const src of priorityList) {
    let channelId = null
    if (['tencent', 'akshare_sina', 'akshare_em'].includes(src)) channelId = 'akshare'
    else if (src === 'efinance') channelId = 'efinance'
    else if (src === 'tushare') channelId = 'tushare'
    else if (src === 'tickflow') channelId = 'tickflow'
    else if (src === 'pytdx') channelId = 'pytdx'
    else if (src === 'longbridge') channelId = 'longbridge'
    else if (src === 'binance') channelId = 'binance'
    else if (src === 'okx') channelId = 'okx'
    if (channelId && !seen.has(channelId)) {
      seen.add(channelId)
      channelOrder.push(channelId)
    }
  }
  // 补充默认渠道
  for (const [k, v] of Object.entries(dataSourcePresets)) {
    if (v.defaultEnabled && !seen.has(k)) {
      seen.add(k)
      channelOrder.push(k)
    }
  }

  dsChannels.value = channelOrder.map(pk => {
    const preset = dataSourcePresets[pk]
    if (!preset) return null
    const creds = reactive({})
    // 读取凭证
    if (preset.authType === 'apiKey' && preset.keys) {
      creds.apiKey = allItems.get(preset.keys[0]) || ''
    } else if (preset.authType === 'token' && preset.keys) {
      creds.token = allItems.get(preset.keys[0]) || ''
    } else if (preset.authType === 'server' && preset.keys) {
      creds.host = allItems.get(preset.keys[0]) || ''
      creds.port = allItems.get(preset.keys[1]) || ''
      creds.servers = allItems.get(preset.keys[2]) || ''
    } else if (preset.authType === 'multi' && preset.keys && preset.fields) {
      preset.fields.forEach((fieldName, i) => {
        creds[fieldName] = allItems.get(preset.keys[i]) || ''
      })
    }
    // 判断是否启用：在 priority 列表中存在
    const enabled = preset.defaultEnabled || (preset.subSources
      ? preset.subSources.some(s => priorityList.includes(s))
      : priorityList.includes(pk))
    return reactive({
      id: dsNextId++,
      preset: pk,
      authType: preset.authType,
      enabled,
      showKey: false,
      credentials: creds,
    })
  }).filter(Boolean)
  dsChannelsDirty.value = false
}

function parseNsChannels() {
  const allItems = new Map(dsaItems.value.map(i => [i.key, String(i.value ?? '')]))
  const list = []
  for (const [pk, preset] of Object.entries(newsSourcePresets)) {
    if (!preset.keys) continue
    const keyVal = allItems.get(preset.keys[0]) || ''
    // 有值或是 boolean(enabled) 时加入列表
    if (preset.authType === 'none') {
      // SearXNG 公共实例
      if (keyVal === 'true') {
        list.push({ pk, val: keyVal })
      }
    } else if (keyVal) {
      list.push({ pk, val: keyVal })
    }
  }
  nsChannels.value = list.map(({ pk, val }) => {
    const preset = newsSourcePresets[pk]
    const creds = reactive({})
    if (preset.authType === 'apiKey') creds.apiKeys = val
    else if (preset.authType === 'url') creds.baseUrls = val
    return reactive({
      id: nsNextId++,
      preset: pk,
      authType: preset.authType,
      enabled: true,
      showKey: false,
      credentials: creds,
    })
  })
  nsChannelsDirty.value = false
}

// 保存数据源 & 新闻源渠道
async function saveDsNsChannels() {
  isSavingDsChannels.value = true
  isSavingNsChannels.value = true
  try {
    const items = []

    // ─── 数据源 ───
    // 构建 REALTIME_SOURCE_PRIORITY
    const prioritySources = []
    for (const ch of dsChannels.value) {
      if (!ch.enabled) continue
      const preset = dataSourcePresets[ch.preset]
      if (preset?.subSources) {
        prioritySources.push(...preset.subSources)
      } else {
        prioritySources.push(ch.preset)
      }
    }
    items.push({ key: 'REALTIME_SOURCE_PRIORITY', value: prioritySources.join(',') })

    // 凭证
    for (const ch of dsChannels.value) {
      const preset = dataSourcePresets[ch.preset]
      if (!preset?.keys) continue
      if (ch.authType === 'apiKey') {
        items.push({ key: preset.keys[0], value: ch.credentials.apiKey || '' })
      } else if (ch.authType === 'token') {
        items.push({ key: preset.keys[0], value: ch.credentials.token || '' })
      } else if (ch.authType === 'server') {
        items.push({ key: preset.keys[0], value: ch.credentials.host || '' })
        items.push({ key: preset.keys[1], value: ch.credentials.port || '' })
        items.push({ key: preset.keys[2], value: ch.credentials.servers || '' })
      } else if (ch.authType === 'multi' && preset.fields) {
        preset.fields.forEach((fieldName, i) => {
          items.push({ key: preset.keys[i], value: ch.credentials[fieldName] || '' })
        })
      }
    }

    // 开关
    items.push({ key: 'ENABLE_REALTIME_TECHNICAL_INDICATORS', value: getDraftValue('ENABLE_REALTIME_TECHNICAL_INDICATORS') })
    items.push({ key: 'ENABLE_REALTIME_QUOTE', value: getDraftValue('ENABLE_REALTIME_QUOTE') })
    items.push({ key: 'ENABLE_CHIP_DISTRIBUTION', value: getDraftValue('ENABLE_CHIP_DISTRIBUTION') })

    // ─── 新闻源 ───
    for (const ch of nsChannels.value) {
      const preset = newsSourcePresets[ch.preset]
      if (!preset?.keys) continue
      if (ch.authType === 'apiKey') {
        items.push({ key: preset.keys[0], value: ch.enabled ? (ch.credentials.apiKeys || '') : '' })
      } else if (ch.authType === 'url') {
        items.push({ key: preset.keys[0], value: ch.enabled ? (ch.credentials.baseUrls || '') : '' })
      } else if (ch.authType === 'none') {
        // SearXNG 公共实例
        items.push({ key: preset.keys[0], value: ch.enabled ? 'true' : 'false' })
      }
    }

    // 新闻参数
    items.push({ key: 'NEWS_MAX_AGE_DAYS', value: getDraftValue('NEWS_MAX_AGE_DAYS') })
    items.push({ key: 'NEWS_STRATEGY_PROFILE', value: getDraftValue('NEWS_STRATEGY_PROFILE') })
    items.push({ key: 'BIAS_THRESHOLD', value: getDraftValue('BIAS_THRESHOLD') })

    const body = toSnake({
      configVersion: dsaConfigVersion.value,
      maskToken: dsaMaskToken.value,
      reloadNow: true,
      items,
    })
    const resp = await fetch(`${baseUrl.value}/api/v1/system/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${resp.status}`)
    }
    showToast('success', '数据源配置已保存')
    dsChannelsDirty.value = false
    nsChannelsDirty.value = false
    await loadDsaConfig()
  } catch (e) {
    showToast('error', `保存失败: ${e.message}`)
  } finally {
    isSavingDsChannels.value = false
    isSavingNsChannels.value = false
  }
}

// 拖拽排序
function initDsSortable() {
  if (dsSortable) dsSortable.destroy()
  const el = dsListRef.value
  if (!el) return
  dsSortable = Sortable.create(el, {
    handle: '.drag-handle',
    animation: 150,
    ghostClass: 'sortable-ghost',
    onEnd(evt) {
      const arr = dsChannels.value
      const [moved] = arr.splice(evt.oldIndex, 1)
      arr.splice(evt.newIndex, 0, moved)
      dsChannelsDirty.value = true
    },
  })
}

function initNsSortable() {
  if (nsSortable) nsSortable.destroy()
  const el = nsListRef.value
  if (!el) return
  nsSortable = Sortable.create(el, {
    handle: '.drag-handle',
    animation: 150,
    ghostClass: 'sortable-ghost',
    onEnd(evt) {
      const arr = nsChannels.value
      const [moved] = arr.splice(evt.oldIndex, 1)
      arr.splice(evt.newIndex, 0, moved)
      nsChannelsDirty.value = true
    },
  })
}

// =============================
// 初始化
// =============================
onMounted(async () => {
  // 加载本地设置
  localConfig.theme = localStorage.getItem('theme') || 'dark'
  localConfig.closeWarning = localStorage.getItem('close-warning') === 'true'
  localConfig.maxTabs = parseInt(localStorage.getItem('max-tabs') || '10', 10)

  if (window.electronAPI?.getWorkspacePath) {
    localConfig.workspacePath = await window.electronAPI.getWorkspacePath() || ''
  }
  if (window.electronAPI?.getDataSource) {
    localConfig.dataSource = await window.electronAPI.getDataSource() || 'binance'
  }
  if (window.electronAPI?.getExternalEditor) {
    const editor = await window.electronAPI.getExternalEditor() || 'auto'
    if (['auto', 'vscode', 'cursor', 'custom'].includes(editor)) {
      localConfig.externalEditor = editor
    } else {
      // 自定义路径
      localConfig.externalEditor = 'custom'
      localConfig.externalEditorPath = editor
    }
  }

  // 加载 DSA 本地配置
  await loadDsaLocal()

  // 加载服务端连接配置
  await loadServerConfig()

  // 加载 DSA 服务状态
  if (window.electronAPI?.getDsaStatus) {
    const info = await window.electronAPI.getDsaStatus()
    dsaStatus.value = info.status
    dsaServerRunning.value = info.status === 'running'
    if (info.status === 'running') {
      statusDesc.value = `服务运行在 ${baseUrl.value}`
    }
  }

  // 监听状态变化
  if (window.electronAPI?.onDsaStatusChanged) {
    window.electronAPI.onDsaStatusChanged(updateStatusFromEvent)
  }

  // 如果服务已在运行，加载后端配置与客户端认证状态
  if (dsaServerRunning.value) {
    await loadDsaConfig()
    loadClientAuthStatus()
  }
})

onUnmounted(() => {
  clearTimeout(toastTimer)
})

// 当切换到 DSA 分类且数据未加载时自动加载
watch(activeCategory, (cat) => {
  if (DSA_CATEGORIES.includes(cat) && dsaServerRunning.value && dsaItems.value.length === 0) {
    loadDsaConfig()
  }
})
</script>

<style scoped>
* {
  box-sizing: border-box;
}

.settings-page {
  color: #ccc;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 14px;
}

/* Toast — 浮动在内容上方 */
.toast-bar {
  position: fixed;
  top: 8px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 1000;
  padding: 0;
}
.toast {
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 13px;
}
.toast.success {
  background: rgba(46, 160, 67, 0.15);
  color: #2ea043;
  border: 1px solid rgba(46, 160, 67, 0.3);
}
.toast.error {
  background: rgba(218, 54, 51, 0.15);
  color: #da3633;
  border: 1px solid rgba(218, 54, 51, 0.3);
}

/* 左侧面板 — 覆盖公共样式的局部调整 */
.category-nav {
  padding: 0;
}
.nav-group-label {
  padding: 12px 16px 6px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  color: #666;
  letter-spacing: 0.5px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  cursor: pointer;
  border-left: 3px solid transparent;
  position: relative;
  transition: background 0.15s;
}
.nav-item:hover {
  background: rgba(255, 255, 255, 0.04);
}
.nav-item.active {
  background: rgba(74, 158, 255, 0.08);
  border-left-color: #4a9eff;
}
.nav-icon {
  font-size: 16px;
  width: 22px;
  text-align: center;
  flex-shrink: 0;
}
.nav-text {
  flex: 1;
  min-width: 0;
}
.nav-title {
  font-size: 13px;
  font-weight: 500;
  color: #ddd;
}
.nav-item.active .nav-title {
  color: #4a9eff;
}
.nav-desc {
  font-size: 11px;
  color: #666;
  margin-top: 2px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.nav-badge {
  position: absolute;
  top: 10px;
  right: 12px;
  background: rgba(255, 255, 255, 0.1);
  color: #aaa;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
}

/* 右侧内容 */
.settings-content {
  overflow-y: auto;
  padding: 20px 24px;
}

/* 左侧面板底部操作按钮 */
.side-panel-footer .panel-btn {
  font-size: 12px;
}
.side-panel-footer .panel-btn.btn-primary {
  background: #0e639c;
  color: #fff;
  border-color: #0e639c;
}
.side-panel-footer .panel-btn.btn-primary:hover:not(:disabled) {
  background: #1177bb;
}
.side-panel-footer .panel-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 卡片 */
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

/* 设置分组卡片 */
.settings-group {
  background: #2a2a2b;
  border: 1px solid #383838;
  border-radius: 8px;
  padding: 16px 18px;
  margin-bottom: 14px;
}
.settings-group:last-child {
  margin-bottom: 0;
}
.settings-group-title {
  font-size: 14px;
  font-weight: 600;
  color: #e0e0e0;
  margin-bottom: 2px;
}
.settings-group-desc {
  font-size: 12px;
  color: #777;
  margin-bottom: 14px;
}
.settings-group-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.settings-group-body .field-item {
  margin-bottom: 0;
}

/* 字段 */
.field-item {
  margin-bottom: 20px;
}
.field-item:last-child {
  margin-bottom: 0;
}
.field-item > label,
.field-label-row > label {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  color: #ccc;
  font-weight: 500;
}
.field-label-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.field-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.flex-1 {
  flex: 1;
}
.field-input {
  width: 100%;
  padding: 7px 12px;
  background: #1a1a1a;
  border: 1px solid #444;
  border-radius: 6px;
  color: #fff;
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s;
}
.field-input:focus {
  border-color: #4a9eff;
}
.field-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.field-textarea {
  min-height: 72px;
  resize: vertical;
}
.field-desc {
  font-size: 11px;
  color: #666;
  margin-top: 4px;
}
.checkbox-row {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.checkbox-row input[type="checkbox"] {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

/* badge */
.badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
}
.badge.sensitive {
  background: rgba(210, 153, 34, 0.15);
  color: #d29922;
}
.badge.readonly {
  background: rgba(150, 150, 150, 0.15);
  color: #999;
}

/* 按钮 */
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
.btn-secondary {
  background: #2d2d2d;
  color: #ccc;
  border-color: #444;
}
.btn-secondary:hover:not(:disabled) {
  background: #3a3a3a;
}
.btn-browse {
  background: #2d2d2d;
  color: #ccc;
  border-color: #444;
  padding: 7px 12px;
}
.btn-browse:hover {
  background: #3a3a3a;
}
.btn-start {
  background: #2ea043;
  color: #fff;
  border-color: #2ea043;
}
.btn-start:hover {
  background: #3ab554;
}
.btn-stop {
  background: #da3633;
  color: #fff;
  border-color: #da3633;
}
.btn-stop:hover {
  background: #e74c3c;
}
.btn-icon {
  padding: 4px 8px;
  font-size: 14px;
  line-height: 1;
}
.btn-danger-icon {
  background: transparent;
  color: #da3633;
  border-color: transparent;
}
.btn-danger-icon:hover {
  background: rgba(218, 54, 51, 0.15);
}

/* 状态行 */
.status-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-text {
  font-size: 14px;
  color: #ccc;
}

/* 渠道编辑器 */
.llm-editor {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.llm-group {
  background: #252526;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  padding: 14px;
}
.llm-group-title {
  font-size: 14px;
  font-weight: 600;
  color: #ddd;
  margin-bottom: 10px;
}
.channel-add-bar {
  display: flex;
  align-items: center;
  gap: 8px;
}
.channel-add-select {
  width: 200px;
}
.channel-count-badge {
  margin-left: auto;
  font-size: 12px;
  color: #888;
  background: #333;
  padding: 2px 8px;
  border-radius: 10px;
}
.channel-empty-hint {
  font-size: 13px;
  color: #666;
  padding: 8px 0;
}
.channels-wrapper {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.channel-card {
  background: #1e1e1e;
  border: 1px solid #3a3a3a;
  border-radius: 6px;
  overflow: hidden;
  transition: border-color 0.2s;
}
.channel-card.expanded {
  border-color: #4a9eff;
}
.channel-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}
.channel-row:hover {
  background: #2a2a2a;
}
.channel-expand-arrow {
  font-size: 10px;
  color: #666;
  transition: transform 0.2s;
  display: inline-block;
  width: 14px;
  flex-shrink: 0;
}
.channel-expand-arrow.open {
  transform: rotate(90deg);
}
.channel-enable-check {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}
.channel-enable-check input[type="checkbox"] {
  margin: 0;
}
.channel-row-name {
  font-size: 13px;
  color: #ddd;
  font-weight: 500;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.channel-row-badge {
  font-size: 11px;
  color: #999;
  background: #333;
  padding: 1px 6px;
  border-radius: 3px;
  flex-shrink: 0;
}
.channel-row-models {
  font-size: 11px;
  color: #777;
  flex-shrink: 0;
}
.channel-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.channel-status-dot.status-ok { background: #2ea043; }
.channel-status-dot.status-error { background: #da3633; }
.channel-status-dot.status-warn { background: #d29922; }
.channel-status-dot.status-idle { background: #555; }
.channel-row-warn {
  font-size: 11px;
  color: #d29922;
  flex-shrink: 0;
}
.channel-row-delete {
  margin-left: auto;
  flex-shrink: 0;
}
.channel-body {
  padding: 12px;
  border-top: 1px solid #3a3a3a;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.channel-field label {
  display: block;
  font-size: 12px;
  color: #999;
  margin-bottom: 4px;
}
.channel-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 4px;
}
.test-result {
  font-size: 12px;
}
.test-result.success {
  color: #2ea043;
}
.test-result.error {
  color: #da3633;
}
.channel-save-row {
  margin-top: 4px;
}
/* 运行时参数 */
.runtime-params-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.temperature-field {
  margin-top: 12px;
}
.temperature-value {
  font-size: 13px;
  color: #4a9eff;
  font-weight: 600;
  margin-left: auto;
}
.temperature-slider {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 6px;
  border-radius: 3px;
  background: linear-gradient(to right, #2ea043, #d29922, #da3633);
  outline: none;
  margin: 8px 0 4px;
}
.temperature-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid #4a9eff;
  cursor: pointer;
  box-shadow: 0 1px 4px rgba(0,0,0,0.3);
}
.temperature-slider::-moz-range-thumb {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid #4a9eff;
  cursor: pointer;
}
.temperature-labels {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #666;
}
/* 备选模型多选 */
.fallback-model-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 140px;
  overflow-y: auto;
  padding: 6px 8px;
  background: #1e1e1e;
  border: 1px solid #3a3a3a;
  border-radius: 4px;
}
.fallback-model-option {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #ccc;
  cursor: pointer;
  padding: 2px 0;
}
.fallback-model-option input[type="checkbox"] {
  margin: 0;
}
.fallback-model-option:hover {
  color: #fff;
}

/* 空状态 / 加载 / 错误 */
.empty-state,
.loading-state,
.error-state {
  text-align: center;
  padding: 60px 20px;
  color: #888;
}
.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
}
.empty-title,
.error-title {
  font-size: 16px;
  font-weight: 500;
  color: #ccc;
  margin-bottom: 8px;
}
.empty-desc,
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
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 对话框 */
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

/* 滚动条 */
::-webkit-scrollbar {
  width: 8px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: #444;
  border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover {
  background: #555;
}

/* 数据源编辑器 */
.ds-editor {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.ds-switches {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid #383838;
}
.ds-params {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid #383838;
}
.ds-params .channel-field {
  min-width: 140px;
}
.drag-handle {
  cursor: grab;
  color: #666;
  font-size: 14px;
  padding: 0 2px;
  user-select: none;
  flex-shrink: 0;
}
.drag-handle:active {
  cursor: grabbing;
}
.sortable-ghost {
  opacity: 0.4;
  background: #333;
}
.badge-free {
  font-size: 11px;
  color: #2ea043;
  background: rgba(46, 160, 67, 0.15);
  padding: 1px 6px;
  border-radius: 3px;
  flex-shrink: 0;
}
.badge-ok {
  font-size: 11px;
  color: #2ea043;
  background: rgba(46, 160, 67, 0.15);
  padding: 1px 6px;
  border-radius: 3px;
  flex-shrink: 0;
}
.badge-warn {
  font-size: 11px;
  color: #d29922;
  background: rgba(210, 153, 34, 0.15);
  padding: 1px 6px;
  border-radius: 3px;
  flex-shrink: 0;
}

/* 客户端账号区 */
.kv-inline-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 0;
  font-size: 13px;
}
.kv-inline-label {
  min-width: 80px;
  color: #888;
  flex-shrink: 0;
}
.kv-inline-value {
  color: #ddd;
}
.tier-badge {
  display: inline-block;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 600;
}
.tier-free {
  color: #999;
  background: rgba(150, 150, 150, 0.2);
}
.tier-pro {
  color: #4a9eff;
  background: rgba(74, 158, 255, 0.15);
}
.tier-enterprise {
  color: #d29922;
  background: rgba(210, 153, 34, 0.15);
}
code {
  background: #1a1a1a;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 12px;
  color: #d29922;
}
</style>
