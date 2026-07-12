/**
 * ===================================
 * 统一市场数据服务 (Unified Market Data Service)
 * ===================================
 *
 * 职责：
 * 1. 提供统一的标的列表、K线数据、实时行情接口
 * 2. 根据市场类型自动路由到对应数据源
 *    - crypto: 直连 Binance / OKX (已有前端实现)
 *    - cn_stock / cn_etf / cn_futures: 后端 Market Data Gateway
 * 3. 前端缓存层：避免重复请求
 */

import { getApiBase } from './serverConfig'

// ==================== 类型定义 ====================

export interface MarketType {
  type: string
  name: string
  description: string
  data_source: string
  icon: string
  enabled: boolean
}

export interface SymbolInfo {
  symbol: string
  name: string
  market_type: string
  exchange: string
  data_source: string
  base_currency: string
  status: string
  current_price?: number | null
  change_percent?: number | null
}

export interface KLineBar {
  time: number // Unix 秒
  open: number
  high: number
  low: number
  close: number
  volume?: number
  turnover?: number
}

export interface RealtimeQuote {
  symbol: string
  name: string
  price?: number | null
  change?: number | null
  change_percent?: number | null
  volume?: number | null
  turnover?: number | null
  high?: number | null
  low?: number | null
  open?: number | null
  prev_close?: number | null
  update_time?: string | null
}

// ==================== 后端 API 基础地址 ====================

const API_BASE = getApiBase() + '/api/v1/market'

// ==================== 前端缓存 ====================

interface CacheEntry<T> {
  data: T
  timestamp: number
}

const cache = {
  marketTypes: null as CacheEntry<MarketType[]> | null,
  symbols: new Map<string, CacheEntry<SymbolInfo[]>>(),
}

const CACHE_TTL = {
  marketTypes: 60 * 60 * 1000,   // 1 小时
  symbols: 10 * 60 * 1000,       // 10 分钟
}

function isCacheValid<T>(entry: CacheEntry<T> | null | undefined, ttl: number): entry is CacheEntry<T> {
  return entry !== null && entry !== undefined && (Date.now() - entry.timestamp) < ttl
}

// ==================== API 请求 ====================

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`)
  }
  return response.json()
}

// ==================== 市场类型 ====================

export async function getMarketTypes(): Promise<MarketType[]> {
  if (isCacheValid(cache.marketTypes, CACHE_TTL.marketTypes)) {
    return cache.marketTypes.data
  }

  const resp = await fetchJson<{ types: MarketType[] }>(`${API_BASE}/types`)
  cache.marketTypes = { data: resp.types, timestamp: Date.now() }
  return resp.types
}

// ==================== 标的列表 ====================

export async function getSymbols(marketType: string, forceRefresh = false): Promise<SymbolInfo[]> {
  if (!forceRefresh && isCacheValid(cache.symbols.get(marketType), CACHE_TTL.symbols)) {
    return cache.symbols.get(marketType)!.data
  }

  const resp = await fetchJson<{ market_type: string; total: number; symbols: SymbolInfo[] }>(
    `${API_BASE}/symbols?type=${encodeURIComponent(marketType)}${forceRefresh ? '&refresh=true' : ''}`
  )
  cache.symbols.set(marketType, { data: resp.symbols, timestamp: Date.now() })
  return resp.symbols
}

// ==================== 标的搜索 ====================

export async function searchSymbols(query: string, marketType = ''): Promise<SymbolInfo[]> {
  const params = new URLSearchParams({ q: query })
  if (marketType) params.set('type', marketType)

  const resp = await fetchJson<{ query: string; total: number; symbols: SymbolInfo[] }>(
    `${API_BASE}/symbols/search?${params.toString()}`
  )
  return resp.symbols
}

// ==================== K 线数据 ====================

export async function getKLineData(
  symbol: string,
  marketType: string,
  period: string,
  from: number,
  to: number,
  limit = 300
): Promise<{ bars: KLineBar[]; noData: boolean }> {
  const params = new URLSearchParams({
    symbol,
    type: marketType,
    period,
    limit: String(limit),
  })
  if (from > 0) params.set('start', String(from))
  if (to > 0) params.set('end', String(to))

  const resp = await fetchJson<{
    symbol: string
    period: string
    data: KLineBar[]
    no_data: boolean
  }>(`${API_BASE}/kline?${params.toString()}`)

  return { bars: resp.data, noData: resp.no_data }
}

// ==================== 实时行情 ====================

export async function getRealtimeQuotes(
  symbols: string[],
  marketType = ''
): Promise<RealtimeQuote[]> {
  const params = new URLSearchParams({
    symbols: symbols.join(','),
  })
  if (marketType) params.set('type', marketType)

  const resp = await fetchJson<{ quotes: RealtimeQuote[] }>(
    `${API_BASE}/realtime?${params.toString()}`
  )
  return resp.quotes
}

// ==================== 辅助方法 ====================

/**
 * 根据市场类型判断是否需要通过后端获取 K 线
 * crypto 类型由前端直连，其他类型走后端 API
 */
export function isBackendMarket(marketType: string): boolean {
  return marketType !== 'crypto'
}

/**
 * 猜测市场类型（前端版本，与后端 _guess_market_type 逻辑一致）
 */
export function guessMarketType(symbol: string): string {
  const s = symbol.trim()
  if (s.includes('/')) return 'crypto'
  // 港股: HKxxxxx
  if (s.toUpperCase().startsWith('HK') && /^\d+$/.test(s.slice(2))) return 'hk_stock'
  if (/^\d{6}$/.test(s)) {
    if (s.startsWith('5')) return 'cn_etf'
    if (s.startsWith('15') || s.startsWith('16') || s.startsWith('18')) return 'cn_etf'
    return 'cn_stock'
  }
  // 纯字母 → 美股
  if (/^[A-Za-z]+$/.test(s)) return 'us_stock'
  return 'cn_stock'
}

/**
 * 清除前端缓存
 */
export function clearCache(): void {
  cache.marketTypes = null
  cache.symbols.clear()
}

// ==================== 财务数据 ====================

export interface FinancialsResponse {
  symbol: string
  type: string
  data: Record<string, any>[]
}

/**
 * 获取标的财务数据
 */
export async function getFinancials(
  symbol: string,
  type: 'income' | 'balance' | 'cash_flow' | 'metrics' | 'shares' = 'metrics',
  limit = 8
): Promise<FinancialsResponse> {
  const params = new URLSearchParams({ symbol, type, limit: String(limit) })
  return fetchJson<FinancialsResponse>(`${API_BASE}/financials?${params.toString()}`)
}
