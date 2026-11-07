/** 统一 API 客户端：REST 封装 + SSE 流式解析 */

const BASE = ''

export class ApiError extends Error {
  code: string
  hint?: string
  status: number
  constructor(message: string, opts: { code?: string; hint?: string; status?: number } = {}) {
    super(message)
    this.code = opts.code || 'error'
    this.hint = opts.hint
    this.status = opts.status || 0
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: {
      ...(init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(init.headers || {}),
    },
  })
  const text = await res.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = { message: text }
  }
  if (!res.ok) {
    const err = (data || {}) as { message?: string; hint?: string; code?: string }
    throw new ApiError(err.message || `请求失败 (${res.status})`, {
      code: err.code,
      hint: err.hint,
      status: res.status,
    })
  }
  return data as T
}

export const api = {
  get: <T>(p: string) => request<T>(p),
  post: <T>(p: string, body?: unknown) =>
    request<T>(p, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(p: string, body?: unknown) =>
    request<T>(p, { method: 'PUT', body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(p: string, body?: unknown) =>
    request<T>(p, { method: 'PATCH', body: body === undefined ? undefined : JSON.stringify(body) }),
  del: <T>(p: string) => request<T>(p, { method: 'DELETE' }),
  upload: async <T>(file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<T>('/api/files/upload', { method: 'POST', body: form })
  },
  /** 上传背景图片 / 视频，返回 { url, kind } */
  uploadBackground: async <T>(file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<T>('/api/backgrounds', { method: 'POST', body: form })
  },
}

/** POST + SSE 流；每收到一个事件调用 onEvent，异常统一抛出 ApiError */
export async function streamSSE(
  path: string,
  body: unknown,
  onEvent: (event: Record<string, any>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => '')
    let parsed: any = {}
    try {
      parsed = JSON.parse(text)
    } catch {
      parsed = { message: text || `HTTP ${res.status}` }
    }
    throw new ApiError(parsed.message || `请求失败 (${res.status})`, {
      code: parsed.code,
      hint: parsed.hint,
      status: res.status,
    })
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() || ''
    for (const chunk of chunks) {
      for (const line of chunk.split('\n')) {
        if (!line.startsWith('data: ')) continue
        const payload = line.slice(6).trim()
        if (payload === '[DONE]') return
        try {
          onEvent(JSON.parse(payload))
        } catch {
          /* 忽略心跳等非 JSON 数据 */
        }
      }
    }
  }
}

/** 订阅屏幕演示事件（EventSource），返回关闭函数 */
export function subscribeScreen(sessionId: string, onEvent: (e: Record<string, any>) => void): () => void {
  const es = new EventSource(`${BASE}/api/screen/sessions/${sessionId}/events`)
  es.onmessage = (ev) => {
    try {
      onEvent(JSON.parse(ev.data))
    } catch {
      /* noop */
    }
  }
  es.onerror = () => {
    /* 由后端 keep-alive 维持，忽略瞬时错误 */
  }
  return () => es.close()
}