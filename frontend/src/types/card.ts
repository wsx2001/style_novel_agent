import type { Timestamped, CardType } from './common'

/** 知识卡（对应后端 KnowledgeCard 模型） */
export interface KnowledgeCard extends Timestamped {
  id: string
  project_id: string
  card_type: CardType
  title: string
  /** 结构化字段，内容随 card_type 变化 */
  content_json: Record<string, unknown>
  tags: string[]
  source_doc_ids: string[]
}

/** 手动新建知识卡请求体 */
export interface KnowledgeCardCreate {
  card_type: CardType
  title: string
  content_json: Record<string, unknown>
  tags?: string[]
}

/** 更新知识卡请求体 */
export interface KnowledgeCardUpdate {
  title?: string
  content_json?: Record<string, unknown>
  tags?: string[]
}

/** 原文片段（对应后端 KnowledgeSnippet 模型），用于知识卡溯源 */
export interface KnowledgeSnippet extends Timestamped {
  id: string
  project_id: string
  document_id: string
  card_id: string | null
  text: string
  tags: string[]
  start_offset: number | null
  end_offset: number | null
}
