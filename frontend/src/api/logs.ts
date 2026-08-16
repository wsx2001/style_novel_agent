import client from './client'

/** 浏览器会话级客户端 ID：同一次前端会话的多条错误可相互关联 */
const CLIENT_ID =
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID().slice(0, 8)
    : `c-${Date.now().toString(36)}`

// 节流：两次上报之间最小间隔，避免错误风暴刷爆 error.log
const MIN_INTERVAL_MS = 2000
let lastReportAt = 0

export interface ClientErrorInput {
  source?: 'window' | 'unhandledrejection' | 'react' | 'fetch'
  message?: string
  stack?: string
  url?: string
  detail?: string
}

/**
 * 静默上报前端错误到后端 /api/v1/logs/client-error。
 * - 永不抛出（失败仅 console.warn）
 * - 节流 + 截断，保证不阻塞业务也不撑爆日志
 */
export async function reportClientError(input: ClientErrorInput): Promise<void> {
  const now = Date.now()
  if (now - lastReportAt < MIN_INTERVAL_MS) return
  lastReportAt = now

  try {
    await client.post('/logs/client-error', {
      client_id: CLIENT_ID,
      source: input.source ?? 'window',
      message: String(input.message ?? '').slice(0, 500),
      stack: String(input.stack ?? '').slice(0, 2000),
      url: input.url ?? window.location.href,
      timestamp: Math.floor(now / 1000),
    })
  } catch (err) {
    // 上报失败不能影响业务；打印到控制台便于本地调试
    console.warn('[FictionForge] 前端错误上报失败：', err)
  }
}
