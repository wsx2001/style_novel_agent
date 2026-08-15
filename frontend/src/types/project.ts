import type { Timestamped } from './common'

/** 项目（对应后端 Project 模型 / ProjectRead schema） */
export interface Project extends Timestamped {
  id: string
  title: string
  description: string | null
  genre: string | null
  cover_path: string | null
  /** V1：项目默认模型配置（snake_case 键，含 depth / temperature / max_tokens，docs/TECHv1.md §4.2） */
  default_model_config: Record<string, unknown>
  /** V1：项目默认提示词模板 ID（null 时生成回退全局默认） */
  default_prompt_template_id: string | null
}

/** 新建项目请求体 */
export interface ProjectCreate {
  title: string
  description?: string
  genre?: string
}

/** 更新项目请求体（仅显式传入的字段生效） */
export interface ProjectUpdate {
  title?: string
  description?: string
  genre?: string
  /** 项目默认模型配置（snake_case 键）；显式传入时整体替换 */
  default_model_config?: Record<string, unknown>
  /** 项目默认提示词模板 ID；显式传 null 表示清空（回退全局默认） */
  default_prompt_template_id?: string | null
}
