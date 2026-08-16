import { useParams } from 'react-router-dom'
import ProjectModelSettings from '@/components/settings/ProjectModelSettings'

/**
 * 项目设置页（docs/TECHv1.1.md §5.2 / PRD v1.1 §4.2）。
 * 当前包含「模型设置」区域：项目可覆盖全局默认提供商与模型，或继承全局默认。
 */
export default function ProjectSettings() {
  const { projectId } = useParams<{ projectId: string }>()

  return (
    <div className="mx-auto min-h-full max-w-3xl space-y-6 bg-background px-6 py-6">
      <header>
        <h1 className="text-2xl font-bold text-foreground">项目设置</h1>
        <p className="mt-1 text-sm text-slate-500">
          配置项目的默认模型提供商与模型；未设置时继承全局默认。
        </p>
      </header>

      {projectId && <ProjectModelSettings projectId={projectId} />}
    </div>
  )
}
