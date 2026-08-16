/**
 * 模型提供商类型（docs/TECHv1.1.md §4.2 / §5.1，对应后端 schemas/model_provider.py）。
 * 前端采用 camelCase 形态，与后端 snake_case JSON（base_url / is_default / api_keys 等）的映射在 api/modelProviders.ts 完成。
 */

/** 提供商类型（docs/TECHv1.1.md §4.2） */
export type ModelProviderType =
  | 'openai'
  | 'anthropic'
  | 'deepseek'
  | 'kimi'
  | 'opencode_go'
  | 'custom'
  | 'other'

/** API Key 读取形态（对应后端 ApiKeyRead；keyMasked 为脱敏值，只含首尾字符，绝不含明文/密文） */
export interface ApiKeyRead {
  keyId: string
  keyMasked: string
  enabled: boolean
  priority: number
  availableModels: string[]
}

/** API Key 提交形态（创建/更新提供商时使用；key 为明文，新增时必填，更新未改动 Key 可回传脱敏占位符） */
export interface ApiKeyInfo {
  /** 已有 Key 回传的 id（新增可省略） */
  keyId?: string
  /** 明文 key（新增必填；更新未改动的 Key 可回传脱敏占位符，服务端复用旧密文） */
  key?: string
  /** 加密后的 key（前端通常不需要，仅保留类型占位） */
  apiKeyEncrypted?: string
  enabled?: boolean
  priority?: number
  availableModels?: string[]
}

/** 模型列表项（modelId + 启用状态，docs/TECHv1.1.md §4.2） */
export interface ModelItem {
  modelId: string
  enabled: boolean
}

/** 提供商派生状态：ready 有启用 Key 可用于生成 | no_keys 无启用 Key */
export type ProviderStatus = 'ready' | 'no_keys'

/** 模型提供商详情（对应后端 ModelProviderRead；apiKeys 已脱敏） */
export interface ModelProvider {
  id: string
  name: string
  type: ModelProviderType
  baseUrl?: string | null
  /** 作用范围（当前固定 global） */
  scope: string
  isDefault: boolean
  apiKeys: ApiKeyRead[]
  models: ModelItem[]
  /** 摘要字段（列表接口 / 派生信息；详情接口通常为空） */
  keyCount?: number
  modelCount?: number
  status?: ProviderStatus
  createdAt: string
  updatedAt: string
}

/** 提供商列表摘要（对应后端 ProviderSummary，不含任何 Key 信息） */
export interface ProviderSummary {
  id: string
  name: string
  type: ModelProviderType
  scope: string
  baseUrl?: string | null
  isDefault: boolean
  keyCount: number
  enabledKeyCount: number
  modelCount: number
  enabledModelCount: number
  status: ProviderStatus
  createdAt: string
  updatedAt: string
}

/** 创建提供商请求体（docs/TECHv1.1.md §5.1） */
export interface ModelProviderCreate {
  name: string
  type: ModelProviderType
  baseUrl?: string | null
  apiKeys?: ApiKeyInfo[]
  /** 创建成功后是否自动获取模型列表（默认 true；失败不阻断创建，models 为空并提示） */
  autoFetch?: boolean
}

/** 更新提供商请求体（所有字段可选；apiKeys / models 为一次全量替换） */
export interface ModelProviderUpdate {
  name?: string
  type?: ModelProviderType
  baseUrl?: string | null
  apiKeys?: ApiKeyInfo[]
  models?: ModelItem[]
}

/** 获取模型列表结果（fetch-models / 创建时自动获取） */
export interface ModelFetchResult {
  success: boolean
  models: string[]
  errors: Array<{ keyId: string; error: string }>
}

/** 单个 Key 连接检测结果 */
export interface KeyDetectResult {
  keyId: string
  valid: boolean
  error?: string | null
  modelCount: number
}

/** 创建提供商响应（provider 详情 + 自动获取模型的结果与提示） */
export interface ModelProviderCreateResponse {
  provider: ModelProvider
  autoFetch?: ModelFetchResult | null
  message?: string | null
}
