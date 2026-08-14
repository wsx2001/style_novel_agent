import client from './client'
import type { Chapter, ChapterCreate, ChapterUpdate } from '@/types'

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

  /** PATCH /chapters/{chapter_id} —— 保存（title/content，后端自动算字数） */
  async update(chapterId: string, payload: ChapterUpdate): Promise<Chapter> {
    const { data } = await client.patch<Chapter>(`/chapters/${chapterId}`, payload)
    return data
  },

  /** DELETE /chapters/{chapter_id} —— 删除 */
  async remove(chapterId: string): Promise<void> {
    await client.delete(`/chapters/${chapterId}`)
  },
}
