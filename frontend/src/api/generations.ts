import client from './client'
import type { GenerationRecord, GenerationType } from '@/types'

/** 续写请求体（POST /chapters/{id}/generate/continue） */
export interface ContinuePayload {
  prompt?: string
  card_ids: string[]
  target_words: number
  temperature: number
  view?: string
  candidate_count?: number
}

/** 重写请求体（POST /chapters/{id}/generate/rewrite） */
export interface RewritePayload {
  selected_text: string
  instruction?: string
  card_ids: string[]
  style_card_id?: string
  target_words: number
  temperature: number
  candidate_count?: number
}

/** 灵感响应体（POST /projects/{id}/generate/inspire） */
export interface InspireResult {
  id: string
  content: string
}

/**
 * AI 生成相关 API（对应 TECH.md §5.5）。
 * 续写/重写为 SSE 流式，由 lib/sse.ts 配合 generationUrls 消费；
 * 这里仅提供记录列表与灵感（同步）。
 */
export const generationUrls = {
  continue: (chapterId: string) => `/api/v1/chapters/${chapterId}/generate/continue`,
  rewrite: (chapterId: string) => `/api/v1/chapters/${chapterId}/generate/rewrite`,
}

export const generationsApi = {
  /** GET /projects/{project_id}/generations —— 生成记录（?type=&chapter_id=&q=） */
  async list(
    projectId: string,
    params?: { type?: GenerationType; chapter_id?: string; q?: string },
  ): Promise<GenerationRecord[]> {
    const { data } = await client.get<GenerationRecord[]>(`/projects/${projectId}/generations`, { params })
    return data
  },

  /** POST /projects/{project_id}/generate/inspire —— 灵感生成（同步） */
  async inspire(projectId: string, idea: string, temperature = 0.9): Promise<InspireResult> {
    const { data } = await client.post<InspireResult>(`/projects/${projectId}/generate/inspire`, {
      idea,
      temperature,
    })
    return data
  },
}
