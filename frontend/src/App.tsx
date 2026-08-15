import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from '@/components/layout/AppLayout'
import ProjectList from '@/pages/ProjectList'
import ProjectWorkspace from '@/pages/ProjectWorkspace'
import KnowledgeBase from '@/pages/KnowledgeBase'
import DocumentParse from '@/pages/DocumentParse'
import ChapterEditor from '@/pages/ChapterEditor'
import ConversationWorkspace from '@/pages/ConversationWorkspace'
import Settings from '@/pages/Settings'

/**
 * 应用路由表：
 *   /                                项目列表
 *   /knowledge                       知识库（全局入口，需先选项目）
 *   /settings                        设置（全局）
 *   /project/:projectId              项目工作台
 *     /chapters                      章节编辑器（默认子页）
 *     /documents                     文档解析
 *     /knowledge                     知识库
 *     /settings                      设置
 */
export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<ProjectList />} />
        <Route path="/knowledge" element={<KnowledgeBase />} />
        <Route path="/settings" element={<Settings />} />

        <Route path="/project/:projectId" element={<ProjectWorkspace />}>
          <Route index element={<Navigate to="chapters" replace />} />
          <Route path="chapters" element={<ChapterEditor />} />
          <Route path="documents" element={<DocumentParse />} />
          <Route path="knowledge" element={<KnowledgeBase />} />
          <Route path="conversation" element={<ConversationWorkspace />} />
          <Route path="settings" element={<Settings />} />
        </Route>

        {/* 未匹配路由回退到项目列表 */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
