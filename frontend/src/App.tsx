import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from '@/components/layout/AppLayout'
import { PagePlaceholder } from '@/components/PagePlaceholder'
import ProjectList from '@/pages/ProjectList'
import ProjectWorkspace from '@/pages/ProjectWorkspace'
import KnowledgeBase from '@/pages/KnowledgeBase'
import DocumentParse from '@/pages/DocumentParse'
import ChapterEditor from '@/pages/ChapterEditor'
import Settings from '@/pages/Settings'

/**
 * 应用路由表：
 *   /                                项目列表
 *   /project/:projectId              项目工作台（含子页）
 *   /project/:projectId/knowledge    知识库
 *   /project/:projectId/documents    文档解析
 *   /project/:projectId/chapters     章节编辑器
 *   /knowledge                       知识库（全局入口）
 *   /settings                        设置
 */
export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<ProjectList />} />
        <Route path="/knowledge" element={<KnowledgeBase />} />
        <Route path="/settings" element={<Settings />} />

        <Route path="/project/:projectId" element={<ProjectWorkspace />}>
          <Route
            index
            element={
              <PagePlaceholder title="项目概览" description="项目统计与最近更新">
                <p className="text-sm text-slate-400">项目概览内容将在后续实现。</p>
              </PagePlaceholder>
            }
          />
          <Route path="knowledge" element={<KnowledgeBase />} />
          <Route path="documents" element={<DocumentParse />} />
          <Route path="chapters" element={<ChapterEditor />} />
        </Route>

        {/* 未匹配路由回退到项目列表 */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
