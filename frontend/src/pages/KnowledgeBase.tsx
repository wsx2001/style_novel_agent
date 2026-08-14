import { PagePlaceholder } from '@/components/PagePlaceholder'

/**
 * 知识库页：角色卡 / 世界观卡 / 术语表 / 文风卡 / 事件卡 管理。
 * 该页面既可作为全局入口（/knowledge），也可作为项目子页（/project/:id/knowledge）。
 */
export default function KnowledgeBase() {
  return (
    <PagePlaceholder
      title="知识库"
      description="管理角色卡、世界观卡、术语表、文风卡与事件卡"
    >
      <p className="text-sm text-slate-400">
        尚未实现。后续将提供卡片分类标签、搜索筛选、手动新建与导入解析。
      </p>
    </PagePlaceholder>
  )
}
