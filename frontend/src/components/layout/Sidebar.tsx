import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/utils'

/** 侧边栏导航项：项目列表、知识库、设置（TECH.md §2 前端布局） */
const NAV_ITEMS = [
  {
    to: '/',
    label: '项目列表',
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5" aria-hidden="true">
        <path d="M2 5a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5Z" />
      </svg>
    ),
  },
  {
    to: '/knowledge',
    label: '知识库',
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5" aria-hidden="true">
        <path d="M10 4.5 2.5 8l7.5 3.5L17.5 8 10 4.5Zm-7 7V14l7 3.5 7-3.5v-2.5L10 14.5 3 11.5Z" />
      </svg>
    ),
  },
  {
    to: '/settings',
    label: '设置',
    icon: (
      <svg viewBox="0 0 20 20" fill="currentColor" className="h-5 w-5" aria-hidden="true">
        <path
          fillRule="evenodd"
          d="M10 6.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7ZM2 9h1.05a6.9 6.9 0 0 1 .7-1.7L2.6 6.1l1.5-1.5 1.2 1.15A6.9 6.9 0 0 1 7 5.05V4h2v1.05a6.9 6.9 0 0 1 1.7.7l1.2-1.15 1.5 1.5-1.15 1.2a6.9 6.9 0 0 1 .7 1.7H14v2h-1.05a6.9 6.9 0 0 1-.7 1.7l1.15 1.2-1.5 1.5-1.2-1.15a6.9 6.9 0 0 1-1.7.7V16H9v-1.05a6.9 6.9 0 0 1-1.7-.7l-1.2 1.15-1.5-1.5 1.15-1.2a6.9 6.9 0 0 1-.7-1.7H2V9Zm0-2h.2A9 9 0 0 1 2 9h1.05A8.9 8.9 0 0 1 2 7Zm0 2h1.05a8.9 8.9 0 0 1-1.05 2H2V9Z"
          clipRule="evenodd"
        />
      </svg>
    ),
  },
]

export function Sidebar() {
  return (
    <aside className="flex w-56 shrink-0 flex-col bg-sidebar text-sidebar-foreground">
      {/* 应用标识 */}
      <div className="flex items-center gap-2 px-4 py-5">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-sidebar-accent text-sm font-bold text-white">
          FF
        </span>
        <span className="text-base font-semibold text-white">FictionForge</span>
      </div>

      {/* 导航 */}
      <nav className="flex flex-1 flex-col gap-1 px-3">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-sidebar-active text-white'
                  : 'text-sidebar-foreground hover:bg-sidebar-active/60 hover:text-white',
              )
            }
          >
            {item.icon}
            {item.label}
          </NavLink>
        ))}
      </nav>

      {/* 底部版本信息 */}
      <div className="px-4 py-4 text-xs text-sidebar-muted">FictionForge v0.2 · 本地运行</div>
    </aside>
  )
}
