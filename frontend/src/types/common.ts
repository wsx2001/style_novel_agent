/**
 * 通用基础类型 —— 与后端 Pydantic schema 一一对应。
 * 时间戳字段后端输出为 ISO 8601 字符串。
 */

/** 所有带时间戳实体的公共字段 */
export interface Timestamped {
  created_at: string
  updated_at: string
}

/** 知识卡类型 */
export type CardType = 'character' | 'world' | 'term' | 'style' | 'event'

/** 文档解析准确率阈值 */
export type ParseThreshold = 'low' | 'medium' | 'high'

/** 文档状态：pending 待解析 | parsing 解析中 | parsed 已解析 | imported 已导入 | failed 失败 */
export type DocumentStatus = 'pending' | 'parsing' | 'parsed' | 'imported' | 'failed'

/** 章节状态 */
export type ChapterStatus = 'draft' | 'writing' | 'completed'

/** 生成类型：continue 续写 | rewrite 重写 | inspire 灵感 | outline 大纲 */
export type GenerationType = 'continue' | 'rewrite' | 'inspire' | 'outline'

/** 生成状态 */
export type GenerationStatus = 'pending' | 'streaming' | 'completed' | 'failed'

/** 思维深度等级（docs/TECHv1.md §8.1：无/自动/低/中/高/极高） */
export type DepthLevel = 'none' | 'auto' | 'low' | 'medium' | 'high' | 'extreme'

/** 模型配置（V1：思维深度必填，temperature / maxTokens 可选） */
export interface ModelConfig {
  depth: DepthLevel
  temperature?: number
  maxTokens?: number
}

/** API 提供商 */
export type ApiProvider = 'openai' | 'deepseek' | 'kimi' | 'moonshot' | 'custom'

/** 通用分页响应（后端如返回分页列表时使用） */
export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}
