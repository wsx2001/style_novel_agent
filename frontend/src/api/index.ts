import client, { getErrorMessage } from './client'
import type { Project, ProjectCreate, ProjectUpdate } from '@/types'

/** 导出文件格式（GET /projects/{id}/export?format=） */
export type ExportFormat = 'txt' | 'markdown' | 'json' | 'docx'

/**
 * 项目相关 API（对应 TECH.md §5.1）。
 */
export const projectsApi = {
  /** GET /projects —— 项目列表 */
  async list(): Promise<Project[]> {
    const { data } = await client.get<Project[]>('/projects')
    return data
  },

  /** POST /projects —— 新建项目 */
  async create(payload: ProjectCreate): Promise<Project> {
    const { data } = await client.post<Project>('/projects', payload)
    return data
  },

  /** GET /projects/{project_id} —— 项目详情 */
  async get(projectId: string): Promise<Project> {
    const { data } = await client.get<Project>(`/projects/${projectId}`)
    return data
  },

  /** PATCH /projects/{project_id} —— 更新项目 */
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

export { client, getErrorMessage }
export type { ApiErrorBody } from './client'
export { documentsApi } from './documents'
export type { SnippetChunk, ConfirmImportResult } from './documents'
export { cardsApi } from './cards'
export { chaptersApi } from './chapters'
export type { ChapterVersionCreate } from './chapters'
export { generationsApi, generationUrls } from './generations'
export type { ContinuePayload, RewritePayload, InspireResult } from './generations'
export { settingsApi } from './settings'
