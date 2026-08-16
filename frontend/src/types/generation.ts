import type { Timestamped, GenerationType, GenerationStatus } from './common'

/** AI 生成记录（对应后端 GenerationRecord 模型） */
export interface GenerationRecord extends Timestamped {
  id: string
  project_id: string
  chapter_id: string | null
  generation_type: GenerationType
  status: GenerationStatus
  input_text: string | null
  params_json: Record<string, unknown>
  /** 候选文本列表（一次生成 2-3 个候选） */
  output_candidates: string[]
  selected_output: string | null
  /** V1.1：本次生成实际使用的提供商与模型（docs/TECHv1.1.md §4.5） */
  provider_id: string | null
  model_id: string | null
}

/** 生成参数（续写 / 重写 / 灵感 / 大纲 通用字段） */
export interface GenerationParams {
  /** 显式选中的知识卡 id */
  card_ids?: string[]
  target_words?: number
  temperature?: number
  /** 叙事视角 */
  view?: string
  /** 续写：自定义提示 */
  prompt?: string
  /** 重写：选中的原文 */
  selected_text?: string
  /** 重写：风格指令 */
  instruction?: string
  /** 重写：文风卡 id */
  style_card_id?: string
  /** 灵感：灵感描述 */
  idea?: string
}
