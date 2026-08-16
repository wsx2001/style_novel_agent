import type { Timestamped, ApiProvider } from './common'

/** API Key 配置（对应后端 ApiKeyConfig 模型）。
 * 注意：GET 列表接口返回的是脱敏后的 key（如 sk-***1234），不会暴露明文。 */
export interface ApiKeyConfig extends Timestamped {
  id: string
  project_id: string | null
  provider: ApiProvider
  name: string
  key_masked: string
  base_url: string
  model: string | null
  is_default: boolean
}

/** 保存 API Key 请求体（api_key 为明文，后端加密存储） */
export interface ApiKeySave {
  provider: ApiProvider
  name: string
  api_key: string
  base_url: string
  model?: string
  is_default?: boolean
}

/** 项目级设置（对应后端 ProjectSettings 模型） */
export interface ProjectSettings extends Timestamped {
  id: string
  project_id: string
  auto_parse_confirm: boolean
  default_temperature: number
  default_max_tokens: number
  default_view: string | null
}

/** 全局应用配置项（对应后端 AppConfig 模型，key-value 存储） */
export interface AppConfig extends Timestamped {
  id: string
  key: string
  value: Record<string, unknown>
}

/** 思维深度映射配置（对应后端 AppConfig depth_mapping_config，docs/TECHv1.md §8.1）。
 * modelOverrides 为前端 camelCase 形态，与后端 model_overrides 的映射在 api/settings.ts 完成。 */
export interface DepthMapping {
  default: Record<string, unknown>
  modelOverrides?: Record<string, unknown>
}

/** 全局应用设置（GET/PATCH /settings/app，对应 AppConfig global_default_* 键） */
export interface GlobalAppSettings {
  /** 全局默认模型配置（新项目创建时复制为项目默认） */
  global_default_model_config: Record<string, unknown>
  /** 全局默认提示词模板 ID（空串表示未设置） */
  global_default_prompt_template_id: string
  /** V1.1：全局默认提供商 ID（空串表示未设置，docs/TECHv1.1.md §4.6） */
  global_default_provider_id: string
  /** V1.1：全局默认模型 ID（空串表示未设置） */
  global_default_model_id: string
}

/** 更新全局设置请求体（所有字段可选，仅显式传入的字段生效） */
export interface GlobalAppSettingsUpdate {
  global_default_model_config?: Record<string, unknown>
  global_default_prompt_template_id?: string
  /** V1.1：全局默认提供商 ID（传空串表示清除） */
  global_default_provider_id?: string
  /** V1.1：全局默认模型 ID（传空串表示清除） */
  global_default_model_id?: string
}
