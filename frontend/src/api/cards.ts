import client from './client'
import type { CardType, KnowledgeCard, KnowledgeCardCreate, KnowledgeCardUpdate } from '@/types'

/**
 * 知识卡相关 API（对应 TECH.md §5.3）。
 */
export const cardsApi = {
  /** GET /projects/{project_id}/cards —— 卡片列表（?card_type= &q= 过滤） */
  async list(projectId: string, params?: { card_type?: CardType; q?: string }): Promise<KnowledgeCard[]> {
    const { data } = await client.get<KnowledgeCard[]>(`/projects/${projectId}/cards`, { params })
    return data
  },

  /** POST /projects/{project_id}/cards —— 手动新建 */
  async create(projectId: string, payload: KnowledgeCardCreate): Promise<KnowledgeCard> {
    const { data } = await client.post<KnowledgeCard>(`/projects/${projectId}/cards`, payload)
    return data
  },

  /** GET /cards/{card_id} —— 卡片详情 */
  async get(cardId: string): Promise<KnowledgeCard> {
    const { data } = await client.get<KnowledgeCard>(`/cards/${cardId}`)
    return data
  },

  /** PATCH /cards/{card_id} —— 更新 */
  async update(cardId: string, payload: KnowledgeCardUpdate): Promise<KnowledgeCard> {
    const { data } = await client.patch<KnowledgeCard>(`/cards/${cardId}`, payload)
    return data
  },

  /** DELETE /cards/{card_id} —— 删除 */
  async remove(cardId: string): Promise<void> {
    await client.delete(`/cards/${cardId}`)
  },
}
