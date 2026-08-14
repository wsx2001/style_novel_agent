import client, { getErrorMessage } from './client'
import type { Project, ProjectCreate, ProjectUpdate } from '@/types'

/**
 * 项目相关 API（对应 TECH.md §5.1）。
 * 后续每个域（文档/知识卡/章节/生成/设置）建一个同构模块。
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
}

export { client, getErrorMessage }
export type { ApiErrorBody } from './client'
