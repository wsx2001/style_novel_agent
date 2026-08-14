import { useEffect } from 'react'
import { NavLink, Outlet, useParams } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { useAppStore } from '@/store'

/**
 * 项目工作台：顶部项目栏 + 项目内子导航（知识库 / 文档 / 章节）+ 子页面内容区。
 * 子路由：
 *   /project/:projectId/knowledge  知识库
 *   /project/:projectId/documents  文档解析
 *   /project/:projectId/chapters   章节编辑器
 */
const WORKSPACE_TABS = [
  { path: 'knowledge', label: '知识库' },
  { path: 'documents', label: '文档' },
  { path: 'chapters', label: '章节' },
]

export default function ProjectWorkspace() {
  const { projectId } = useParams<{ projectId: string }>()
  const setCurrentProjectId = useAppStore((s) => s.setCurrentProjectId)

  // 记录当前打开的项目，供全局状态使用
  useEffect(() => {
    if (projectId) setCurrentProjectId(projectId)
  }, [projectId, setCurrentProjectId])

  return (
    <div className="flex min-h-full flex-col">
      {/* 顶部项目栏 */}
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-card px-6">
        <div className="flex items-baseline gap-3">
          <span className="text-lg font-semibold text-foreground">项目工作台</span>
          <span className="text-sm text-slate-400">项目 ID：{projectId}</span>
        </div>
        {/* TODO: 项目统计、导出按钮 */}
      </header>

      {/* 项目内子导航 */}
      <nav className="flex shrink-0 gap-1 border-b border-border bg-card px-4 pt-2">
        {WORKSPACE_TABS.map((tab) => (
          <NavLink
            key={tab.path}
            to={tab.path}
            className={({ isActive }) =>
              cn(
                'rounded-t-lg px-4 py-2.5 text-sm font-medium transition-colors',
                isActive
                  ? 'border-b-2 border-primary text-primary'
                  : 'text-slate-500 hover:text-foreground',
              )
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>

      {/* 子页面内容区 */}
      <div className="flex-1 overflow-auto">
        <Outlet />
      </div>
    </div>
  )
}
