import client from './client'
import type { Document, CandidateCard, ConfirmImportRequest, KnowledgeCard } from '@/types'

/** 文档分块预览（POST /documents/{id}/confirm-import 前的片段） */
export interface SnippetChunk {
  id: string
  text: string
  tags: string[]
  start: number
  end: number
}

/** 确认导入的响应体 */
export interface ConfirmImportResult {
  cards: KnowledgeCard[]
  snippet_count: number
}

/**
 * 文档相关 API（对应 TECH.md §5.2）。
 */
export const documentsApi = {
  /** POST /projects/{project_id}/documents —— multipart 上传 */
  async upload(
    projectId: string,
    file: File,
    parseThreshold: string = 'medium',
    requireManualConfirm = true,
  ): Promise<Document> {
    const form = new FormData()
    form.append('file', file)
    form.append('parse_threshold', parseThreshold)
    form.append('require_manual_confirm', String(requireManualConfirm))
    const { data } = await client.post<Document>(
      `/projects/${projectId}/documents`,
      form,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    )
    return data
  },

  /** GET /projects/{project_id}/documents —— 文档列表（?status= 过滤） */
  async list(projectId: string, status?: string): Promise<Document[]> {
    const { data } = await client.get<Document[]>(`/projects/${projectId}/documents`, {
      params: status ? { status } : undefined,
    })
    return data
  },

  /** POST /documents/{document_id}/parse —— 触发 LLM 抽取候选卡片 */
  async parse(documentId: string, payload?: { threshold?: string; manual_confirm?: boolean }): Promise<CandidateCard[]> {
    const { data } = await client.post<CandidateCard[]>(`/documents/${documentId}/parse`, payload ?? {})
    return data
  },

  /** GET /documents/{document_id}/chunks —— 分块预览 */
  async chunks(documentId: string): Promise<SnippetChunk[]> {
    const { data } = await client.get<SnippetChunk[]>(`/documents/${documentId}/chunks`)
    return data
  },

  /** POST /documents/{document_id}/confirm-import —— 确认导入知识库 */
  async confirmImport(documentId: string, payload: ConfirmImportRequest): Promise<ConfirmImportResult> {
    const { data } = await client.post<ConfirmImportResult>(`/documents/${documentId}/confirm-import`, payload)
    return data
  },
}
