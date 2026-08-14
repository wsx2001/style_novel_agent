import client from './client'
import type { Chapter, ChapterCreate, ChapterUpdate, ChapterVersion } from '@/types'

/** 手动创建版本快照请求体 */
export interface ChapterVersionCreate {
  content: string
  note?: string
}

/**
 * 章节相关 API（对应 TECH.md §5.4）。
 */
export const chaptersApi = {
  /** GET /projects/{project_id}/chapters —— 章节列表（按 order 排序） */
  async list(projectId: string): Promise<Chapter[]> {
    const { data } = await client.get<Chapter[]>(`/projects/${projectId}/chapters`)
    return data
  },

  /** POST /projects/{project_id}/chapters —— 新建章节 */
  async create(projectId: string, payload: ChapterCreate): Promise<Chapter> {
    const { data } = await client.post<Chapter>(`/projects/${projectId}/chapters`, payload)
    return data
  },

  /** GET /chapters/{chapter_id} —— 章节详情 */
  async get(chapterId: string): Promise<Chapter> {
    const { data } = await client.get<Chapter>(`/chapters/${chapterId}`)
    return data
  },

  /** PATCH /chapters/{chapter_id} —— 保存（title/content，后端自动算字数并生成自动快照） */
  async update(chapterId: string, payload: ChapterUpdate): Promise<Chapter> {
    const { data } = await client.patch<Chapter>(`/chapters/${chapterId}`, payload)
    return data
  },

  /** DELETE /chapters/{chapter_id} —— 删除 */
  async remove(chapterId: string): Promise<void> {
    await client.delete(`/chapters/${chapterId}`)
  },

  /** GET /chapters/{chapter_id}/versions —— 版本快照列表 */
  async versions(chapterId: string): Promise<ChapterVersion[]> {
    const { data } = await client.get<ChapterVersion[]>(`/chapters/${chapterId}/versions`)
    return data
  },

  /** POST /chapters/{chapter_id}/versions —— 手动创建版本快照 */
  async createVersion(chapterId: string, payload: ChapterVersionCreate): Promise<ChapterVersion> {
    const { data } = await client.post<ChapterVersion>(`/chapters/${chapterId}/versions`, payload)
    return data
  },

  /** POST /chapters/{chapter_id}/versions/{version_id}/rollback —— 回滚到指定版本 */
  async rollback(chapterId: string, versionId: string): Promise<Chapter> {
    const { data } = await client.post<Chapter>(`/chapters/${chapterId}/versions/${versionId}/rollback`)
    return data
  },
}
