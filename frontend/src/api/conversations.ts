import client from './client'
import { streamSSE, type SSEEvent } from '@/lib/sse'
import { toModelConfigWire } from './generations'
import type {
  Conversation,
  ConversationCreate,
  ConversationDetail,
  ConversationUpdate,
  Message,
  MessageRole,
  ModelConfig,
  SendMessageOptions,
} from '@/types'

/**
 * 对话相关 API（docs/TECHv1.md §5.6）。
 * 后端响应为 snake_case JSON，此处映射为前端 camelCase 类型（见 types/conversation.ts）。
 */

function toModelConfig(raw: Record<string, unknown> | null | undefined): ModelConfig {
  return {
    depth: (raw?.depth as ModelConfig['depth']) ?? 'auto',
    ...(raw?.temperature != null ? { temperature: raw.temperature as number } : {}),
    ...(raw?.max_tokens != null ? { maxTokens: raw.max_tokens as number } : {}),
  }
}

function toConversation(raw: Record<string, unknown>): Conversation {
  return {
    id: raw.id as string,
    projectId: raw.project_id as string,
    chapterId: (raw.chapter_id as string) ?? null,
    title: raw.title as string,
    modelConfig: toModelConfig(raw.model_config as Record<string, unknown> | null),
    systemPromptTemplateId: (raw.system_prompt_template_id as string) ?? null,
    systemPromptOverride: (raw.system_prompt_override as string) ?? null,
    currentProviderId: (raw.current_provider_id as string) ?? null,
    currentModelId: (raw.current_model_id as string) ?? null,
    createdAt: raw.created_at as string,
    updatedAt: raw.updated_at as string,
  }
}

function toMessage(raw: Record<string, unknown>): Message {
  return {
    id: raw.id as string,
    conversationId: raw.conversation_id as string,
    role: raw.role as MessageRole,
    content: raw.content as string,
    metadata: (raw.metadata as Record<string, unknown>) ?? {},
    createdAt: raw.created_at as string,
  }
}

function toConversationDetail(raw: Record<string, unknown>): ConversationDetail {
  const messages = Array.isArray(raw.messages) ? raw.messages.map(toMessage) : []
  return { ...toConversation(raw), messages }
}

/** 前端 camelCase 创建参数 → 后端 snake_case 请求体 */
function buildCreateBody(payload: ConversationCreate): Record<string, unknown> {
  const body: Record<string, unknown> = {}
  if (payload.title != null) body.title = payload.title
  if (payload.chapterId != null) body.chapter_id = payload.chapterId
  if (payload.modelConfig) body.model_config = toModelConfigWire(payload.modelConfig)
  if (payload.systemPromptTemplateId != null) {
    body.system_prompt_template_id = payload.systemPromptTemplateId
  }
  if (payload.currentProviderId != null) body.current_provider_id = payload.currentProviderId
  if (payload.currentModelId != null) body.current_model_id = payload.currentModelId
  return body
}

/** 前端 camelCase 更新参数 → 后端 snake_case 请求体（仅显式传入的字段，null 用于清空） */
function buildUpdateBody(payload: ConversationUpdate): Record<string, unknown> {
  const body: Record<string, unknown> = {}
  if (payload.title !== undefined) body.title = payload.title
  if (payload.modelConfig) body.model_config = toModelConfigWire(payload.modelConfig)
  if (payload.systemPromptTemplateId !== undefined) {
    body.system_prompt_template_id = payload.systemPromptTemplateId
  }
  if (payload.systemPromptOverride !== undefined) body.system_prompt_override = payload.systemPromptOverride
  if (payload.currentProviderId !== undefined) body.current_provider_id = payload.currentProviderId
  if (payload.currentModelId !== undefined) body.current_model_id = payload.currentModelId
  return body
}

/** SSE 发送消息回调 */
export interface SendMessageHandlers {
  /** 增量正文 */
  onDelta: (text: string) => void
  /** 流结束（携带 assistant 消息 id） */
  onDone: (messageId: string) => void
}

export const conversationsApi = {
  /** GET /projects/{project_id}/conversations —— 项目下所有对话 */
  async listConversations(projectId: string): Promise<Conversation[]> {
    const { data } = await client.get<Record<string, unknown>[]>(`/projects/${projectId}/conversations`)
    return data.map(toConversation)
  },

  /** POST /projects/{project_id}/conversations —— 创建对话 */
  async createConversation(projectId: string, payload: ConversationCreate): Promise<Conversation> {
    const { data } = await client.post<Record<string, unknown>>(
      `/projects/${projectId}/conversations`,
      buildCreateBody(payload),
    )
    return toConversation(data)
  },

  /** GET /conversations/{id} —— 对话详情（含消息列表） */
  async getConversation(id: string): Promise<ConversationDetail> {
    const { data } = await client.get<Record<string, unknown>>(`/conversations/${id}`)
    return toConversationDetail(data)
  },

  /** PATCH /conversations/{id} —— 更新对话（标题/模型配置/模板/临时覆盖） */
  async updateConversation(id: string, payload: ConversationUpdate): Promise<Conversation> {
    const { data } = await client.patch<Record<string, unknown>>(
      `/conversations/${id}`,
      buildUpdateBody(payload),
    )
    return toConversation(data)
  },

  /** DELETE /conversations/{id} —— 删除对话 */
  async deleteConversation(id: string): Promise<void> {
    await client.delete(`/conversations/${id}`)
  },

  /** GET /conversations/{id}/messages —— 消息历史（时间正序） */
  async getMessages(conversationId: string): Promise<Message[]> {
    const { data } = await client.get<Record<string, unknown>[]>(`/conversations/${conversationId}/messages`)
    return data.map(toMessage)
  },

  /**
   * POST /conversations/{id}/messages —— 发送消息（SSE 流式，单回复）。
   * 事件：delta（增量正文）/ done（message_id）/ error（message）。
   * V1.1：options.providerId / options.modelId 用于临时指定本次生成使用的模型（优先级最高，
   * 若与会话当前模型不同，后端自动更新会话并插入「模型已切换」系统消息，docs/TECHv1.1.md §5.3）。
   */
  async sendMessage(
    conversationId: string,
    userInput: string,
    onDelta: (text: string) => void,
    onDone: (messageId: string) => void,
    signal?: AbortSignal,
    options?: SendMessageOptions,
  ): Promise<void> {
    let error: string | null = null
    await streamSSE(
      `/api/v1/conversations/${conversationId}/messages`,
      {
        content: userInput,
        ...(options?.providerId != null ? { provider_id: options.providerId } : {}),
        ...(options?.modelId != null ? { model_id: options.modelId } : {}),
      },
      (ev: SSEEvent) => {
        if (ev.event === 'delta') {
          const { content } = JSON.parse(ev.data) as { content: string }
          onDelta(content)
        } else if (ev.event === 'done') {
          const { message_id } = JSON.parse(ev.data) as { message_id: string }
          onDone(message_id)
        } else if (ev.event === 'error') {
          const { message } = JSON.parse(ev.data) as { message: string }
          error = message
        }
      },
      signal,
    )
    if (error) throw new Error(error)
  },
}
