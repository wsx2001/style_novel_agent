/**
 * 提示词模板类型（对应后端 PromptTemplate 模型，docs/TECHv1.md §4.3 / §5.7）。
 * 注意：前端采用 camelCase 形态（projectId / isSystem / createdAt），
 * 与后端 snake_case JSON（project_id / is_system / created_at）的映射在 api/promptTemplates.ts 完成。
 */

/** 模板作用域：global 全局 / project 项目级 */
export type PromptTemplateScope = 'global' | 'project'

/** 提示词模板 */
export interface PromptTemplate {
  id: string
  name: string
  content: string
  scope: PromptTemplateScope
  projectId: string | null
  isSystem: boolean
  createdAt: string
  updatedAt: string
}

/** 创建模板请求体（scope=project 时 projectId 必填） */
export interface PromptTemplateCreate {
  name: string
  content: string
  scope: PromptTemplateScope
  projectId?: string
}

/** 更新模板请求体（仅显式传入的字段生效） */
export interface PromptTemplateUpdate {
  name?: string
  content?: string
  scope?: PromptTemplateScope
}

/** 复制模板请求体 */
export interface PromptTemplateDuplicate {
  newName: string
  scope: PromptTemplateScope
  projectId?: string
}
