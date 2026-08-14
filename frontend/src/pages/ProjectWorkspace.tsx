import { useEffect } from 'react'
import { NavLink, Outlet, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '@/api'
import { cn } from '@/lib/utils'
import { useAppStore } from '@/store'

/** 项目内子导航：章节 / 文档 / 知识库 / 设置 */
const TABS = [
  { path: 'chapters', label: '章节', icon: '📝' },
  { path: 'documents', label: '文档', icon: '📄' },
  { path: 'knowledge', label: '知识库', icon: '🗂️' },
  { path: 'settings', label: '设置', icon: '⚙️' },
]

/**
 * 项目工作台：
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

  return (
    <div className="flex min-h-full">
      <nav className="flex w-44 shrink-0 flex-col border-r border-border bg-card px-2 py-4">
        <div className="mb-3 px-2">
          <p className="text-[10px] uppercase tracking-wide text-slate-400">项目</p>
          <h1 className="truncate text-sm font-semibold text-foreground">{project?.title ?? '…'}</h1>
        </div>
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
  )
}
