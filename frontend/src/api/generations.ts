import client from './client'
import { streamSSE, type SSEEvent } from '@/lib/sse'
import type { DepthLevel, GenerationRecord, GenerationType, ModelConfig } from '@/types'

/** 后端 model_config 的 wire 形态（snake_case 键：max_tokens） */
export interface ModelConfigWire {
  depth: DepthLevel
  temperature?: number
  max_tokens?: number
  use_1m_context?: boolean
}

/** 续写请求体（wire 形态，POST /chapters/{id}/generate/continue） */
export interface ContinuePayload {
  prompt?: string
  card_ids: string[]
  target_words: number
  temperature: number
  view?: string
  candidate_count?: number
  /** V1：模型配置（docs/TECHv1.md §5.5） */
  model_config?: ModelConfigWire
  /** V1：系统提示词模板 ID */
  system_prompt_template_id?: string
  /** V1.1：本次生成临时指定的提供商与模型（优先级最高，docs/TECHv1.1.md §5.4） */
  provider_id?: string
  model_id?: string
}

/** 重写请求体（wire 形态，POST /chapters/{id}/generate/rewrite） */
export interface RewritePayload {
  selected_text: string
  instruction?: string
  card_ids: string[]
  style_card_id?: string
  target_words: number
  temperature: number
  candidate_count?: number
  /** V1：模型配置 */
  model_config?: ModelConfigWire
  /** V1：系统提示词模板 ID */
  system_prompt_template_id?: string
  /** V1.1：本次生成临时指定的提供商与模型（优先级最高，docs/TECHv1.1.md §5.4） */
  provider_id?: string
  model_id?: string
}

/** 续写参数（前端 camelCase 形态，供 continueGeneration 使用） */
export interface ContinueParams {
  prompt?: string
  cardIds: string[]
  targetWords: number
  temperature: number
  view?: string
  candidateCount?: number
  modelConfig?: Partial<ModelConfig>
  systemPromptTemplateId?: string
  /** V1.1：本次生成临时指定的提供商与模型（不传则回退会话/项目/全局默认） */
  providerId?: string
  modelId?: string
}

/** 重写参数（前端 camelCase 形态，供 rewriteGeneration 使用） */
export interface RewriteParams {
  selectedText: string
  instruction?: string
  cardIds: string[]
  styleCardId?: string
  targetWords: number
  temperature: number
  candidateCount?: number
  modelConfig?: Partial<ModelConfig>
  systemPromptTemplateId?: string
  /** V1.1：本次生成临时指定的提供商与模型（不传则回退会话/项目/全局默认） */
  providerId?: string
  modelId?: string
}

/** 灵感响应体（POST /projects/{id}/generate/inspire） */
export interface InspireResult {
  id: string
  content: string
}

/** 灵感生成参数（前端 camelCase 形态） */
export interface InspireParams {
  idea: string
  temperature?: number
  /** V1.1：本次生成临时指定的提供商与模型（不传则回退项目/全局默认，docs/TECHv1.1.md §5.4） */
  providerId?: string
  modelId?: string
}

/** 前端 ModelConfig → 后端 wire model_config（snake_case 键） */
export function toModelConfigWire(config: Partial<ModelConfig>): ModelConfigWire {
  return {
    depth: config.depth ?? 'auto',
    ...(config.temperature != null ? { temperature: config.temperature } : {}),
    ...(config.maxTokens != null ? { max_tokens: config.maxTokens } : {}),
    ...(config.use1mContext != null ? { use_1m_context: config.use1mContext } : {}),
  }
}

function buildContinuePayload(params: ContinueParams): ContinuePayload {
  return {
    prompt: params.prompt,
    card_ids: params.cardIds,
    target_words: params.targetWords,
    temperature: params.temperature,
    view: params.view,
    candidate_count: params.candidateCount ?? 3,
    ...(params.modelConfig ? { model_config: toModelConfigWire(params.modelConfig) } : {}),
    ...(params.systemPromptTemplateId ? { system_prompt_template_id: params.systemPromptTemplateId } : {}),
    ...(params.providerId ? { provider_id: params.providerId } : {}),
    ...(params.modelId ? { model_id: params.modelId } : {}),
  }
}

function buildRewritePayload(params: RewriteParams): RewritePayload {
  return {
    selected_text: params.selectedText,
    instruction: params.instruction,
    card_ids: params.cardIds,
    style_card_id: params.styleCardId,
    target_words: params.targetWords,
    temperature: params.temperature,
    candidate_count: params.candidateCount ?? 3,
    ...(params.modelConfig ? { model_config: toModelConfigWire(params.modelConfig) } : {}),
    ...(params.systemPromptTemplateId ? { system_prompt_template_id: params.systemPromptTemplateId } : {}),
    ...(params.providerId ? { provider_id: params.providerId } : {}),
    ...(params.modelId ? { model_id: params.modelId } : {}),
  }
}

/**
 * AI 生成相关 API（对应 TECH.md §5.5；V1 支持 model_config / system_prompt_template_id，
 * docs/TECHv1.md §5.5）。续写/重写为 SSE 流式，由 lib/sse.ts 消费。
 */
export const generationUrls = {
  continue: (chapterId: string) => `/api/v1/chapters/${chapterId}/generate/continue`,
  rewrite: (chapterId: string) => `/api/v1/chapters/${chapterId}/generate/rewrite`,
}

/** 续写（SSE 流式）：POST /chapters/{id}/generate/continue，逐帧回调 onEvent */
export async function continueGeneration(
  chapterId: string,
  params: ContinueParams,
  onEvent: (ev: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await streamSSE(generationUrls.continue(chapterId), buildContinuePayload(params), onEvent, signal)
}

/** 重写（SSE 流式）：POST /chapters/{id}/generate/rewrite，逐帧回调 onEvent */
export async function rewriteGeneration(
  chapterId: string,
  params: RewriteParams,
  onEvent: (ev: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await streamSSE(generationUrls.rewrite(chapterId), buildRewritePayload(params), onEvent, signal)
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

  /** POST /projects/{project_id}/generate/inspire —— 灵感生成（同步，V1.1 支持临时指定提供商/模型） */
  async inspire(projectId: string, params: InspireParams): Promise<InspireResult> {
    const { data } = await client.post<InspireResult>(`/projects/${projectId}/generate/inspire`, {
      idea: params.idea,
      ...(params.temperature != null ? { temperature: params.temperature } : {}),
      ...(params.providerId ? { provider_id: params.providerId } : {}),
      ...(params.modelId ? { model_id: params.modelId } : {}),
    })
    return data
  },
}
