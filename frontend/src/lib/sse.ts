/**
 * SSE 客户端解析（POST 流式）。
 *
 * 后端续写/重写端点返回 `text/event-stream`，帧格式：
 *     event: <name>\ndata: <json>\n\n
 * 本模块用 fetch 拉取并逐帧解析，回调 onEvent。
 */

/** 解析后的一帧 SSE 事件 */
export interface SSEEvent {
  event: string
  data: string
}

/** 从一帧文本中解析出 event 名与 data */
function parseFrame(frame: string, emit: (ev: SSEEvent) => void): void {
  let event = 'message'
  let data = ''
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data += line.slice(5).trim()
  }
  if (data) emit({ event, data })
}

/**
 * 发起 POST 流式请求并逐帧解析 SSE。
 * - 非 2xx 时读取响应体中的 detail 并抛出
 * - 返回 Promise，流结束（或出错）时 resolve / reject
 */
export async function streamSSE(
  url: string,
  body: unknown,
  onEvent: (ev: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })

  if (!res.ok || !res.body) {
    let detail = `HTTP ${res.status}`
    try {
      const parsed = (await res.json()) as { detail?: string }
      if (typeof parsed.detail === 'string') detail = parsed.detail
    } catch {
      // 非 JSON 响应，保留默认 detail
    }
    throw new Error(detail)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // 以空行切分完整帧；残缺的帧留在 buffer 等下一块
    let sep = buffer.indexOf('\n\n')
    while (sep !== -1) {
      const frame = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      if (frame.trim()) parseFrame(frame, onEvent)
      sep = buffer.indexOf('\n\n')
    }
  }

  // 收尾：处理流末尾残留的帧
  if (buffer.trim()) parseFrame(buffer, onEvent)
}
