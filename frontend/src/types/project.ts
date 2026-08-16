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
  /** V1.1：项目默认提供商与模型（null 表示继承全局默认，docs/TECHv1.1.md §4.3） */
  default_provider_id: string | null
  default_model_id: string | null
}

/** 新建项目请求体 */
export interface ProjectCreate {
  title: string
  description?: string
  genre?: string
  /** V1.1：可选指定项目默认提供商与模型（未传继承全局默认；显式传 null 表示不继承） */
  default_provider_id?: string | null
  default_model_id?: string | null
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
  /** V1.1：项目默认提供商与模型（显式传 null 表示继承全局默认，docs/TECHv1.1.md §5.2） */
  default_provider_id?: string | null
  default_model_id?: string | null
}
