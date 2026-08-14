import { useEffect } from 'react'
import { NavLink, Outlet, useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { getErrorMessage } from '@/api/client'
import { projectsApi, type ExportFormat } from '@/api'
import { cn } from '@/lib/utils'
import { useAppStore } from '@/store'

/** 项目内子导航：章节 / 文档 / 知识库 / 设置 */
const TABS = [
  { path: 'chapters', label: '章节', icon: '📝' },
  { path: 'documents', label: '文档', icon: '📄' },
  { path: 'knowledge', label: '知识库', icon: '🗂️' },
  { path: 'settings', label: '设置', icon: '⚙️' },
]

/** 导出格式选项 */
const EXPORT_OPTIONS: Array<{ format: ExportFormat; label: string }> = [
  { format: 'txt', label: 'txt' },
  { format: 'markdown', label: 'md' },
  { format: 'json', label: 'json' },
  { format: 'docx', label: 'docx' },
]

/**
 * 项目工作台：
 * - 顶栏：项目标题 + 导出按钮
 * - 左侧：项目内导航（文档 / 知识库 / 章节 / 设置）
 * - 右侧：子页面内容区（<Outlet />）
 */
export default function ProjectWorkspace() {
  const { projectId } = useParams<{ projectId: string }>()
  const setCurrentProjectId = useAppStore((s) => s.setCurrentProjectId)

  // 记录当前打开的项目，供全局状态使用
  useEffect(() => {
    if (projectId) setCurrentProjectId(projectId)
  }, [projectId, setCurrentProjectId])

  const { data: project } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => projectsApi.get(projectId!),
    enabled: !!projectId,
  })

  const exportMutation = useMutation({
    mutationFn: (format: ExportFormat) => projectsApi.exportFile(projectId!, format),
  })

  return (
    <div className="flex min-h-full flex-col">
      {/* 顶栏：项目名 + 导出 */}
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-card px-4">
        <h1 className="truncate text-sm font-semibold text-foreground">{project?.title ?? '…'}</h1>
        <div className="flex shrink-0 items-center gap-1.5">
          <span className="text-xs text-slate-400">导出</span>
          {EXPORT_OPTIONS.map((opt) => (
            <button
              key={opt.format}
              className="rounded-md border border-border px-2 py-1 text-xs font-medium text-slate-600 hover:border-primary/50 hover:text-primary disabled:opacity-50"
              disabled={!projectId || exportMutation.isPending}
              onClick={() => exportMutation.mutate(opt.format)}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </header>
      {exportMutation.isError && (
        <p className="border-b border-border bg-card px-4 py-1.5 text-xs text-danger">
          导出失败：{getErrorMessage(exportMutation.error)}
        </p>
      )}

      <div className="flex min-h-0 flex-1">
        <nav className="flex w-44 shrink-0 flex-col border-r border-border bg-card px-2 py-4">
          {TABS.map((tab) => (
            <NavLink
              key={tab.path}
              to={tab.path}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors',
                  isActive
                    ? 'bg-primary/10 font-medium text-primary'
                    : 'text-slate-600 hover:bg-background hover:text-foreground',
                )
              }
            >
              <span aria-hidden="true">{tab.icon}</span>
              {tab.label}
            </NavLink>
          ))}
          <NavLink
            to="/"
            className="mt-auto flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-slate-500 hover:bg-background hover:text-foreground"
          >
            ← 返回项目列表
          </NavLink>
        </nav>
        <div className="min-w-0 flex-1 overflow-auto">
          <Outlet />
        </div>
      </div>
    </div>
  )
}
