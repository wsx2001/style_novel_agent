import type { Timestamped, DocumentStatus, ParseThreshold, CardType } from './common'

/** 已导入文档（对应后端 Document 模型） */
export interface Document extends Timestamped {
  id: string
  project_id: string
  filename: string
  file_type: 'txt' | 'md' | 'docx'
  file_size: number
  content_text: string
  status: DocumentStatus
  parse_threshold: ParseThreshold
  require_manual_confirm: boolean
  imported_at: string
}

/** 触发文档解析的请求体 */
export interface DocumentParseRequest {
  threshold?: ParseThreshold
  manual_confirm?: boolean
}

/** 解析产出的候选知识卡（确认导入前） */
export interface CandidateCard {
  card_type: CardType
  title: string
  content_json: Record<string, unknown>
  snippet_ids?: string[]
}

/** 确认导入知识库的请求体 */
export interface ConfirmImportRequest {
  cards: CandidateCard[]
}
