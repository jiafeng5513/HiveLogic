const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  getVersion: () => process.versions,
  getPlatform: () => process.platform,
  // 通知主进程渲染进程已就绪
  rendererReady: () => ipcRenderer.send('renderer-ready'),

  // 模式切换
  switchMode: (mode) => ipcRenderer.send('switch-mode', mode),
  onModeSwitched: (callback) => ipcRenderer.on('mode-switched', (event, data) => callback(data)),

  // 标签页相关 API
  createNewTab: () => ipcRenderer.send('new-tab'),
  switchTab: (viewId) => ipcRenderer.send('switch-tab', viewId),
  closeTab: (viewId) => ipcRenderer.send('close-tab', viewId),
  openContextMenu: (viewId) => ipcRenderer.send('show-context-menu', viewId),
  onTabCreated: (callback) => ipcRenderer.on('tab-created', callback),
  onTabClosed: (callback) => ipcRenderer.on('tab-closed', callback),
  onContextMenuPushed: (callback) =>
    ipcRenderer.on('context-menu-action', (event, data) => callback(data)),

  // 添加标签限制提示的监听器
  onTabLimit: (callback) => ipcRenderer.on('tab-limit', (event, message) => callback(message)),

  // 添加加载状态监听
  onTabLoading: (callback) =>
    ipcRenderer.on('tab-loading', (event, viewId, isLoading) => callback(viewId, isLoading)),

  // 添加标题更新监听
  onTabTitleUpdated: (callback) =>
    ipcRenderer.on('tab-title-updated', (event, viewId, title) => callback(event, viewId, title)),

  // 打开开发者工具
  openDevTools: () => ipcRenderer.send('open-dev-tools-in-new-window'),
  toggleDevTools: () => ipcRenderer.send('toggle-devtools'),
  onDevToolsStateChanged: (callback) =>
    ipcRenderer.on('devtools-state-changed', (event, isOpen) => callback(isOpen)),

  // 关闭所有图表页面
  closeAllChartTabs: () => ipcRenderer.send('close-all-chart-tabs'),

  // 标的浏览器操作
  openSymbolInChart: (symbolInfo) => ipcRenderer.send('open-symbol-in-chart', symbolInfo),
  openSymbolAnalysis: (symbolInfo) => ipcRenderer.send('open-symbol-analysis', symbolInfo),
  switchToPinnedTab: (tabType) => ipcRenderer.send('switch-to-pinned-tab', tabType),
  onLoadSymbol: (callback) => ipcRenderer.on('load-symbol', (event, data) => callback(data)),
  onAnalyzeSymbol: (callback) =>
    ipcRenderer.on('analyze-symbol', (event, data) => callback(data)),

  // K 线图标注 (Agent → Chart)
  onAnnotationsUpdate: (callback) =>
    ipcRenderer.on('chart:annotations-update', (event, data) => callback(data)),

  // 数据源设置（跨 partition 共享）
  getDataSource: () => ipcRenderer.invoke('get-data-source'),
  setDataSource: (dataSource) => ipcRenderer.send('set-data-source', dataSource),

  // Agent 面板切换
  toggleAgentPanel: (visible) => ipcRenderer.send('toggle-agent-panel', visible),

  // Agent 面板调整宽度
  resizeAgentPanel: (width) => ipcRenderer.send('resize-agent-panel', width),

  // Agent Window (独立窗口)
  openAgentWindow: (options) => ipcRenderer.invoke('agent:open-window', options),
  toggleAgentWindow: (options) => ipcRenderer.invoke('agent:toggle-window', options),
  syncAgentResult: (data) => ipcRenderer.invoke('agent:sync-result', data),
  onAgentResult: (callback) =>
    ipcRenderer.on('sidebar:agent-result', (event, data) => callback(data)),

  // 通用 invoke (供 Vue 组件使用)
  invoke: (channel, ...args) => ipcRenderer.invoke(channel, ...args),

  // 工作区目录
  getWorkspacePath: () => ipcRenderer.invoke('get-workspace-path'),
  setWorkspacePath: () => ipcRenderer.invoke('set-workspace-path'),
  readDirectory: (dirPath) => ipcRenderer.invoke('read-directory', dirPath),
  readFile: (filePath) => ipcRenderer.invoke('read-file', filePath),
  openFile: (filePath) => ipcRenderer.send('open-file', filePath),
  onFileOpened: (callback) => ipcRenderer.on('file-opened', (event, data) => callback(data)),
  onTabActivated: (callback) =>
    ipcRenderer.on('tab-activated', (event, viewId) => callback(viewId)),

  // Python 编辑器 - 接收打开文件消息
  onOpenFileInEditor: (callback) =>
    ipcRenderer.on('open-file-in-editor', (event, filePath) => callback(filePath)),

  // 资源管理器面板
  toggleExplorerPanel: (visible) => ipcRenderer.send('toggle-explorer-panel', visible),
  resizeExplorerPanel: (width) => ipcRenderer.send('resize-explorer-panel', width),
  onSidePanelWidthChanged: (callback) =>
    ipcRenderer.on('side-panel-width-changed', (event, width) => callback(width)),
  onExplorerPanelVisibilityChanged: (callback) =>
    ipcRenderer.on('explorer-panel-visibility-changed', (event, visible) => callback(visible)),
  getSidePanelWidth: () => ipcRenderer.invoke('get-side-panel-width'),

  // 文件操作
  createFile: (filePath) => ipcRenderer.invoke('create-file', filePath),
  createFolder: (folderPath) => ipcRenderer.invoke('create-folder', folderPath),
  renameItem: (oldPath, newPath) => ipcRenderer.invoke('rename-item', oldPath, newPath),
  deleteItem: (targetPath) => ipcRenderer.invoke('delete-item', targetPath),
  moveItem: (srcPath, destDir) => ipcRenderer.invoke('move-item', srcPath, destDir),
  saveFile: (filePath, content) => ipcRenderer.invoke('save-file', filePath, content),
  exportPDF: (html, defaultFileName) => ipcRenderer.invoke('export-pdf', { html, defaultFileName }),

  // DSA (daily_stock_analysis) 集成
  getDsaConfig: () => ipcRenderer.invoke('get-dsa-config'),
  setDsaConfig: (config) => ipcRenderer.invoke('set-dsa-config', config),
  browsePythonPath: () => ipcRenderer.invoke('browse-python-path'),
  startDsaServer: () => ipcRenderer.invoke('start-dsa-server'),
  stopDsaServer: () => ipcRenderer.invoke('stop-dsa-server'),
  getDsaStatus: () => ipcRenderer.invoke('get-dsa-status'),
  checkDsaHealth: () => ipcRenderer.invoke('check-dsa-health'),
  onDsaStatusChanged: (callback) =>
    ipcRenderer.on('dsa-status-changed', (event, data) => callback(data)),

  getServerConfig: () => ipcRenderer.invoke('get-server-config'),
  setServerConfig: (config) => ipcRenderer.invoke('set-server-config', config),

  // 后端进度信息（状态栏用）
  onBackendProgress: (callback) =>
    ipcRenderer.on('backend-progress', (event, data) => callback(data)),

  // 终端面板 API
  terminalCreate: (options) => ipcRenderer.invoke('terminal-create', options),
  terminalInput: (id, data) => ipcRenderer.send('terminal-input', { id, data }),
  terminalResize: (id, cols, rows) => ipcRenderer.send('terminal-resize', { id, cols, rows }),
  terminalDestroy: (id) => ipcRenderer.send('terminal-destroy', { id }),
  terminalGetLogHistory: () => ipcRenderer.invoke('terminal-get-log-history'),
  onTerminalData: (callback) =>
    ipcRenderer.on('terminal-data', (event, payload) => callback(payload)),
  onTerminalExit: (callback) =>
    ipcRenderer.on('terminal-exit', (event, payload) => callback(payload)),
  toggleTerminalPanel: (visible, height) => ipcRenderer.send('toggle-terminal-panel', visible, height),
  resizeTerminalPanel: (height) => ipcRenderer.send('resize-terminal-panel', height),

  // 配置导入/导出
  exportConfig: (content, defaultFileName) =>
    ipcRenderer.invoke('export-config', content, defaultFileName),
  importConfig: () => ipcRenderer.invoke('import-config'),

  // K 线图标注
  onAnnotationsUpdate: (callback) =>
    ipcRenderer.on('chart:annotations-update', (event, data) => callback(data)),

  // 自定义指标
  openIndicatorEditor: (options) => ipcRenderer.invoke('indicator:open-editor', options),
  toggleIndicatorEditor: (options) => ipcRenderer.invoke('indicator:toggle-editor', options),
  getActiveIndicators: () => ipcRenderer.invoke('indicator:get-active-indicators'),
  listIndicators: () => ipcRenderer.invoke('indicator:list'),
  getExternalEditor: () => ipcRenderer.invoke('get-external-editor'),
  setExternalEditor: (editor) => ipcRenderer.invoke('set-external-editor', editor),
  onIndicatorCodeUpdated: (callback) =>
    ipcRenderer.on('indicator:code-updated', (event, data) => callback(data)),
  onIndicatorRemoved: (callback) =>
    ipcRenderer.on('indicator:removed', (event, data) => callback(data))
})
