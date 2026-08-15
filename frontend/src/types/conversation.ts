/**
 * 对话与消息类型（对应后端 Conversation / Message 模型，docs/TECHv1.md §4.4 / §5.6）。
 * 注意：前端采用 camelCase 形态（projectId / modelConfig / createdAt 等），
 * 与后端 snake_case JSON（project_id / model_config / created_at）的映射在 api/conversations.ts 完成。
 */
import type { ModelConfig } from './common'

/** 对话 */
export interface Conversation {
  id: string
  projectId: string
  chapterId: string | null
  title: string
  /** 会话模型配置（思维深度 / 温度 / maxTokens） */
  modelConfig: ModelConfig
  systemPromptTemplateId: string | null
  systemPromptOverride: string | null
  createdAt: string
  updatedAt: string
}

/** 消息角色 */
export type MessageRole = 'user' | 'assistant' | 'system'

/** 消息 */
export interface Message {
  id: string
  conversationId: string
  role: MessageRole
  content: string
  /** 扩展信息（模型、token 用量等） */
  metadata: Record<string, unknown>
  createdAt: string
}

/** 对话详情（含消息列表，GET /conversations/{id}） */
export interface ConversationDetail extends Conversation {
  messages: Message[]
}

/** 创建对话请求体 */
export interface ConversationCreate {
  title?: string
  chapterId?: string
  modelConfig?: Partial<ModelConfig>
  systemPromptTemplateId?: string
}

/** 更新对话请求体（仅显式传入的字段生效） */
export interface ConversationUpdate {
  title?: string
  modelConfig?: Partial<ModelConfig>
  /** 当前会话使用的提示词模板 ID；显式传 null 表示清空（回退项目/全局默认） */
  systemPromptTemplateId?: string | null
  /** 会话级临时覆盖（仅本会话生效）；显式传 null 表示清除覆盖 */
  systemPromptOverride?: string | null
}
