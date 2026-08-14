import axios, { AxiosError } from 'axios'

/**
 * 统一 axios 实例。
 * - baseURL 为 /api/v1（开发环境由 Vite 代理到 http://127.0.0.1:8000）
 * - 生产环境 FastAPI 直接托管前端构建产物，同源请求无需代理
 */
const client = axios.create({
  baseURL: '/api/v1',
  timeout: 60_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器：可在此注入通用头（本地应用暂无需 token）
client.interceptors.request.use((config) => config)

// 响应拦截器：统一错误处理
client.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorBody>) => {
    // 网络错误（后端未启动等）
    if (!error.response) {
      console.error('[FictionForge] 网络请求失败：', error.message)
    }
    return Promise.reject(error)
  },
)

/** FastAPI HTTPException 的响应体结构 */
export interface ApiErrorBody {
  detail?: string | Array<{ msg?: string; loc?: unknown[] }>
}

/** 从异常中提取人类可读的错误信息 */
export function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError<ApiErrorBody>(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail.map((d) => d.msg ?? '参数错误').join('；')
    }
    if (error.response?.status === 401) return '未授权'
    if (error.response?.status === 404) return '资源不存在'
    if (error.code === 'ECONNABORTED') return '请求超时'
  }
  return error instanceof Error ? error.message : '未知错误'
}

export default client
