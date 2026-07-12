import {
  app,
  shell,
  WebContentsView,
  BrowserWindow,
  ipcMain,
  Menu,
  session,
  dialog,
  globalShortcut
} from 'electron'
import { join, dirname } from 'path'
import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  readdirSync,
  statSync,
  unlinkSync,
  renameSync,
  rmSync
} from 'fs'
import { spawn, spawnSync } from 'child_process'
import { is, electronApp, optimizer } from '@electron-toolkit/utils'
import icon from '../../resources/hivelogic_logo.png?asset'
import terminalManager from './terminalManager'
import { initAgentWindowIPC, openAgentWindow } from './agentWindow'
import { initIndicatorManager, destroyIndicatorManager } from './indicatorManager'
import { initIndicatorEditorIPC } from './indicatorEditorWindow'

// 子进程输出解码：优先 UTF-8，GBK 兜底（中文 Windows 上 uv.exe 输出 GBK）
function decodeOutput(buffer) {
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(buffer)
  } catch {
    try {
      return new TextDecoder('gbk').decode(buffer)
    } catch {
      return buffer.toString('utf-8')
    }
  }
}

// 全局的变量参数
const ACTIVITY_BAR_WIDTH = 48 // VSCode 风格侧边栏宽度
const TITLE_BAR_HEIGHT = 30 // 标题栏高度
const TAB_BAR_HEIGHT = 36 // 标签栏高度
const STATUS_BAR_HEIGHT = 22 // 底部状态栏高度
const AGENT_PANEL_WIDTH = 350 // Agent 侧栏默认宽度
const EXPLORER_PANEL_WIDTH = 250 // 资源管理器默认宽度
let agentPanelVisible = true // Agent 侧栏是否可见
let currentAgentPanelWidth = AGENT_PANEL_WIDTH // Agent 侧栏当前宽度
let explorerPanelVisible = false // 左面板是否可见（开发模式:资源管理器, 交易模式:标的浏览器）
let currentExplorerPanelWidth = EXPLORER_PANEL_WIDTH // 左面板当前宽度
let mainWindow // 主进程的唯一窗口，所有tab都被它加载
let views = new Map() // 所有的view 对象，格式: { view: WebContentsView, type: string, title: string }
let activeViewId = null // 活动的view对象
let symbolBrowserView = null // 标的浏览器左面板视图（独立于 tabs）
let currentDataSource = 'binance' // 当前数据源设置（跨 partition 共享）
let terminalPanelVisible = false // 终端面板是否可见
let currentTerminalPanelHeight = 250 // 终端面板当前高度

// =====================
// 配置文件管理
// =====================
const configPath = join(app.getPath('userData'), 'hivelogic-config.json')

function readConfig() {
  try {
    if (existsSync(configPath)) {
      return JSON.parse(readFileSync(configPath, 'utf-8'))
    }
  } catch (e) {
    console.error('[Config] 读取配置失败:', e)
  }
  return {}
}

function writeConfig(config) {
  try {
    writeFileSync(configPath, JSON.stringify(config, null, 2), 'utf-8')
  } catch (e) {
    console.error('[Config] 写入配置失败:', e)
  }
}

function getDefaultWorkspacePath() {
  if (is.dev) {
    return join(app.getAppPath(), 'HiveLogicWorkSpace')
  }
  return join(dirname(app.getPath('exe')), 'HiveLogicWorkSpace')
}

function getWorkspacePath() {
  const config = readConfig()
  return config.workspacePath || getDefaultWorkspacePath()
}

function setWorkspacePath(newPath) {
  const config = readConfig()
  config.workspacePath = newPath
  writeConfig(config)
}

// =====================
// DSA (daily_stock_analysis) 配置管理
// =====================
function getDsaConfig() {
  const config = readConfig()
  return config.dsa || {}
}

function setDsaConfig(dsaConfig) {
  const config = readConfig()
  config.dsa = { ...config.dsa, ...dsaConfig }
  writeConfig(config)
}

function getBackendPath() {
  // 服务端代码位于仓库的 server/ 目录（与 client/ 同级）
  // 注意：这是开发期的临时本地桥接；Phase 1 解耦后改为可配置的远程服务端地址
  if (is.dev) {
    return join(app.getAppPath(), '..', 'server')
  }
  // 打包后 server/ 与 exe 同级
  return join(dirname(app.getPath('exe')), 'server')
}

// =====================
// 服务端连接配置管理（Phase 1.2）
// =====================
const DEFAULT_SERVER_CONFIG = {
  mode: 'local',          // 'local' | 'remote'
  remoteBaseUrl: '',      // 远程服务端地址，如 http://192.168.50.7:8100
  token: ''               // 访问令牌（Phase 5 启用，当前预留）
}

function getServerConfig() {
  const config = readConfig()
  return { ...DEFAULT_SERVER_CONFIG, ...(config.server || {}) }
}

function setServerConfig(serverConfig) {
  const config = readConfig()
  config.server = { ...DEFAULT_SERVER_CONFIG, ...(config.server || {}), ...serverConfig }
  writeConfig(config)
}

function isLocalMode() {
  return getServerConfig().mode === 'local'
}

// 生成 DSA 的 .env 文件（仅在不存在时创建，避免覆盖后端 API 已保存的配置）
function writeDsaEnvFile(dsaPath) {
  const envPath = join(dsaPath, '.env')
  if (existsSync(envPath)) {
    console.log('[DSA] .env 已存在，跳过初始化写入:', envPath)
    return true
  }

  const dsaConfig = getDsaConfig()
  const lines = []

  // LLM 配置
  if (dsaConfig.llmProvider && dsaConfig.llmApiKey) {
    const provider = dsaConfig.llmProvider
    if (provider === 'gemini') {
      lines.push(`GEMINI_API_KEY=${dsaConfig.llmApiKey}`)
    } else if (provider === 'deepseek') {
      lines.push(`DEEPSEEK_API_KEY=${dsaConfig.llmApiKey}`)
    } else if (provider === 'openai') {
      lines.push(`OPENAI_API_KEY=${dsaConfig.llmApiKey}`)
    } else if (provider === 'anthropic') {
      lines.push(`ANTHROPIC_API_KEY=${dsaConfig.llmApiKey}`)
    } else if (provider === 'aihubmix') {
      lines.push(`AIHUBMIX_KEY=${dsaConfig.llmApiKey}`)
    } else if (provider === 'ollama') {
      lines.push(`OLLAMA_API_BASE=${dsaConfig.llmApiKey || 'http://localhost:11434'}`)
    }
  }

  if (dsaConfig.llmModel) {
    lines.push(`LITELLM_MODEL=${dsaConfig.llmModel}`)
  }

  // 搜索引擎 API Key
  if (dsaConfig.searchApiKey) {
    lines.push(`TAVILY_API_KEYS=${dsaConfig.searchApiKey}`)
  }

  // Agent 模式
  lines.push('AGENT_MODE=true')
  lines.push('AGENT_SKILLS=all')

  // 端口配置
  const port = dsaConfig.port || 8100
  lines.push(`# FastAPI port: ${port}`)

  try {
    writeFileSync(envPath, lines.join('\n') + '\n', 'utf-8')
    console.log('[DSA] 已写入 .env 文件:', envPath)
    return true
  } catch (e) {
    console.error('[DSA] 写入 .env 文件失败:', e)
    return false
  }
}

// =====================
// FastAPI 子进程管理
// =====================
let fastApiProcess = null
let fastApiStatus = 'stopped' // 'stopped' | 'starting' | 'running' | 'error'
let fastApiPort = 8100

function getFastApiUrl() {
  return `http://127.0.0.1:${fastApiPort}`
}

// 向渲染进程广播后端进度信息
function broadcastBackendProgress(message, phase) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('backend-progress', { message, phase })
  }
}

async function startFastApiServer() {
  if (fastApiProcess) {
    console.log('[FastAPI] 服务已在运行中')
    return { success: true, status: 'running' }
  }

  const dsaConfig = getDsaConfig()
  const backendDir = getBackendPath()
  fastApiPort = dsaConfig.port || 8100

  if (!existsSync(backendDir)) {
    const msg = `后端目录不存在: ${backendDir}`
    console.error('[FastAPI]', msg)
    fastApiStatus = 'error'
    broadcastDsaStatus()
    return { success: false, error: msg }
  }

  const serverPy = join(backendDir, 'server.py')
  if (!existsSync(serverPy)) {
    const msg = `未找到 server.py: ${serverPy}`
    console.error('[FastAPI]', msg)
    fastApiStatus = 'error'
    broadcastDsaStatus()
    return { success: false, error: msg }
  }

  // 生成 .env 配置
  writeDsaEnvFile(backendDir)

  // 确保 data/ 目录指向用户数据目录（SQLite 等持久化数据）
  const userDataDir = join(app.getPath('userData'), 'dsa-data')
  if (!existsSync(userDataDir)) {
    mkdirSync(userDataDir, { recursive: true })
  }

  // 清理上次可能残留的进程（端口占用）
  killProcessOnPort(fastApiPort)

  fastApiStatus = 'starting'
  broadcastDsaStatus()

  return new Promise((resolve) => {
    const args = ['run', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', String(fastApiPort)]
    // 在 Windows 上使用 uv.exe，避免 shell: true 导致的编码问题和进程包装
    const uvCmd = process.platform === 'win32' ? 'uv.exe' : 'uv'
    let started = false
    let didRetryWithMirror = false

    const shouldRetryWithMirror = (logText) => {
      const t = (logText || '').toLowerCase()
      return (
        t.includes('tls handshake eof') ||
        t.includes('handshake failed') ||
        t.includes('failed to download') ||
        t.includes('request failed after') ||
        t.includes('certificate') ||
        t.includes('connect')
      )
    }

    const spawnFastApi = (useMirror = false) => {
      const uvEnv = {
        ...process.env,
        PYTHONIOENCODING: 'utf-8',
        PYTHONUTF8: '1',
        PYTHONLEGACYWINDOWSSTDIO: '0',
        DSA_DATA_DIR: userDataDir,
        // 使用系统证书可避免部分 macOS 网络环境下 rustls 握手失败
        UV_NATIVE_TLS: process.env.UV_NATIVE_TLS || '1'
      }
      if (useMirror) {
        uvEnv.UV_INDEX_URL =
          process.env.UV_INDEX_URL || 'https://pypi.tuna.tsinghua.edu.cn/simple'
      }

      console.log(`[FastAPI] 启动命令: uv ${args.join(' ')}`)
      console.log(`[FastAPI] 工作目录: ${backendDir}`)
      if (useMirror) {
        console.log(`[FastAPI] 使用镜像源重试: ${uvEnv.UV_INDEX_URL}`)
        broadcastBackendProgress('默认源失败，正在切换镜像源重试...', 'retry')
      } else {
        broadcastBackendProgress('正在启动后端服务...', 'starting')
      }

      fastApiProcess = spawn(uvCmd, args, {
        cwd: backendDir,
        stdio: ['ignore', 'pipe', 'pipe'],
        shell: false,
        windowsHide: true,
        env: uvEnv
      })

      let stderrLog = ''

      fastApiProcess.stdout.on('data', (data) => {
        const output = decodeOutput(data)
        console.log('[FastAPI stdout]', output.trim())
        // 推送到终端面板日志
        terminalManager.appendLog(output)
        // 广播日志到状态栏
        broadcastBackendProgress(output.trim(), 'running')
        if (!started && output.includes('Uvicorn running')) {
          started = true
          fastApiStatus = 'running'
          broadcastDsaStatus()
          broadcastBackendProgress('服务已就绪', 'ready')
          resolve({ success: true, status: 'running' })
        }
      })

      fastApiProcess.stderr.on('data', (data) => {
        const output = decodeOutput(data)
        stderrLog += output
        console.log('[FastAPI stderr]', output.trim())
        // 推送到终端面板日志
        terminalManager.appendLog(output)

        // 解析 stderr 中的进度信息并广播到状态栏
        if (output.includes('Creating virtual environment')) {
          broadcastBackendProgress('正在创建 Python 虚拟环境...', 'env')
        } else if (output.includes('Installed') && output.includes('packages')) {
          const match = output.match(/Installed (\d+) packages/)
          if (match) {
            broadcastBackendProgress(`已安装 ${match[1]} 个依赖包`, 'install')
          }
        } else if (output.includes('Downloading')) {
          const match = output.match(/Downloading (\S+)/)
          if (match) {
            broadcastBackendProgress(`正在下载: ${match[1]}`, 'download')
          }
        } else if (output.includes('Building')) {
          const match = output.match(/Building (\S+)/)
          if (match) {
            broadcastBackendProgress(`正在构建: ${match[1]}`, 'build')
          }
        } else if (output.includes('Using') && output.includes('interpreter')) {
          broadcastBackendProgress('正在配置 Python 解释器...', 'env')
        } else if (output.includes('Resolved') || output.includes('Resolving')) {
          broadcastBackendProgress('正在解析依赖...', 'resolve')
        }

        // uvicorn 输出到 stderr 也是正常的
        if (!started && output.includes('Uvicorn running')) {
          started = true
          fastApiStatus = 'running'
          broadcastDsaStatus()
          broadcastBackendProgress('服务已就绪', 'ready')
          resolve({ success: true, status: 'running' })
        }
      })

      fastApiProcess.on('error', (err) => {
        console.error('[FastAPI] 启动失败:', err.message)
        fastApiProcess = null
        fastApiStatus = 'error'
        broadcastDsaStatus()
        broadcastBackendProgress(`启动失败: ${err.message}`, 'error')
        if (!started) {
          resolve({ success: false, error: err.message })
        }
      })

      fastApiProcess.on('exit', (code) => {
        console.log(`[FastAPI] 进程退出, code=${code}`)
        const canRetry = !started && !didRetryWithMirror && shouldRetryWithMirror(stderrLog)
        fastApiProcess = null

        if (canRetry) {
          didRetryWithMirror = true
          spawnFastApi(true)
          return
        }

        fastApiStatus = 'stopped'
        broadcastDsaStatus()
        broadcastBackendProgress('后端服务已停止', 'stopped')
        if (!started) {
          resolve({ success: false, error: `进程退出 code=${code}` })
        }
      })
    }

    spawnFastApi(false)

    // 超时 30 秒
    setTimeout(() => {
      if (!started) {
        started = true
        // 进程还活着但没检测到启动消息，尝试健康检查
        checkFastApiHealth().then((healthy) => {
          if (healthy) {
            fastApiStatus = 'running'
            broadcastDsaStatus()
            resolve({ success: true, status: 'running' })
          } else {
            fastApiStatus = 'running' // 可能还在加载中，给个乐观状态
            broadcastDsaStatus()
            resolve({
              success: true,
              status: 'running',
              warning: '未检测到启动消息，但进程仍在运行'
            })
          }
        })
      }
    }, 30000)
  })
}

// 按端口号查杀残留进程（启动前清理用）
function killProcessOnPort(port) {
  if (process.platform !== 'win32') return
  try {
    const result = spawnSync('netstat', ['-ano'], {
      encoding: 'utf-8', windowsHide: true, timeout: 5000
    })
    if (!result.stdout) return
    for (const line of result.stdout.split('\n')) {
      if (line.includes(`:${port}`) && line.includes('LISTENING')) {
        const pid = line.trim().split(/\s+/).pop()
        if (pid && pid !== '0') {
          console.log(`[FastAPI] 发现端口 ${port} 被 PID ${pid} 占用，正在终止...`)
          spawnSync('taskkill', ['/pid', pid, '/f', '/t'], {
            windowsHide: true, timeout: 5000
          })
        }
      }
    }
  } catch (e) {
    console.error('[FastAPI] 检查端口占用失败:', e)
  }
}

function stopFastApiServer() {
  if (!fastApiProcess) {
    fastApiStatus = 'stopped'
    broadcastDsaStatus()
    return { success: true }
  }

  const pid = fastApiProcess.pid
  console.log('[FastAPI] 正在停止服务... PID:', pid)
  try {
    if (process.platform === 'win32') {
      // 同步终止进程树，确保 app 退出前子进程已被杀死
      spawnSync('taskkill', ['/pid', String(pid), '/f', '/t'], {
        windowsHide: true, timeout: 5000
      })
    } else {
      fastApiProcess.kill('SIGTERM')
    }
  } catch (e) {
    console.error('[FastAPI] 停止失败:', e)
  }
  fastApiProcess = null
  fastApiStatus = 'stopped'
  broadcastDsaStatus()
  return { success: true }
}

async function checkFastApiHealth() {
  try {
    const { net } = await import('electron')
    return new Promise((resolve) => {
      const request = net.request(`${getFastApiUrl()}/api/health`)
      request.on('response', (response) => {
        resolve(response.statusCode === 200)
      })
      request.on('error', () => resolve(false))
      setTimeout(() => resolve(false), 5000)
      request.end()
    })
  } catch {
    return false
  }
}

function broadcastDsaStatus() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('dsa-status-changed', {
      status: fastApiStatus,
      port: fastApiPort
    })
  }
}

function ensureWorkspaceDir() {
  const wsPath = getWorkspacePath()
  if (!existsSync(wsPath)) {
    try {
      mkdirSync(wsPath, { recursive: true })
      console.log('[Workspace] 已创建工作区目录:', wsPath)
    } catch (e) {
      console.error('[Workspace] 创建工作区目录失败:', e)
    }
  }

  // 创建 indicator 和 strategy 目录
  const indicatorDir = join(wsPath, 'indicator')
  const strategyDir = join(wsPath, 'strategy')
  for (const dir of [indicatorDir, strategyDir]) {
    if (!existsSync(dir)) {
      try {
        mkdirSync(dir, { recursive: true })
      } catch (e) {
        console.error('[Workspace] 创建子目录失败:', e)
      }
    }
  }

  // 创建示例指标：indicator/sma_indicator/
  const smaDir = join(indicatorDir, 'sma_indicator')
  if (!existsSync(smaDir)) {
    mkdirSync(smaDir, { recursive: true })
    writeFileSync(
      join(smaDir, 'sma.py'),
      [
        '# SMA 简单移动平均线指标',
        '# HiveLogic 示例指标',
        '',
        '',
        'def calculate(close_prices: list[float], period: int = 20) -> list[float]:',
        '    """计算简单移动平均线',
        '',
        '    Args:',
        '        close_prices: 收盘价序列',
        '        period: 均线周期，默认20',
        '',
        '    Returns:',
        '        移动平均线数值序列，前 period-1 个值为 None',
        '    """',
        '    result = []',
        '    for i in range(len(close_prices)):',
        '        if i < period - 1:',
        '            result.append(None)',
        '        else:',
        '            window = close_prices[i - period + 1:i + 1]',
        '            result.append(sum(window) / period)',
        '    return result',
        ''
      ].join('\n'),
      'utf-8'
    )
    writeFileSync(
      join(smaDir, '__init__.py'),
      ['from .sma import calculate', ''].join('\n'),
      'utf-8'
    )
    console.log('[Workspace] 已创建示例指标: sma_indicator')
  }

  // 创建示例策略：strategy/ma_cross_strategy/
  const maCrossDir = join(strategyDir, 'ma_cross_strategy')
  if (!existsSync(maCrossDir)) {
    mkdirSync(maCrossDir, { recursive: true })
    writeFileSync(
      join(maCrossDir, 'strategy.py'),
      [
        '# 均线交叉策略',
        '# HiveLogic 示例策略',
        '',
        'from indicator.sma_indicator import calculate as sma',
        '',
        '',
        'def generate_signal(data: dict) -> str:',
        '    """生成交易信号',
        '',
        '    Args:',
        '        data: 包含 OHLCV 数据的字典，至少包含 "close" 键',
        '',
        '    Returns:',
        '        "buy" / "sell" / "hold"',
        '    """',
        '    close = data.get("close", [])',
        '    if len(close) < 21:',
        '        return "hold"',
        '',
        '    ma_short = sma(close, period=5)',
        '    ma_long = sma(close, period=20)',
        '',
        '    if ma_short[-1] is None or ma_long[-1] is None:',
        '        return "hold"',
        '    if ma_short[-2] is None or ma_long[-2] is None:',
        '        return "hold"',
        '',
        '    # 短期均线上穿长期均线 -> 买入',
        '    if ma_short[-1] > ma_long[-1] and ma_short[-2] <= ma_long[-2]:',
        '        return "buy"',
        '    # 短期均线下穿长期均线 -> 卖出',
        '    elif ma_short[-1] < ma_long[-1] and ma_short[-2] >= ma_long[-2]:',
        '        return "sell"',
        '',
        '    return "hold"',
        ''
      ].join('\n'),
      'utf-8'
    )
    writeFileSync(
      join(maCrossDir, 'backtest.py'),
      [
        '# 均线交叉策略回测脚本',
        '',
        'from strategy import generate_signal',
        '',
        '',
        'def run_backtest(prices: list[float]) -> dict:',
        '    """简单回测框架',
        '',
        '    Args:',
        '        prices: 历史收盘价序列',
        '',
        '    Returns:',
        '        回测结果统计',
        '    """',
        '    position = 0  # 0: 空仓, 1: 持仓',
        '    trades = []',
        '    entry_price = 0.0',
        '',
        '    for i in range(1, len(prices)):',
        '        data = {"close": prices[:i + 1]}',
        '        signal = generate_signal(data)',
        '',
        '        if signal == "buy" and position == 0:',
        '            position = 1',
        '            entry_price = prices[i]',
        '            trades.append({"type": "buy", "price": entry_price, "index": i})',
        '        elif signal == "sell" and position == 1:',
        '            position = 0',
        '            profit = prices[i] - entry_price',
        '            trades.append({"type": "sell", "price": prices[i], "index": i, "profit": profit})',
        '',
        '    return {',
        '        "total_trades": len(trades),',
        '        "trades": trades',
        '    }',
        '',
        '',
        'if __name__ == "__main__":',
        '    test_prices = [10, 11, 12, 11, 13, 14, 15, 14, 13, 12,',
        '                   11, 12, 13, 14, 15, 16, 17, 18, 19, 20,',
        '                   21, 22, 21, 20, 19, 18, 19, 20, 21, 22]',
        '    result = run_backtest(test_prices)',
        '    print(f"总交易次数: {result[\'total_trades\']}")',
        '    for t in result["trades"]:',
        '        print(t)',
        ''
      ].join('\n'),
      'utf-8'
    )
    writeFileSync(
      join(maCrossDir, '__init__.py'),
      ['from .strategy import generate_signal', ''].join('\n'),
      'utf-8'
    )
    console.log('[Workspace] 已创建示例策略: ma_cross_strategy')
  }

  // 清理旧的 example.py（如果存在）
  const oldExamplePath = join(wsPath, 'example.py')
  if (existsSync(oldExamplePath)) {
    try {
      unlinkSync(oldExamplePath)
      console.log('[Workspace] 已清理旧示例文件: example.py')
    } catch {
      // 忽略清理失败
    }
  }
}

// 读取目录内容（用于资源管理器）
function readDirectoryTree(dirPath, depth = 0, maxDepth = 1) {
  const items = []
  try {
    const entries = readdirSync(dirPath)
    for (const name of entries) {
      // 跳过隐藏文件
      if (name.startsWith('.')) continue
      const fullPath = join(dirPath, name)
      try {
        const stat = statSync(fullPath)
        const item = {
          name,
          path: fullPath,
          isDirectory: stat.isDirectory()
        }
        if (stat.isDirectory() && depth < maxDepth) {
          item.children = readDirectoryTree(fullPath, depth + 1, maxDepth)
        }
        items.push(item)
      } catch {
        // 跳过无法访问的文件
      }
    }
    // 文件夹在前，文件在后，各自按名称排序
    items.sort((a, b) => {
      if (a.isDirectory === b.isDirectory) return a.name.localeCompare(b.name)
      return a.isDirectory ? -1 : 1
    })
  } catch (e) {
    console.error('[Explorer] 读取目录失败:', e)
  }
  return items
}

// 模式管理
let currentMode = 'trading' // 'trading' | 'news' | 'market_analyze' | 'portfolio' | 'backtest' | 'settings'
const modeState = {
  trading: {
    viewIds: new Set(),
    activeViewId: null,
    pinnedViewIds: new Set(),
    homeViewId: null,
    marketBrowserViewId: null
  },
  developing: { viewIds: new Set(), activeViewId: null },
  news: { viewId: null },
  market_analyze: { viewId: null },
  portfolio: { viewId: null },
  backtest: { viewId: null },
  settings: { viewId: null }
}

function createWindow() {
  // Create the browser window.
  const windowOptions = {
    width: 1600,
    height: 1000,
    show: false,
    title: 'HiveLogic',
    autoHideMenuBar: true,
    icon,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false
    }
  }

  if (process.platform === 'darwin') {
    // macOS: 隐藏标题栏，保留红绿灯
    windowOptions.titleBarStyle = 'hiddenInset'
    windowOptions.trafficLightPosition = { x: 12, y: 8 }
  } else {
    // Windows/Linux: 隐藏标题栏，使用原生窗口控制按钮覆盖层
    windowOptions.titleBarStyle = 'hidden'
    windowOptions.titleBarOverlay = {
      color: '#1e1e1e',
      symbolColor: '#cccccc',
      height: 30
    }
  }

  mainWindow = new BrowserWindow(windowOptions)
  terminalManager.setMainWindow(mainWindow)

  mainWindow.on('ready-to-show', () => {
    mainWindow.show()
  })

  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

  const handleWindowBoundsChange = () => {
    if (!mainWindow || !activeViewId) return
    const activeView = views.get(activeViewId)
    if (activeView) {
      updateWebViewBounds(mainWindow, activeView.view)
    }
    updateSymbolBrowserBounds()
  }

  // 最小化恢复后强制刷新所有 WebContentsView 避免黑屏
  const handleWindowRestore = () => {
    handleWindowBoundsChange()
    // 强制各视图重绘
    views.forEach((viewData) => {
      if (viewData.view && viewData.view.webContents) {
        viewData.view.webContents.invalidate()
      }
    })
    if (symbolBrowserView && symbolBrowserView.webContents) {
      symbolBrowserView.webContents.invalidate()
    }
  }

  mainWindow.on('move', handleWindowBoundsChange)
  mainWindow.on('resize', handleWindowBoundsChange)
  mainWindow.on('restore', handleWindowRestore)
  mainWindow.on('show', handleWindowRestore)

  // HMR for renderer base on electron-vite cli.
  // Load the remote URL for development or the local html file for production.
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }

  // 创建第一个标签页
  // createHomeTab()
  // mainWindow.webContents.openDevTools({ mode: 'left' })
}

function getUUID() {
  if (typeof crypto === 'object') {
    if (typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID()
    }
    if (typeof crypto.getRandomValues === 'function' && typeof Uint8Array === 'function') {
      const callback = (c) => {
        const num = Number(c)
        return (num ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (num / 4)))).toString(
          16
        )
      }
      return ([1e7] + -1e3 + -4e3 + -8e3 + -1e11).replace(/[018]/g, callback)
    }
  }
  let timestamp = new Date().getTime()
  let perforNow =
    (typeof performance !== 'undefined' && performance.now && performance.now() * 1000) || 0
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    let random = Math.random() * 16
    if (timestamp > 0) {
      random = ((timestamp + random) % 16) | 0
      timestamp = Math.floor(timestamp / 16)
    } else {
      random = ((perforNow + random) % 16) | 0
      perforNow = Math.floor(perforNow / 16)
    }
    return (c === 'x' ? random : (random & 0x3) | 0x8).toString(16)
  })
}

// 获取动态顶部偏移（根据当前模式是否显示标签栏）
function getTopOffset() {
  const showTabBar = currentMode === 'trading'
  return TITLE_BAR_HEIGHT + (showTabBar ? TAB_BAR_HEIGHT : 0)
}

// 获取默认标题
function getDefaultTitle(type) {
  switch (type) {
    case 'chart':
      return '新标签页'
    case 'python':
      return 'Python 编辑器'
    case 'settings':
      return '设置'
    case 'placeholder':
      return '正在开发中'
    case 'symbol-browser':
      return '标的浏览器'
    case 'home':
      return '首页'
    case 'market-browser':
      return '标的浏览器'
    default:
      return ''
  }
}

// 创建 WebContentsView（统一创建函数）
function createView(type, options = {}) {
  const viewId = getUUID()
  const view = new WebContentsView({
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      partition: `persist:${viewId}`,
      preload: join(__dirname, '../preload/index.js')
    }
  })
  view.setBackgroundColor('#2e2c29')
  mainWindow.contentView.addChildView(view)

  // 如果指定了文件路径，使用文件名作为标题
  let title = getDefaultTitle(type)
  if (options.filePath) {
    const fileName = options.filePath.split(/[\\/]/).pop()
    title = fileName || title
  }

  const viewData = { view, type, title, filePath: options.filePath || null }
  views.set(viewId, viewData)

  // 初始隐藏
  view.setBounds({ x: ACTIVITY_BAR_WIDTH, y: 0, width: 0, height: 0 })

  // 监听页面标题变化
  view.webContents.on('page-title-updated', (event, title) => {
    viewData.title = title
    mainWindow.webContents.send('tab-title-updated', viewId, title)
  })

  // 监听页面加载状态
  view.webContents.on('did-start-loading', () => {
    mainWindow.webContents.send('tab-loading', viewId, true)
  })
  view.webContents.on('did-stop-loading', () => {
    mainWindow.webContents.send('tab-loading', viewId, false)
  })
  view.webContents.on('did-finish-load', () => {
    mainWindow.webContents.send('tab-loading', viewId, false)
    // 如果有关联的文件路径，通知 python 编辑器加载文件
    if (viewData.filePath && viewData.type === 'python') {
      view.webContents.send('open-file-in-editor', viewData.filePath)
    }
  })
  view.webContents.on('did-fail-load', () => {
    mainWindow.webContents.send('tab-loading', viewId, false)
  })

  // 加载对应页面
  const htmlFileMap = {
    chart: 'chart.html',
    python: 'python.html',
    settings: 'settings.html',
    placeholder: 'placeholder.html',
    'stock-analysis': 'stock-analysis.html',
    portfolio: 'portfolio.html',
    backtest: 'backtest.html',
    news: 'news.html',
    'symbol-browser': 'symbol-browser.html',
    home: 'home.html',
    'market-browser': 'market-browser.html'
  }
  const htmlFile = htmlFileMap[type]
  if (htmlFile) {
    if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
      const url = `${process.env['ELECTRON_RENDERER_URL']}/${htmlFile}`
      console.log(`[createView] Loading URL: ${url}`)
      view.webContents.loadURL(url)
    } else {
      view.webContents.loadFile(join(__dirname, `../renderer/${htmlFile}`))
    }
  }

  // 监听 DevTools 关闭/打开事件，同步按钮状态
  view.webContents.on('devtools-closed', () => {
    mainWindow.webContents.send('devtools-state-changed', false)
  })
  view.webContents.on('devtools-opened', () => {
    mainWindow.webContents.send('devtools-state-changed', true)
  })

  // 开发模式下自动打开 DevTools 用于调试图表（已禁用，可通过 UI 按钮手动开启）
  // if (is.dev && type === 'chart') {
  //   view.webContents.openDevTools({ mode: 'detach' })
  // }

  return viewId
}

// 在交易模式下创建新的图表标签页
function createNewTab() {
  if (currentMode !== 'trading') return null
  const state = modeState.trading
  if (state.viewIds.size >= 10) {
    mainWindow.webContents.send('tab-limit', '最多只能创建10个标签页')
    return null
  }

  const viewId = createView('chart')
  state.viewIds.add(viewId)

  // 通知渲染进程
  mainWindow.webContents.send('tab-created', viewId)

  setActiveTab(viewId)
  state.activeViewId = viewId
  return viewId
}

// 模式切换
function switchMode(newMode) {
  // developing 模式已废弃，改为打开指标编辑器
  if (newMode === 'developing') {
    const { toggleIndicatorEditorWindow } = require('./indicatorEditorWindow')
    toggleIndicatorEditorWindow(mainWindow)
    return
  }

  // 保存当前模式的活动视图
  if (currentMode === 'trading') {
    modeState[currentMode].activeViewId = activeViewId
  }

  // 隐藏所有视图
  views.forEach((viewData) => {
    viewData.view.setBounds({ x: ACTIVITY_BAR_WIDTH, y: 0, width: 0, height: 0 })
  })

  currentMode = newMode
  // 左面板在交易模式（标的浏览器）下显示
  explorerPanelVisible = newMode === 'trading'
  const showTabBar = newMode === 'trading'
  const showNewTabBtn = newMode === 'trading'

  let tabs = []
  let newActiveViewId = null

  if (newMode === 'trading') {
    const state = modeState.trading
    // 创建固定标签页（首页和标的浏览器）
    if (!state.homeViewId) {
      const homeId = createView('home')
      state.homeViewId = homeId
      state.pinnedViewIds.add(homeId)
      state.viewIds.add(homeId)
    }
    if (!state.marketBrowserViewId) {
      const mbId = createView('market-browser')
      state.marketBrowserViewId = mbId
      state.pinnedViewIds.add(mbId)
      state.viewIds.add(mbId)
    }
    // 创建标的浏览器左面板视图（如果尚未创建）
    createSymbolBrowserView()
    newActiveViewId = state.homeViewId
    // 构建标签页信息（固定标签在前，图表标签在后）
    // 先添加固定标签
    const homeVd = views.get(state.homeViewId)
    if (homeVd) {
      tabs.push({
        viewId: state.homeViewId,
        title: '首页',
        type: 'home',
        pinned: true
      })
    }
    const mbVd = views.get(state.marketBrowserViewId)
    if (mbVd) {
      tabs.push({
        viewId: state.marketBrowserViewId,
        title: '标的浏览器',
        type: 'market-browser',
        pinned: true
      })
    }
    // 再添加普通标签
    state.viewIds.forEach((vid) => {
      if (state.pinnedViewIds.has(vid)) return
      const vd = views.get(vid)
      if (vd) tabs.push({ viewId: vid, title: vd.title || '新标签页', type: vd.type })
    })
  } else if (newMode === 'news') {
    const state = modeState.news
    if (!state.viewId) {
      state.viewId = createView('news')
    }
    newActiveViewId = state.viewId
  } else if (newMode === 'market_analyze') {
    // P1: 市场分析能力已迁移至 Agent Window
    openAgentWindow({ mode: 'deep' })
    // 仍维持 stock-analysis 视图作为兼容兜底
    const state = modeState.market_analyze
    if (!state.viewId) {
      state.viewId = createView('stock-analysis')
    }
    newActiveViewId = state.viewId
  } else if (newMode === 'portfolio') {
    const state = modeState.portfolio
    if (!state.viewId) {
      state.viewId = createView('portfolio')
    }
    newActiveViewId = state.viewId
  } else if (newMode === 'backtest') {
    const state = modeState.backtest
    if (!state.viewId) {
      state.viewId = createView('backtest')
    }
    newActiveViewId = state.viewId
  } else if (newMode === 'settings') {
    const state = modeState.settings
    if (!state.viewId) {
      state.viewId = createView('settings')
    }
    newActiveViewId = state.viewId
  }

  // 显示新模式的活动视图
  if (newActiveViewId) {
    activeViewId = newActiveViewId
    const viewData = views.get(newActiveViewId)
    if (viewData) {
      updateWebViewBounds(mainWindow, viewData.view)
    }
  }

  // 通知渲染进程
  mainWindow.webContents.send('mode-switched', {
    mode: newMode,
    showTabBar,
    showNewTabBtn,
    tabs,
    activeViewId: newActiveViewId
  })
}
// 更新 WebContentsView 边界的函数
function updateWebViewBounds(window, webView) {
  const [mainwin_content_width, mainwin_content_height] = mainWindow.getContentSize()
  const rightPanelWidth = agentPanelVisible ? currentAgentPanelWidth : 0
  const leftPanelWidth = explorerPanelVisible ? currentExplorerPanelWidth : 0
  const topOffset = getTopOffset()
  const bottomOffset = STATUS_BAR_HEIGHT + (terminalPanelVisible ? currentTerminalPanelHeight : 0)
  webView.setBounds({
    x: ACTIVITY_BAR_WIDTH + leftPanelWidth + 1,
    y: topOffset,
    width: mainwin_content_width - ACTIVITY_BAR_WIDTH - leftPanelWidth - rightPanelWidth - 1,
    height: mainwin_content_height - topOffset - bottomOffset
  })
  // 同步更新标的浏览器左面板视图的边界
  updateSymbolBrowserBounds()
}

// 创建标的浏览器左面板视图
function createSymbolBrowserView() {
  if (symbolBrowserView) return // 已存在
  symbolBrowserView = new WebContentsView({
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      partition: 'persist:symbol-browser-panel',
      preload: join(__dirname, '../preload/index.js')
    }
  })
  symbolBrowserView.setBackgroundColor('#252526')
  mainWindow.contentView.addChildView(symbolBrowserView)

  const htmlFile = 'symbol-browser.html'
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    symbolBrowserView.webContents.loadURL(`${process.env['ELECTRON_RENDERER_URL']}/${htmlFile}`)
  } else {
    symbolBrowserView.webContents.loadFile(join(__dirname, `../renderer/${htmlFile}`))
  }
}

// 更新标的浏览器视图边界（左面板区域）
function updateSymbolBrowserBounds() {
  if (!symbolBrowserView) return
  if (currentMode !== 'trading' || !explorerPanelVisible) {
    symbolBrowserView.setBounds({ x: 0, y: 0, width: 0, height: 0 })
    return
  }
  const [, mainwin_content_height] = mainWindow.getContentSize()
  // 标的浏览器左面板从标题栏下方开始（与 activity bar / explorer 面板对齐，不受 tab bar 影响）
  const panelTop = TITLE_BAR_HEIGHT
  const bottomOffset = STATUS_BAR_HEIGHT + (terminalPanelVisible ? currentTerminalPanelHeight : 0)
  symbolBrowserView.setBounds({
    x: ACTIVITY_BAR_WIDTH + 1,
    y: panelTop,
    width: currentExplorerPanelWidth - 7,
    height: mainwin_content_height - panelTop - bottomOffset
  })
}

// 关闭所有图表页面
function closeAllChartTabs() {
  console.log('[closeAllChartTabs] 开始关闭所有图表页面')
  const state = modeState.trading
  const chartViewIds = Array.from(state.viewIds)

  console.log(`[closeAllChartTabs] 找到 ${chartViewIds.length} 个图表页面需要关闭:`, chartViewIds)

  chartViewIds.forEach((viewId) => {
    const viewData = views.get(viewId)
    if (viewData) {
      console.log(`[closeAllChartTabs] 正在关闭图表页面: ${viewId}`)
      try {
        mainWindow.contentView.removeChildView(viewData.view)
        views.delete(viewId)
        state.viewIds.delete(viewId)
        mainWindow.webContents.send('tab-closed', viewId)
        console.log(`[closeAllChartTabs] 成功关闭图表页面: ${viewId}`)
      } catch (error) {
        console.error(`[closeAllChartTabs] 关闭图表页面失败 ${viewId}:`, error)
      }
    }
  })

  state.activeViewId = null

  // 如果当前在交易模式，创建一个新的图表标签页
  if (currentMode === 'trading') {
    const viewId = createView('chart')
    state.viewIds.add(viewId)
    state.activeViewId = viewId
    mainWindow.webContents.send('tab-created', viewId)
    setActiveTab(viewId)
  }

  console.log(`[closeAllChartTabs] 完成，已关闭 ${chartViewIds.length} 个图表页面`)
}

// 重置可视窗口
function setActiveTab(viewId) {
  views.forEach((viewData, id) => {
    if (id === viewId) {
      updateWebViewBounds(mainWindow, viewData.view)
    } else {
      viewData.view.setBounds({ x: ACTIVITY_BAR_WIDTH, y: 0, width: 0, height: 0 })
    }
  })
  activeViewId = viewId
  // 更新当前模式的活动视图
  if (currentMode === 'trading') {
    const state = modeState[currentMode]
    if (state.viewIds && state.viewIds.has(viewId)) {
      state.activeViewId = viewId
    }
  }
}

// 监听标签页相关的事件
ipcMain.on('renderer-ready', () => {
  switchMode('trading')
})

ipcMain.on('switch-mode', (event, newMode) => {
  switchMode(newMode)
})

ipcMain.on('new-tab', () => {
  createNewTab()
})

ipcMain.on('switch-tab', (event, viewId) => {
  setActiveTab(viewId)
})

// 按标签页类型切换到固定标签页
ipcMain.on('switch-to-pinned-tab', (event, tabType) => {
  const state = modeState.trading
  if (tabType === 'market-browser' && state.marketBrowserViewId) {
    setActiveTab(state.marketBrowserViewId)
  } else if (tabType === 'home' && state.homeViewId) {
    setActiveTab(state.homeViewId)
  }
})

ipcMain.on('close-tab', (event, viewId) => {
  const viewData = views.get(viewId)
  if (!viewData) return

  // 不允许关闭固定标签页
  if (modeState.trading.pinnedViewIds && modeState.trading.pinnedViewIds.has(viewId)) {
    mainWindow.webContents.send('tab-limit', '固定标签页不可关闭')
    return
  }

  // 找到该视图所属的模式
  let viewMode = null
  for (const [mode, state] of Object.entries(modeState)) {
    if (state.viewIds && state.viewIds.has(viewId)) {
      viewMode = mode
      break
    }
  }

  // 至少保留1个标签页（不含固定标签）
  if (viewMode && modeState[viewMode].viewIds) {
    const pinnedCount = modeState[viewMode].pinnedViewIds
      ? modeState[viewMode].pinnedViewIds.size
      : 0
    const closableCount = modeState[viewMode].viewIds.size - pinnedCount
    if (closableCount <= 1) {
      mainWindow.webContents.send('tab-limit', '至少需要保留1个标签页')
      return
    }
  }

  mainWindow.contentView.removeChildView(viewData.view)
  views.delete(viewId)

  if (viewMode && modeState[viewMode].viewIds) {
    modeState[viewMode].viewIds.delete(viewId)
  }

  if (activeViewId === viewId) {
    // 切换到当前模式的最后一个视图
    if (viewMode && modeState[viewMode].viewIds) {
      const remaining = Array.from(modeState[viewMode].viewIds)
      if (remaining.length > 0) {
        setActiveTab(remaining[remaining.length - 1])
      }
    }
  }

  mainWindow.webContents.send('tab-closed', viewId)
})

// 监听关闭所有图表页面的请求
ipcMain.on('close-all-chart-tabs', () => {
  console.log('[IPC] 收到关闭所有图表页面的请求')
  closeAllChartTabs()
})

// 标的浏览器：在图表中打开标的
ipcMain.on('open-symbol-in-chart', (event, symbolInfo) => {
  console.log('[IPC] 在图表中打开标的:', symbolInfo)
  if (currentMode !== 'trading') {
    switchMode('trading')
  }
  const state = modeState.trading
  if (state.viewIds.size >= 10) {
    mainWindow.webContents.send('tab-limit', '最多只能创建10个标签页')
    return
  }
  const viewId = createView('chart')
  state.viewIds.add(viewId)
  mainWindow.webContents.send('tab-created', viewId)
  setActiveTab(viewId)
  state.activeViewId = viewId
  // 等页面加载完成后发送标的信息
  // 延迟 200ms 确保 Vue 已完成挂载并注册了 onLoadSymbol 监听器
  const viewData = views.get(viewId)
  if (viewData) {
    viewData.view.webContents.once('did-finish-load', () => {
      setTimeout(() => {
        viewData.view.webContents.send('load-symbol', symbolInfo)
      }, 200)
    })
  }
})

// 标的浏览器：打开市场分析
ipcMain.on('open-symbol-analysis', (event, symbolInfo) => {
  console.log('[IPC] 打开标的市场分析:', symbolInfo)
  switchMode('market_analyze')
  const state = modeState.market_analyze
  if (state.viewId) {
    const viewData = views.get(state.viewId)
    if (viewData) {
      // 检查页面是否已加载完成
      if (viewData.view.webContents.isLoading()) {
        // 页面尚在加载，等加载完成后发送（延迟确保 Vue 挂载）
        viewData.view.webContents.once('did-finish-load', () => {
          setTimeout(() => {
            viewData.view.webContents.send('analyze-symbol', symbolInfo)
          }, 200)
        })
      } else {
        // 页面已加载，直接发送
        viewData.view.webContents.send('analyze-symbol', symbolInfo)
      }
    }
  }
})

// 数据源设置的 IPC 处理（解决跨 partition localStorage 隔离问题）
ipcMain.handle('get-data-source', () => {
  return currentDataSource
})

ipcMain.on('set-data-source', (event, dataSource) => {
  console.log('[IPC] 数据源已更新为:', dataSource)
  currentDataSource = dataSource
})

// 外部编辑器设置
ipcMain.handle('get-external-editor', () => {
  const config = readConfig()
  return config.externalEditor || 'auto'
})

ipcMain.handle('set-external-editor', (event, editor) => {
  const config = readConfig()
  config.externalEditor = editor
  writeConfig(config)
  return true
})

// 读取文件内容
ipcMain.handle('read-file', (event, filePath) => {
  // 安全检查：只允许读取工作区目录下的文件
  const wsPath = getWorkspacePath()
  const normalizedPath = join(filePath)
  if (!normalizedPath.startsWith(wsPath)) {
    console.warn('[ReadFile] 拒绝读取工作区以外的文件:', filePath)
    return null
  }
  try {
    return readFileSync(filePath, 'utf-8')
  } catch (e) {
    console.error('[ReadFile] 读取文件失败:', e)
    return null
  }
})

// 在开发模式中打开文件 (legacy, developing 模式已移除)
ipcMain.on('open-file', (event, filePath) => {
  // developing 模式已废弃, 此 handler 保留兼容性
  return
})

// 监听 Agent 面板切换
ipcMain.on('toggle-agent-panel', (event, visible) => {
  agentPanelVisible = visible
  if (!visible) {
    currentAgentPanelWidth = 0
  } else {
    currentAgentPanelWidth = AGENT_PANEL_WIDTH
  }
  // 更新当前活动视图的尺寸
  if (activeViewId) {
    const activeView = views.get(activeViewId)
    if (activeView) {
      updateWebViewBounds(mainWindow, activeView.view)
    }
  }
})

// 监听 Agent 面板宽度调整
ipcMain.on('resize-agent-panel', (event, width) => {
  currentAgentPanelWidth = width
  if (activeViewId) {
    const activeView = views.get(activeViewId)
    if (activeView) {
      updateWebViewBounds(mainWindow, activeView.view)
    }
  }
})

// =====================
// 工作区目录 IPC
// =====================
ipcMain.handle('get-workspace-path', () => {
  return getWorkspacePath()
})

ipcMain.handle('set-workspace-path', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择工作区目录',
    defaultPath: getWorkspacePath(),
    properties: ['openDirectory', 'createDirectory']
  })
  if (!result.canceled && result.filePaths.length > 0) {
    const newPath = result.filePaths[0]
    setWorkspacePath(newPath)
    ensureWorkspaceDir()
    return newPath
  }
  return null
})

ipcMain.handle('read-directory', (event, dirPath) => {
  // 安全检查：只允许读取工作区目录下的内容
  const wsPath = getWorkspacePath()
  const normalizedDir = join(dirPath)
  if (!normalizedDir.startsWith(wsPath)) {
    console.warn('[Explorer] 拒绝访问工作区以外的目录:', dirPath)
    return []
  }
  return readDirectoryTree(dirPath, 0, 0)
})

// 安全检查工具函数：确保路径在工作区内
function isInsideWorkspace(targetPath) {
  const wsPath = getWorkspacePath()
  const normalized = join(targetPath)
  return normalized.startsWith(wsPath)
}

// 创建文件
ipcMain.handle('create-file', (event, filePath) => {
  const safePath = join(filePath)
  if (!isInsideWorkspace(safePath)) return { success: false, error: '路径不在工作区内' }
  if (existsSync(safePath)) return { success: false, error: '文件已存在' }
  try {
    writeFileSync(safePath, '', 'utf-8')
    return { success: true }
  } catch (e) {
    return { success: false, error: e.message }
  }
})

// 创建文件夹
ipcMain.handle('create-folder', (event, folderPath) => {
  const safePath = join(folderPath)
  if (!isInsideWorkspace(safePath)) return { success: false, error: '路径不在工作区内' }
  if (existsSync(safePath)) return { success: false, error: '文件夹已存在' }
  try {
    mkdirSync(safePath, { recursive: true })
    return { success: true }
  } catch (e) {
    return { success: false, error: e.message }
  }
})

// 重命名
ipcMain.handle('rename-item', (event, oldPath, newPath) => {
  const safeOld = join(oldPath)
  const safeNew = join(newPath)
  if (!isInsideWorkspace(safeOld) || !isInsideWorkspace(safeNew)) {
    return { success: false, error: '路径不在工作区内' }
  }
  if (!existsSync(safeOld)) return { success: false, error: '原路径不存在' }
  if (existsSync(safeNew)) return { success: false, error: '目标名称已存在' }
  try {
    renameSync(safeOld, safeNew)
    return { success: true }
  } catch (e) {
    return { success: false, error: e.message }
  }
})

// 删除文件/文件夹
ipcMain.handle('delete-item', (event, targetPath) => {
  const safePath = join(targetPath)
  if (!isInsideWorkspace(safePath)) return { success: false, error: '路径不在工作区内' }
  if (!existsSync(safePath)) return { success: false, error: '路径不存在' }
  try {
    const stat = statSync(safePath)
    if (stat.isDirectory()) {
      rmSync(safePath, { recursive: true, force: true })
    } else {
      unlinkSync(safePath)
    }
    return { success: true }
  } catch (e) {
    return { success: false, error: e.message }
  }
})

// 移动（用于拖拽）
ipcMain.handle('move-item', (event, srcPath, destDir) => {
  const safeSrc = join(srcPath)
  const safeDest = join(destDir)
  if (!isInsideWorkspace(safeSrc) || !isInsideWorkspace(safeDest)) {
    return { success: false, error: '路径不在工作区内' }
  }
  if (!existsSync(safeSrc)) return { success: false, error: '源路径不存在' }
  const itemName = safeSrc.split(/[\\/]/).pop()
  const destPath = join(safeDest, itemName)
  if (existsSync(destPath)) return { success: false, error: '目标位置已存在同名项' }
  try {
    renameSync(safeSrc, destPath)
    return { success: true }
  } catch (e) {
    return { success: false, error: e.message }
  }
})

// 保存文件内容
ipcMain.handle('save-file', (event, filePath, content) => {
  const safePath = join(filePath)
  if (!isInsideWorkspace(safePath)) return { success: false, error: '路径不在工作区内' }
  try {
    writeFileSync(safePath, content, 'utf-8')
    return { success: true }
  } catch (e) {
    return { success: false, error: e.message }
  }
})

// 导出 PDF — 利用隐藏窗口 printToPDF
ipcMain.handle('export-pdf', async (_event, { html, defaultFileName }) => {
  const result = await dialog.showSaveDialog(mainWindow, {
    title: '导出 PDF',
    defaultPath: defaultFileName || 'analysis_report.pdf',
    filters: [{ name: 'PDF', extensions: ['pdf'] }]
  })
  if (result.canceled || !result.filePath) return { success: false }

  const pdfWin = new BrowserWindow({ show: false, width: 800, height: 1200 })
  try {
    await pdfWin.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`)
    const pdfBuffer = await pdfWin.webContents.printToPDF({
      printBackground: true,
      marginType: 1, // minimum margins
      pageSize: 'A4'
    })
    writeFileSync(result.filePath, pdfBuffer)
    return { success: true, path: result.filePath }
  } catch (e) {
    return { success: false, error: e.message }
  } finally {
    pdfWin.destroy()
  }
})

// 资源管理器面板 IPC
ipcMain.on('toggle-explorer-panel', (event, visible) => {
  explorerPanelVisible = visible
  if (activeViewId) {
    const activeView = views.get(activeViewId)
    if (activeView) {
      updateWebViewBounds(mainWindow, activeView.view)
    }
  }
  // 通知主渲染进程同步面板显示状态
  mainWindow.webContents.send('explorer-panel-visibility-changed', visible)
})

ipcMain.on('resize-explorer-panel', (event, width) => {
  currentExplorerPanelWidth = width
  if (activeViewId) {
    const activeView = views.get(activeViewId)
    if (activeView) {
      updateWebViewBounds(mainWindow, activeView.view)
    }
  }
  // 广播宽度变化到所有视图，使各页面侧栏宽度同步
  views.forEach((viewData) => {
    viewData.view.webContents.send('side-panel-width-changed', width)
  })
})

ipcMain.handle('get-side-panel-width', () => {
  return currentExplorerPanelWidth
})

// =====================
// DSA (daily_stock_analysis) IPC
// =====================
ipcMain.handle('get-dsa-config', () => {
  const cfg = getDsaConfig()
  cfg.backendPath = getBackendPath()
  return cfg
})

ipcMain.handle('set-dsa-config', (event, dsaConfig) => {
  setDsaConfig(dsaConfig)
  return { success: true }
})

// 服务端连接配置 IPC（Phase 1.2）
ipcMain.handle('get-server-config', () => {
  return getServerConfig()
})

ipcMain.handle('set-server-config', (event, serverConfig) => {
  setServerConfig(serverConfig)
  return { success: true }
})

ipcMain.handle('browse-python-path', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择 Python 解释器',
    properties: ['openFile'],
    filters:
      process.platform === 'win32'
        ? [{ name: 'Python', extensions: ['exe'] }]
        : [{ name: 'All Files', extensions: ['*'] }]
  })
  if (!result.canceled && result.filePaths.length > 0) {
    return result.filePaths[0]
  }
  return null
})

// 配置导出
ipcMain.handle('export-config', async (_event, content, defaultFileName) => {
  const result = await dialog.showSaveDialog(mainWindow, {
    title: '导出配置',
    defaultPath: defaultFileName || 'hivelogic-config.env',
    filters: [
      { name: 'Env File', extensions: ['env'] },
      { name: 'JSON File', extensions: ['json'] },
      { name: 'All Files', extensions: ['*'] }
    ]
  })
  if (result.canceled || !result.filePath) return { success: false }
  try {
    writeFileSync(result.filePath, content, 'utf-8')
    return { success: true, path: result.filePath }
  } catch (e) {
    return { success: false, error: e.message }
  }
})

// 配置导入
ipcMain.handle('import-config', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '导入配置',
    properties: ['openFile'],
    filters: [
      { name: 'Env File', extensions: ['env'] },
      { name: 'JSON File', extensions: ['json'] },
      { name: 'All Files', extensions: ['*'] }
    ]
  })
  if (result.canceled || result.filePaths.length === 0) return { success: false }
  try {
    const content = readFileSync(result.filePaths[0], 'utf-8')
    return { success: true, content, path: result.filePaths[0] }
  } catch (e) {
    return { success: false, error: e.message }
  }
})

// =====================
// 终端面板 IPC
// =====================
ipcMain.handle('terminal-create', (_event, options = {}) => {
  const backendDir = getBackendPath()
  const venvDir = join(backendDir, '.venv')
  const isWin = process.platform === 'win32'
  const binDir = isWin ? join(venvDir, 'Scripts') : join(venvDir, 'bin')

  const termEnv = {
    ...process.env,
    VIRTUAL_ENV: venvDir,
    PATH: `${binDir}${isWin ? ';' : ':'}${process.env.PATH}`,
    PYTHONIOENCODING: 'utf-8',
    PYTHONUTF8: '1'
  }

  const termOptions = {
    cwd: options.cwd || backendDir,
    env: termEnv,
    cols: options.cols || 80,
    rows: options.rows || 24,
    shell: options.shell || undefined
  }

  return terminalManager.createTerminal(termOptions)
})

ipcMain.on('terminal-input', (_event, { id, data }) => {
  terminalManager.writeToTerminal(id, data)
})

ipcMain.on('terminal-resize', (_event, { id, cols, rows }) => {
  terminalManager.resizeTerminal(id, cols, rows)
})

ipcMain.on('terminal-destroy', (_event, { id }) => {
  terminalManager.destroyTerminal(id)
})

ipcMain.handle('terminal-get-log-history', () => {
  return terminalManager.getLogHistory()
})

ipcMain.on('toggle-terminal-panel', (_event, visible, height) => {
  terminalPanelVisible = visible
  if (height !== undefined) {
    currentTerminalPanelHeight = height
  }
  if (activeViewId) {
    const activeView = views.get(activeViewId)
    if (activeView) {
      updateWebViewBounds(mainWindow, activeView.view)
    }
  }
})

ipcMain.on('resize-terminal-panel', (_event, height) => {
  currentTerminalPanelHeight = height
  if (activeViewId) {
    const activeView = views.get(activeViewId)
    if (activeView) {
      updateWebViewBounds(mainWindow, activeView.view)
    }
  }
})

ipcMain.handle('start-dsa-server', async () => {
  return await startFastApiServer()
})

ipcMain.handle('stop-dsa-server', () => {
  return stopFastApiServer()
})

ipcMain.handle('get-dsa-status', () => {
  return { status: fastApiStatus, port: fastApiPort }
})

ipcMain.handle('check-dsa-health', async () => {
  const healthy = await checkFastApiHealth()
  return { healthy, status: fastApiStatus, port: fastApiPort }
})

// 监听右键菜单请求
ipcMain.on('show-context-menu', (event, viewId) => {
  console.log(`open context menu ${viewId}`)
  const viewData = views.get(viewId)
  if (!viewData) return

  const template = [
    {
      label: '打开DevTools',
      click: () => {
        mainWindow.send('context-menu-action', { action: 'copy', viewId: viewId })
        viewData.view.webContents.openDevTools({ mode: 'detach' })
        console.log(`on menu item open DevTools for ${viewId}`)
      }
    },
    {
      label: '粘贴',
      click: () => mainWindow.send('context-menu-action', { action: 'paste', viewId: viewId })
    },
    { type: 'separator' },
    {
      label: '自定义动作',
      click: () => mainWindow.send('context-menu-action', { action: 'custom', viewId: viewId })
    }
  ]
  const menu = Menu.buildFromTemplate(template)
  menu.popup({ window: mainWindow })
})

// // 添加以下函数来广播消息给所有标签
// function broadcastToAllTabs(channel, ...args) {
//   views.forEach((view) => {
//     view.webContents.send(channel, ...args)
//   })
// }

// app.whenReady().then(createWindow)

// This method will be called when Electron has finished
// initialization and is ready to create browser windows.
// Some APIs can only be used after this event occurs.
app.whenReady().then(() => {
  // Set app user model id for windows
  electronApp.setAppUserModelId('com.electron')

  // 确保工作区目录存在
  ensureWorkspaceDir()

  // 为所有新创建的 session 设置 CORS 旁路（解决 OKX API 不返回 CORS 头的问题）
  app.on('session-created', (newSession) => {
    newSession.webRequest.onHeadersReceived((details, callback) => {
      const { responseHeaders } = details
      if (details.url.includes('okx.com')) {
        responseHeaders['Access-Control-Allow-Origin'] = ['*']
        responseHeaders['Access-Control-Allow-Methods'] = ['GET, POST, OPTIONS']
        responseHeaders['Access-Control-Allow-Headers'] = ['*']
      }
      callback({ responseHeaders })
    })
  })

  // 也为默认 session 设置
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    const { responseHeaders } = details
    if (details.url.includes('okx.com')) {
      responseHeaders['Access-Control-Allow-Origin'] = ['*']
      responseHeaders['Access-Control-Allow-Methods'] = ['GET, POST, OPTIONS']
      responseHeaders['Access-Control-Allow-Headers'] = ['*']
    }
    callback({ responseHeaders })
  })

  // Default open or close DevTools by F12 in development
  // and ignore CommandOrControl + R in production.
  // see https://github.com/alex8088/electron-toolkit/tree/master/packages/utils
  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  // IPC test
  ipcMain.on('ping', () => console.log('pong'))

  createWindow()

  // 初始化 Agent Window IPC
  initAgentWindowIPC(mainWindow)

  // 初始化自定义指标管理器 + 编辑器窗口 IPC
  initIndicatorManager(mainWindow, getWorkspacePath())
  initIndicatorEditorIPC(mainWindow)

  // 注册全局快捷键: Ctrl+Shift+A 打开 Agent Window
  globalShortcut.register('CommandOrControl+Shift+A', () => {
    ipcMain.emit('agent:toggle-window')
  })

  // 注册全局快捷键: Ctrl+Shift+E 打开指标编辑器
  globalShortcut.register('CommandOrControl+Shift+E', () => {
    ipcMain.emit('indicator:toggle-editor')
  })

  // 自动拉起后端服务（仅本地模式）
  if (isLocalMode()) {
    startFastApiServer().then((result) => {
      if (result.success) {
        console.log('[FastAPI] 后端服务已自动启动')
      } else {
        console.warn('[FastAPI] 后端服务自动启动失败:', result.error)
      }
    })
  } else {
    fastApiStatus = 'stopped'
    broadcastDsaStatus()
    console.log('[Server] 远程模式，跳过本地后端启动')
  }

  app.on('activate', function () {
    // On macOS it's common to re-create a window in the app when the
    // dock icon is clicked and there are no other windows open.
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

// Quit when all windows are closed, except on macOS. There, it's common
// for applications and their menu bar to stay active until the user quits
// explicitly with Cmd + Q.
app.on('window-all-closed', () => {
  if (isLocalMode()) {
    stopFastApiServer()
  }
  destroyIndicatorManager()
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
  globalShortcut.unregisterAll()
  if (isLocalMode()) {
    stopFastApiServer()
    terminalManager.destroyAll()
    killProcessOnPort(fastApiPort)
  }
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow()
  }
})
// In this file you can include the rest of your app's specific main process
// code. You can also put them in separate files and require them here.

ipcMain.on('toggle-devtools', () => {
  if (activeViewId) {
    const viewData = views.get(activeViewId)
    if (viewData && viewData.view) {
      const wc = viewData.view.webContents
      if (wc.isDevToolsOpened()) {
        wc.closeDevTools()
      } else {
        wc.openDevTools({ mode: 'detach' })
      }
    }
  } else {
    // fallback: toggle main window devtools
    if (mainWindow.webContents.isDevToolsOpened()) {
      mainWindow.webContents.closeDevTools()
    } else {
      mainWindow.webContents.openDevTools({ mode: 'detach' })
    }
  }
})

ipcMain.on('open-dev-tools-in-new-window', (event) => {
  // const mainWindow = BrowserWindow.fromWebContents(event.sender)
  const devToolsWindow = new BrowserWindow({ width: 800, height: 600, title: 'DevTool' })

  // 将 DevTools 从主窗口移动到新窗口
  mainWindow.webContents.devToolsWebContents.executeJavaScript(`
      InspectorFrontendHost.setInspectedWindowTab(null);
      InspectorFrontendHost.showWindow();
  `)
  mainWindow.webContents.devToolsWebContents.setDevToolsWebContents(devToolsWindow.webContents)

  const mainPos = mainWindow.getPosition()
  devToolsWindow.setPosition(mainPos[0] + mainWindow.getSize()[0] + 10, mainPos[1])

  devToolsWindow.focus()
})
