import client from './client'
import type { Project, ProjectCreate, ProjectUpdate } from '@/types'

/** 导出文件格式（GET /projects/{id}/export?format=） */
export type ExportFormat = 'txt' | 'markdown' | 'json' | 'docx'

/**
 * 项目相关 API（对应 TECH.md §5.1；V1.1 支持项目默认提供商/模型字段，
 * docs/TECHv1.1.md §5.2）。请求体与响应体均为后端 snake_case JSON 直传。
 */
export const projectsApi = {
  /** GET /projects —— 项目列表 */
  async list(): Promise<Project[]> {
    const { data } = await client.get<Project[]>('/projects')
    return data
  },

  /** POST /projects —— 新建项目（可选 default_provider_id / default_model_id） */
  async create(payload: ProjectCreate): Promise<Project> {
    const { data } = await client.post<Project>('/projects', payload)
    return data
  },

  /** GET /projects/{project_id} —— 项目详情 */
  async get(projectId: string): Promise<Project> {
    const { data } = await client.get<Project>(`/projects/${projectId}`)
    return data
  },

  /** PATCH /projects/{project_id} —— 更新项目（default_provider_id / default_model_id 传 null 继承全局默认） */
  async update(projectId: string, payload: ProjectUpdate): Promise<Project> {
    const { data } = await client.patch<Project>(`/projects/${projectId}`, payload)
    return data
  },

  /** DELETE /projects/{project_id} —— 删除项目 */
  async remove(projectId: string): Promise<void> {
    await client.delete(`/projects/${projectId}`)
  },

  /** GET /projects/{project_id}/export?format= —— 导出项目并触发浏览器下载 */
  async exportFile(projectId: string, format: ExportFormat): Promise<void> {
    const { data, headers } = await client.get(`/projects/${projectId}/export`, {
      params: { format },
      responseType: 'blob',
    })
    const disposition = headers['content-disposition'] ?? ''
    const match = /filename="?([^";]+)"?/.exec(disposition)
    const filename = match?.[1] ?? `export.${format}`
    const url = URL.createObjectURL(data as Blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
    URL.revokeObjectURL(url)
  },
}
