import { PagePlaceholder } from '@/components/PagePlaceholder'

/**
 * 项目列表页（应用启动页）。
 * TODO: 项目卡片列表 + 新建项目 + 灵感创作 + 打开数据目录
 */
export default function ProjectList() {
  return (
    <PagePlaceholder
      title="项目列表"
      description="选择或创建一个本地小说项目"
    >
      <p className="text-sm text-slate-400">
        当前没有项目。后续将在此展示项目卡片、新建项目与灵感创作入口。
      </p>
    </PagePlaceholder>
  )
}
