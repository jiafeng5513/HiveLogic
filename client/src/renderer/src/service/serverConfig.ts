/**
 * ===================================
 * 服务端地址统一配置 (Server Config)
 * ===================================
 *
 * 职责：
 * 1. 统一管理后端服务地址，消除各模块硬编码的 127.0.0.1:8100
 * 2. 优先级：localStorage 覆盖 > window.__hivelogic_config__ > 默认值
 * 3. 对外导出 getApiBase() / getWsUrl()
 */

// ==================== 全局类型声明 ====================

interface HiveLogicRuntimeConfig {
  /** 后端服务基础地址，如 http://127.0.0.1:8100 */
  serverBaseUrl?: string
}

declare global {
  interface Window {
    __hivelogic_config__?: HiveLogicRuntimeConfig
  }
}

// ==================== 常量 ====================

/** 默认本地后端地址 */
const DEFAULT_SERVER_BASE_URL = 'http://127.0.0.1:8100'

/** localStorage 覆盖键名 */
const LOCAL_STORAGE_KEY = 'hivelogic:serverBaseUrl'

// ==================== 内部实现 ====================

/**
 * 读取服务端基础地址（origin，不含路径）
 *
 * 优先级：
 * 1. localStorage.getItem('hivelogic:serverBaseUrl') —— 用户手动覆盖（开发/调试用）
 * 2. window.__hivelogic_config__.serverBaseUrl —— 主进程注入的运行时配置
 * 3. http://127.0.0.1:8100 —— 默认本地后端
 *
 * 返回值已去掉末尾斜杠，便于调用方拼接路径。
 */
function getServerBaseUrl(): string {
  // 1. localStorage 用户覆盖
  try {
    const stored = localStorage.getItem(LOCAL_STORAGE_KEY)
    if (stored) return stored.replace(/\/+$/, '')
  } catch {
    // localStorage 不可用时忽略（如 SSR 或权限受限场景）
  }

  // 2. 主进程注入的运行时配置
  const injected = window.__hivelogic_config__?.serverBaseUrl
  if (injected) return injected.replace(/\/+$/, '')

  // 3. 默认值
  return DEFAULT_SERVER_BASE_URL
}

// ==================== 对外 API ====================

/**
 * 获取 REST API 基础地址（origin，不含路径）
 *
 * 调用方自行拼接 API 路径，例如：
 * ```ts
 * const API_BASE = getApiBase() + '/api/v1/market'
 * ```
 */
export function getApiBase(): string {
  return getServerBaseUrl()
}

/**
 * 获取实时行情 WebSocket 完整地址
 *
 * 自动将 http(s):// 协议转换为 ws(s)://，
 * 返回形如 `ws://127.0.0.1:8100/ws/market` 的完整 URL。
 */
export function getWsUrl(): string {
  const base = getServerBaseUrl()
  const wsBase = base.replace(/^http:/i, 'ws:').replace(/^https:/i, 'wss:')
  return `${wsBase}/ws/market`
}
