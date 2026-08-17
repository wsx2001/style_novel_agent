import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useParseSessionStore } from '@/store/parseSession'

/**
 * 全局解析进度悬浮面板：解析中 / 解析完成待导入 时在项目任意标签页可见。
 *
 * 文档解析的进度与结果原先只在文档页内可见，切换页面即丢失；现在解析会话
 * 存于全局 store，这里在项目工作台全局渲染一个悬浮卡片：
 * - 点击跳转到文档页查看完整进度与候选卡片；
 * - 右上角 ✕ 可关闭（clear 会话），避免错误提示常驻；
 * - 文档页内不显示（文档页已有 ParseProgressPanel / ParseCandidates，避免重复）。
 */
export function ParseProgressOverlay() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const location = useLocation()

  const status = useParseSessionStore((s) => s.status)
  const parseTarget = useParseSessionStore((s) => s.parseTarget)
  const progressUnits = useParseSessionStore((s) => s.progressUnits)
  const progressTotal = useParseSessionStore((s) => s.progressTotal)
  const candidates = useParseSessionStore((s) => s.candidates)
  const error = useParseSessionStore((s) => s.error)
  const sessionProjectId = useParseSessionStore((s) => s.projectId)
  const clearParse = useParseSessionStore((s) => s.clear)

  // 无项目上下文 / 在文档页（已有完整面板）/ 无进行中会话 / 非当前项目会话 → 不显示
  if (!projectId || location.pathname.endsWith('/documents')) return null
  if (sessionProjectId !== projectId) return null
  if (status !== 'running' && status !== 'done' && status !== 'error') return null

  const completed = progressUnits.filter(
    (u) => u.status === 'done' || u.status === 'error' || u.status === 'skipped',
  ).length
  const pct = progressTotal > 0 ? Math.min(100, Math.round((completed / progressTotal) * 100)) : 0
  const docName = parseTarget?.filename ?? ''
  const gotoDocuments = () => navigate(`/project/${projectId}/documents`)

  return (
    <div className="fixed bottom-4 right-4 z-40 w-72 overflow-hidden rounded-xl border border-border bg-card shadow-xl">
      <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
        <span className="text-[11px] font-medium text-slate-500">文档解析</span>
        <button
          type="button"
          onClick={clearParse}
          aria-label="关闭"
          className="rounded p-0.5 text-xs text-slate-400 hover:text-foreground"
        >
          ✕
        </button>
      </div>
      <button
        type="button"
        onClick={gotoDocuments}
        className="w-full px-4 py-3 text-left transition-colors hover:bg-background/60"
      >
        {status === 'running' && (
          <>
            <p className="flex items-center justify-between text-xs font-medium text-foreground">
              <span className="truncate">正在解析《{docName}》</span>
              <span className="ml-2 shrink-0 text-slate-400">
                {completed}/{progressTotal} 章
              </span>
            </p>
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
            <p className="mt-1.5 text-[11px] text-primary">查看解析进度 →</p>
          </>
        )}
        {status === 'done' && (
          <p className="text-xs font-medium text-emerald-600">
            解析完成 · {candidates?.length ?? 0} 条候选待确认导入
            <span className="mt-1 block text-[11px] text-primary">查看结果 →</span>
          </p>
        )}
        {status === 'error' && (
          <p className="text-xs font-medium text-danger">解析失败：{error ?? '请到文档页查看'}</p>
        )}
      </button>
    </div>
  )
}
