import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import App from './App.tsx'
import { reportClientError } from './api/logs'
import ErrorBoundary from './components/ErrorBoundary'

// TanStack Query 全局配置：本地应用，关掉自动重试，加快失败反馈
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
})

/**
 * 全局错误上报：未捕获异常 / 未处理 Promise 拒绝 → 后端 error.log。
 * React 渲染错误由 ErrorBoundary 兜底上报（react 来源）。
 */
function installGlobalErrorReporting(): void {
  window.addEventListener('error', (event) => {
    void reportClientError({
      source: 'window',
      message: event.message,
      stack: event.error?.stack,
      url: event.filename,
    })
  })

  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason
    void reportClientError({
      source: 'unhandledrejection',
      message: reason instanceof Error ? reason.message : String(reason),
      stack: reason instanceof Error ? reason.stack : undefined,
    })
  })
}

installGlobalErrorReporting()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
)
