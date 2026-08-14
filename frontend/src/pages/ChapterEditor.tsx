import { PagePlaceholder } from '@/components/PagePlaceholder'

/**
 * 章节编辑器页：章节树 + Markdown 编辑区（Milkdown）+ AI 续写/重写。
 * TODO: 章节树组件（components/editor/）、Milkdown 编辑器集成、AI 生成面板。
 */
export default function ChapterEditor() {
  return (
    <PagePlaceholder
      title="章节编辑器"
      description="编写章节正文，使用 AI 续写 / 重写"
    >
      <p className="text-sm text-slate-400">
        尚未实现。后续将集成 Milkdown 编辑器、章节树、版本快照与 AI 生成候选面板。
      </p>
    </PagePlaceholder>
  )
}
