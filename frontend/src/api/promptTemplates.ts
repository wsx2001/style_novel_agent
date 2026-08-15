import client from './client'
import type {
  PromptTemplate,
  PromptTemplateCreate,
  PromptTemplateDuplicate,
  PromptTemplateScope,
  PromptTemplateUpdate,
} from '@/types'

/**
 * 提示词模板 API（docs/TECHv1.md §5.7）。
 * 后端响应为 snake_case JSON，此处映射为前端 camelCase 类型（见 types/prompt_template.ts）。
 */

function toPromptTemplate(raw: Record<string, unknown>): PromptTemplate {
  return {
    id: raw.id as string,
    name: raw.name as string,
    content: raw.content as string,
    scope: raw.scope as PromptTemplateScope,
    projectId: (raw.project_id as string) ?? null,
    isSystem: raw.is_system as boolean,
    createdAt: raw.created_at as string,
    updatedAt: raw.updated_at as string,
  }
}

export const promptTemplatesApi = {
  /** GET /prompt-templates?scope=&project_id= —— 模板列表 */
  async listPromptTemplates(scope?: PromptTemplateScope, projectId?: string): Promise<PromptTemplate[]> {
    const { data } = await client.get<Record<string, unknown>[]>('/prompt-templates', {
      params: { scope, project_id: projectId },
    })
    return data.map(toPromptTemplate)
  },

  /** POST /prompt-templates —— 创建模板 */
  async createPromptTemplate(payload: PromptTemplateCreate): Promise<PromptTemplate> {
    const { data } = await client.post<Record<string, unknown>>('/prompt-templates', {
      name: payload.name,
      content: payload.content,
      scope: payload.scope,
      ...(payload.projectId ? { project_id: payload.projectId } : {}),
    })
    return toPromptTemplate(data)
  },

  /** GET /prompt-templates/{id} —— 模板详情 */
  async getPromptTemplate(id: string): Promise<PromptTemplate> {
    const { data } = await client.get<Record<string, unknown>>(`/prompt-templates/${id}`)
    return toPromptTemplate(data)
  },

  /** PATCH /prompt-templates/{id} —— 更新模板（仅显式传入的字段） */
  async updatePromptTemplate(id: string, payload: PromptTemplateUpdate): Promise<PromptTemplate> {
    const body: Record<string, unknown> = {}
    if (payload.name != null) body.name = payload.name
    if (payload.content != null) body.content = payload.content
    if (payload.scope != null) body.scope = payload.scope
    const { data } = await client.patch<Record<string, unknown>>(`/prompt-templates/${id}`, body)
    return toPromptTemplate(data)
  },

  /** DELETE /prompt-templates/{id} —— 删除模板（系统内置模板后端返回 403） */
  async deletePromptTemplate(id: string): Promise<void> {
    await client.delete(`/prompt-templates/${id}`)
  },

  /** POST /prompt-templates/{id}/duplicate —— 复制模板（生成新模板） */
  async duplicatePromptTemplate(id: string, payload: PromptTemplateDuplicate): Promise<PromptTemplate> {
    const { data } = await client.post<Record<string, unknown>>(`/prompt-templates/${id}/duplicate`, {
      new_name: payload.newName,
      scope: payload.scope,
      ...(payload.projectId ? { project_id: payload.projectId } : {}),
    })
    return toPromptTemplate(data)
  },
}
