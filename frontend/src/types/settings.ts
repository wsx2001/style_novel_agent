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
