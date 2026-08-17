import client from './client'
import type {
  ApiKeyInfo,
  ApiKeyRead,
  KeyDetectResult,
  ModelFetchResult,
  ModelItem,
  ModelProvider,
  ModelProviderCreate,
  ModelProviderCreateResponse,
  ModelProviderType,
  ModelProviderUpdate,
  ProviderStatus,
  ProviderSummary,
} from '@/types'

/**
 * 模型提供商管理 API（docs/TECHv1.1.md §5.1，对应后端 api/v1/model_providers.py）。
 * 后端响应为 snake_case JSON，此处映射为前端 camelCase 类型（见 types/modelProvider.ts）。
 */

function toApiKeyRead(raw: Record<string, unknown>): ApiKeyRead {
  return {
    keyId: raw.key_id as string,
    keyMasked: raw.key_masked as string,
    enabled: raw.enabled as boolean,
    priority: raw.priority as number,
    availableModels: Array.isArray(raw.available_models) ? (raw.available_models as string[]) : [],
  }
}

function toModelItem(raw: Record<string, unknown>): ModelItem {
  return {
    modelId: raw.model_id as string,
    enabled: raw.enabled as boolean,
    supports1mContext: raw.supports_1m_context === true,
  }
}

/** 后端 type 字符串 → 前端联合类型；未知值回退 other 保证类型安全 */
function toProviderType(raw: unknown): ModelProviderType {
  const known: ModelProviderType[] = [
    'openai',
    'anthropic',
    'deepseek',
    'kimi',
    'opencode_go',
    'custom',
    'other',
  ]
  return known.includes(raw as ModelProviderType) ? (raw as ModelProviderType) : 'other'
}

function toStatus(raw: unknown): ProviderStatus {
  return raw === 'ready' ? 'ready' : 'no_keys'
}

function toModelProvider(raw: Record<string, unknown>): ModelProvider {
  return {
    id: raw.id as string,
    name: raw.name as string,
    type: toProviderType(raw.type),
    baseUrl: (raw.base_url as string | null) ?? null,
    scope: (raw.scope as string) ?? 'global',
    isDefault: raw.is_default as boolean,
    apiKeys: Array.isArray(raw.api_keys)
      ? raw.api_keys.map((k) => toApiKeyRead(k as Record<string, unknown>))
      : [],
    models: Array.isArray(raw.models)
      ? raw.models.map((m) => toModelItem(m as Record<string, unknown>))
      : [],
    ...(raw.key_count != null ? { keyCount: raw.key_count as number } : {}),
    ...(raw.model_count != null ? { modelCount: raw.model_count as number } : {}),
    ...(raw.status != null ? { status: toStatus(raw.status) } : {}),
    createdAt: raw.created_at as string,
    updatedAt: raw.updated_at as string,
  }
}

function toProviderSummary(raw: Record<string, unknown>): ProviderSummary {
  return {
    id: raw.id as string,
    name: raw.name as string,
    type: toProviderType(raw.type),
    scope: (raw.scope as string) ?? 'global',
    baseUrl: (raw.base_url as string | null) ?? null,
    isDefault: raw.is_default as boolean,
    keyCount: (raw.key_count as number) ?? 0,
    enabledKeyCount: (raw.enabled_key_count as number) ?? 0,
    modelCount: (raw.model_count as number) ?? 0,
    enabledModelCount: (raw.enabled_model_count as number) ?? 0,
    status: toStatus(raw.status),
    createdAt: raw.created_at as string,
    updatedAt: raw.updated_at as string,
  }
}

function toFetchResult(raw: Record<string, unknown>): ModelFetchResult {
  return {
    success: raw.success as boolean,
    models: Array.isArray(raw.models) ? (raw.models as string[]) : [],
    errors: Array.isArray(raw.errors)
      ? (raw.errors as Array<{ key_id?: string; keyId?: string; error: string }>).map((e) => ({
          keyId: (e.key_id ?? e.keyId) as string,
          error: e.error,
        }))
      : [],
  }
}

function toDetectResult(raw: Record<string, unknown>): KeyDetectResult {
  return {
    keyId: raw.key_id as string,
    valid: raw.valid as boolean,
    error: (raw.error as string | null) ?? null,
    modelCount: (raw.model_count as number) ?? 0,
  }
}

/** ApiKeyInfo（camelCase）→ 后端 ApiKeyInput wire 形态（snake_case） */
function toApiKeyInputWire(key: ApiKeyInfo): Record<string, unknown> {
  const wire: Record<string, unknown> = {}
  if (key.key != null) wire.key = key.key
  if (key.keyId != null) wire.key_id = key.keyId
  if (key.enabled !== undefined) wire.enabled = key.enabled
  if (key.priority !== undefined) wire.priority = key.priority
  return wire
}

/** 前端 camelCase 创建参数 → 后端 snake_case 请求体 */
function buildCreateBody(payload: ModelProviderCreate): Record<string, unknown> {
  const body: Record<string, unknown> = { name: payload.name, type: payload.type }
  if (payload.baseUrl != null) body.base_url = payload.baseUrl
  if (payload.apiKeys) body.api_keys = payload.apiKeys.map(toApiKeyInputWire)
  if (payload.autoFetch !== undefined) body.auto_fetch = payload.autoFetch
  return body
}

/** 前端 camelCase 更新参数 → 后端 snake_case 请求体（仅显式传入的字段） */
function buildUpdateBody(payload: ModelProviderUpdate): Record<string, unknown> {
  const body: Record<string, unknown> = {}
  if (payload.name !== undefined) body.name = payload.name
  if (payload.type !== undefined) body.type = payload.type
  if (payload.baseUrl !== undefined) body.base_url = payload.baseUrl
  if (payload.apiKeys !== undefined) body.api_keys = payload.apiKeys.map(toApiKeyInputWire)
  if (payload.models !== undefined) {
    body.models = payload.models.map((m) => ({
      model_id: m.modelId,
      enabled: m.enabled,
      supports_1m_context: m.supports1mContext,
    }))
  }
  return body
}

/** GET /model-providers —— 提供商列表摘要（不含任何 Key 信息） */
export async function listModelProviders(): Promise<ProviderSummary[]> {
  const { data } = await client.get<Record<string, unknown>[]>('/model-providers')
  return data.map(toProviderSummary)
}

/** POST /model-providers —— 创建提供商（默认自动获取模型列表，失败不阻断创建） */
export async function createModelProvider(
  payload: ModelProviderCreate,
): Promise<ModelProviderCreateResponse> {
  const { data } = await client.post<Record<string, unknown>>('/model-providers', buildCreateBody(payload))
  return {
    provider: toModelProvider(data.provider as Record<string, unknown>),
    ...(data.auto_fetch != null
      ? { autoFetch: toFetchResult(data.auto_fetch as Record<string, unknown>) }
      : {}),
    ...(data.message != null ? { message: data.message as string } : {}),
  }
}

/** GET /model-providers/{provider_id} —— 提供商详情（api_keys 脱敏） */
export async function getModelProvider(providerId: string): Promise<ModelProvider> {
  const { data } = await client.get<Record<string, unknown>>(`/model-providers/${providerId}`)
  return toModelProvider(data)
}

/** PATCH /model-providers/{provider_id} —— 更新提供商（名称/base_url/api_keys/models） */
export async function updateModelProvider(
  providerId: string,
  payload: ModelProviderUpdate,
): Promise<ModelProvider> {
  const { data } = await client.patch<Record<string, unknown>>(
    `/model-providers/${providerId}`,
    buildUpdateBody(payload),
  )
  return toModelProvider(data)
}

/** DELETE /model-providers/{provider_id} —— 删除提供商 */
export async function deleteModelProvider(providerId: string): Promise<void> {
  await client.delete(`/model-providers/${providerId}`)
}

/** POST /model-providers/{provider_id}/fetch-models —— 获取模型列表（合并去重所有启用 Key） */
export async function fetchModels(providerId: string): Promise<ModelFetchResult> {
  const { data } = await client.post<Record<string, unknown>>(
    `/model-providers/${providerId}/fetch-models`,
  )
  return toFetchResult(data)
}

/** POST /model-providers/{provider_id}/detect —— 检测所有 Key 连接状态 */
export async function detectProvider(providerId: string): Promise<KeyDetectResult[]> {
  const { data } = await client.post<Record<string, unknown>[]>(`/model-providers/${providerId}/detect`)
  return data.map(toDetectResult)
}

/** POST /model-providers/{provider_id}/keys/{key_id}/detect —— 检测单个 Key 连接状态 */
export async function detectKey(providerId: string, keyId: string): Promise<KeyDetectResult> {
  const { data } = await client.post<Record<string, unknown>>(
    `/model-providers/${providerId}/keys/${keyId}/detect`,
  )
  return toDetectResult(data)
}

/** 与代码库其他 API 模块一致的对象命名空间（自由函数 + 对象双出口） */
export const modelProvidersApi = {
  listModelProviders,
  createModelProvider,
  getModelProvider,
  updateModelProvider,
  deleteModelProvider,
  fetchModels,
  detectProvider,
  detectKey,
}
