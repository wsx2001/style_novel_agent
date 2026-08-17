import client from './client'
import { streamSSE, type SSEEvent } from '@/lib/sse'
import type {
  CandidateCard,
  ConfirmImportRequest,
  Document,
  KnowledgeCard,
  ParseResult,
  ParseThreshold,
} from '@/types'

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

/** 解析进度帧（event: progress 的 data） */
export interface ParseProgressFrame {
  index: number
  total: number
  label: string
  status: 'start' | 'done' | 'error' | 'skipped'
  /** 简略结果（status=done）：类别 → 数量 */
  result?: Record<string, number>
}

/** 流式解析回调 */
export interface ParseHandlers {
  onProgress: (frame: ParseProgressFrame) => void
  onDone: (candidates: CandidateCard[]) => void
  onError: (message: string) => void
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

  /** POST /documents/{document_id}/parse —— 触发 LLM 抽取候选卡片（SSE 流式，含分块进度）。
   * 事件：progress（进度帧）/ done（candidates）/ error（message）。 */
  async parseStream(
    documentId: string,
    payload: { threshold?: string; manual_confirm?: boolean } | undefined,
    handlers: ParseHandlers,
  ): Promise<void> {
    let error: string | null = null
    await streamSSE(
      `/api/v1/documents/${documentId}/parse`,
      payload ?? {},
      (ev: SSEEvent) => {
        if (ev.event === 'progress') {
          handlers.onProgress(JSON.parse(ev.data) as ParseProgressFrame)
        } else if (ev.event === 'done') {
          const { candidates } = JSON.parse(ev.data) as { candidates: CandidateCard[] }
          handlers.onDone(candidates)
        } else if (ev.event === 'error') {
          const { message } = JSON.parse(ev.data) as { message: string }
          error = message
        }
      },
    )
    if (error) handlers.onError(error)
  },

  /** GET /documents/{document_id}/chunks —— 分块预览 */
  async chunks(documentId: string): Promise<SnippetChunk[]> {
    const { data } = await client.get<SnippetChunk[]>(`/documents/${documentId}/chunks`)
    return data
  },

  /** GET /documents/{document_id}/parse-result —— 查询已解析结果（刷新后恢复候选卡片继续导入） */
  async parseResult(documentId: string): Promise<ParseResult> {
    const { data } = await client.get<Record<string, unknown>>(`/documents/${documentId}/parse-result`)
    return {
      candidates: Array.isArray(data.candidates) ? (data.candidates as CandidateCard[]) : [],
      threshold: (data.threshold as ParseThreshold) ?? 'medium',
      manual_confirm: data.manual_confirm !== false,
      extracted_at: (data.extracted_at as string | null) ?? null,
    }
  },

  /** POST /documents/{document_id}/confirm-import —— 确认导入知识库 */
  async confirmImport(documentId: string, payload: ConfirmImportRequest): Promise<ConfirmImportResult> {
    const { data } = await client.post<ConfirmImportResult>(`/documents/${documentId}/confirm-import`, payload)
    return data
  },
}
