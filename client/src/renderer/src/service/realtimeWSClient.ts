/**
 * ===================================
 * 实时行情 WebSocket 客户端 (Realtime WS Client)
 * ===================================
 *
 * 职责:
 * 1. 管理与后端 /ws/market 的 WebSocket 连接（地址由 serverConfig 动态提供）
 * 2. 提供订阅/退订 API (quotes / depth 频道)
 * 3. 自动重连 + 心跳保活
 * 4. 回调分发: 各组件注册 listener 接收推送
 */

import type { RealtimeQuote } from './marketDataService'
import { getWsUrl } from './serverConfig'

// ==================== 类型定义 ====================

export interface DepthData {
  symbol: string
  bids: [number, number][] // [[price, volume], ...]
  asks: [number, number][]
  timestamp?: number
}

export type QuotesCallback = (quotes: RealtimeQuote[]) => void
export type DepthCallback = (depth: DepthData) => void
export type StatusCallback = (status: string) => void

interface Subscription {
  channel: 'quotes' | 'depth'
  symbols: Set<string>
  callback: QuotesCallback | DepthCallback
}

// ==================== WebSocket 客户端 ====================

const WS_URL = getWsUrl()
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 15000, 30000]
const HEARTBEAT_INTERVAL = 25000

class RealtimeWSClient {
  private ws: WebSocket | null = null
  private reconnectAttempt = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private connected = false
  private destroyed = false

  // 订阅管理
  private quotesListeners: Map<string, QuotesCallback> = new Map() // id → callback
  private depthListeners: Map<string, DepthCallback> = new Map()
  private statusListeners: Set<StatusCallback> = new Set()

  // 已订阅的标的 (跟踪当前状态，重连时恢复)
  private subscribedQuotes: Set<string> = new Set()
  private subscribedDepth: Set<string> = new Set()

  // 上游状态
  private _upstreamStatus: string = 'disconnected'

  get upstreamStatus(): string {
    return this._upstreamStatus
  }

  get isConnected(): boolean {
    return this.connected
  }

  // ==================== 连接管理 ====================

  connect(): void {
    if (this.destroyed) return
    if (this.ws && (this.ws.readyState === WebSocket.CONNECTING || this.ws.readyState === WebSocket.OPEN)) {
      return
    }
    this._createConnection()
  }

  disconnect(): void {
    this.destroyed = true
    this._cleanup()
  }

  private _createConnection(): void {
    try {
      this.ws = new WebSocket(WS_URL)
    } catch (e) {
      console.warn('[RealtimeWS] WebSocket 创建失败:', e)
      this._scheduleReconnect()
      return
    }

    this.ws.onopen = () => {
      console.log('[RealtimeWS] 已连接')
      this.connected = true
      this.reconnectAttempt = 0
      this._startHeartbeat()
      // 恢复订阅
      this._resubscribeAll()
    }

    this.ws.onmessage = (event) => {
      this._handleMessage(event.data)
    }

    this.ws.onclose = () => {
      console.log('[RealtimeWS] 连接关闭')
      this.connected = false
      this._stopHeartbeat()
      if (!this.destroyed) {
        this._scheduleReconnect()
      }
    }

    this.ws.onerror = (err) => {
      console.warn('[RealtimeWS] 连接错误:', err)
    }
  }

  private _scheduleReconnect(): void {
    if (this.destroyed) return
    if (this.reconnectTimer) return

    const delay = RECONNECT_DELAYS[Math.min(this.reconnectAttempt, RECONNECT_DELAYS.length - 1)]
    console.log(`[RealtimeWS] ${delay / 1000}s 后重连 (第 ${this.reconnectAttempt + 1} 次)`)
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.reconnectAttempt++
      this._createConnection()
    }, delay)
  }

  private _cleanup(): void {
    this._stopHeartbeat()
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.onclose = null
      this.ws.onerror = null
      this.ws.onmessage = null
      this.ws.close()
      this.ws = null
    }
    this.connected = false
  }

  // ==================== 心跳 ====================

  private _startHeartbeat(): void {
    this._stopHeartbeat()
    this.heartbeatTimer = setInterval(() => {
      this._send({ op: 'ping' })
    }, HEARTBEAT_INTERVAL)
  }

  private _stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  // ==================== 消息处理 ====================

  private _handleMessage(raw: string): void {
    let msg: any
    try {
      msg = JSON.parse(raw)
    } catch {
      return
    }

    const op = msg.op

    if (op === 'quotes') {
      const data = msg.data as RealtimeQuote[]
      this.quotesListeners.forEach((cb) => cb(data))
    } else if (op === 'depth') {
      const data = msg.data as DepthData
      this.depthListeners.forEach((cb) => cb(data))
    } else if (op === 'status') {
      this._upstreamStatus = msg.upstream || 'unknown'
      this.statusListeners.forEach((cb) => cb(this._upstreamStatus))
    } else if (op === 'pong') {
      // heartbeat OK
    } else if (op === 'error') {
      console.warn('[RealtimeWS] 服务端错误:', msg.message)
    }
  }

  // ==================== 订阅 API ====================

  /**
   * 订阅实时行情 (quotes 频道)
   * @param id 唯一订阅标识 (用于退订)
   * @param symbols 标的代码列表
   * @param callback 收到行情时的回调
   */
  subscribeQuotes(id: string, symbols: string[], callback: QuotesCallback): void {
    this.quotesListeners.set(id, callback)
    const newSymbols = symbols.filter((s) => !this.subscribedQuotes.has(s))
    for (const s of symbols) {
      this.subscribedQuotes.add(s)
    }
    if (newSymbols.length > 0) {
      this._send({ op: 'subscribe', channel: 'quotes', symbols: newSymbols })
    }
    // 确保连接存在
    this.connect()
  }

  /**
   * 退订实时行情
   */
  unsubscribeQuotes(id: string, symbols?: string[]): void {
    this.quotesListeners.delete(id)
    if (symbols) {
      // 检查是否还有其他 listener 需要这些 symbols
      // 简单处理: 不主动退订，减少上下游交互复杂度
      // 只有所有 listener 都移除后才退订
      if (this.quotesListeners.size === 0) {
        this._send({ op: 'unsubscribe', channel: 'quotes', symbols: [...this.subscribedQuotes] })
        this.subscribedQuotes.clear()
      }
    }
  }

  /**
   * 订阅五档盘口 (depth 频道)
   */
  subscribeDepth(id: string, symbols: string[], callback: DepthCallback): void {
    this.depthListeners.set(id, callback)
    const newSymbols = symbols.filter((s) => !this.subscribedDepth.has(s))
    for (const s of symbols) {
      this.subscribedDepth.add(s)
    }
    if (newSymbols.length > 0) {
      this._send({ op: 'subscribe', channel: 'depth', symbols: newSymbols })
    }
    this.connect()
  }

  /**
   * 退订五档盘口
   */
  unsubscribeDepth(id: string, symbols?: string[]): void {
    this.depthListeners.delete(id)
    if (symbols && this.depthListeners.size === 0) {
      this._send({ op: 'unsubscribe', channel: 'depth', symbols: [...this.subscribedDepth] })
      this.subscribedDepth.clear()
    }
  }

  /**
   * 监听上游连接状态变化
   */
  onStatusChange(callback: StatusCallback): () => void {
    this.statusListeners.add(callback)
    return () => this.statusListeners.delete(callback)
  }

  /**
   * 更新订阅列表 (替换模式: 用新的 symbols 替换旧的)
   */
  updateQuotesSubscription(id: string, symbols: string[], callback: QuotesCallback): void {
    this.quotesListeners.set(id, callback)

    // 计算需要新增订阅的
    const newSymbols = symbols.filter((s) => !this.subscribedQuotes.has(s))
    for (const s of symbols) {
      this.subscribedQuotes.add(s)
    }
    if (newSymbols.length > 0) {
      this._send({ op: 'subscribe', channel: 'quotes', symbols: newSymbols })
    }
    this.connect()
  }

  // ==================== 内部方法 ====================

  private _send(data: object): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
    }
  }

  private _resubscribeAll(): void {
    if (this.subscribedQuotes.size > 0) {
      this._send({ op: 'subscribe', channel: 'quotes', symbols: [...this.subscribedQuotes] })
    }
    if (this.subscribedDepth.size > 0) {
      this._send({ op: 'subscribe', channel: 'depth', symbols: [...this.subscribedDepth] })
    }
  }
}

// ==================== 导出单例 ====================

export const realtimeWS = new RealtimeWSClient()
