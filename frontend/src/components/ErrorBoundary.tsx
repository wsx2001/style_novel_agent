import { Component, type ErrorInfo, type ReactNode } from 'react'
import { reportClientError } from '../api/logs'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/**
 * 顶层错误边界：React 渲染错误会卸载整棵组件树，这里兜底捕获，
 * 展示可恢复的错误页并上报后端 error.log（docs/TECHv1.2.md §4）。
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    void reportClientError({
      source: 'react',
      message: error.message,
      stack: String(error.stack ?? ''),
      detail: String(info.componentStack ?? ''),
    })
  }

  handleReload = (): void => {
    window.location.reload()
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children

    return (
      <div style={{ padding: '2rem', fontFamily: 'system-ui, sans-serif' }}>
        <h2>页面出错了</h2>
        <p>
          应用遇到未预期的错误。错误已写入后端日志（<code>data/logs/error.log</code>
          ），可据此排查。
        </p>
        <pre
          style={{
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            background: '#f5f5f5',
            padding: '1rem',
            borderRadius: 8,
            maxHeight: 240,
            overflow: 'auto',
            fontSize: 12,
          }}
        >
          {this.state.error.message}
          {'\n'}
          {this.state.error.stack}
        </pre>
        <button onClick={this.handleReload}>重新加载</button>
      </div>
    )
  }
}
