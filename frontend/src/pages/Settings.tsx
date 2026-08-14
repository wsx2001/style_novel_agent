import { PagePlaceholder } from '@/components/PagePlaceholder'

/**
 * 设置页：全局设置 + 项目设置。
 * 全局：API Key 管理（加密存储）、默认模型、数据目录、免责声明。
 * 项目级：解析确认、生成参数默认值（由路由参数决定作用域）。
 */
export default function Settings() {
  return (
    <PagePlaceholder
      title="设置"
      description="配置 API Key、默认模型、数据目录与内容安全选项"
    >
      <p className="text-sm text-slate-400">
        尚未实现。后续将提供 API Key 管理、模型参数与数据目录设置表单。
      </p>
    </PagePlaceholder>
  )
}
