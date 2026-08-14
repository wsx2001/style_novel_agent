import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'

/**
 * 应用整体布局：
 * 左侧导航栏（项目列表 / 知识库 / 设置）+ 右侧主内容区。
 * 子路由通过 <Outlet /> 渲染在右侧内容区。
 */
export function AppLayout() {
  return (
    <div className="flex h-full">
      <Sidebar />
      <main className="min-w-0 flex-1 overflow-auto bg-background">
        <Outlet />
      </main>
    </div>
  )
}
