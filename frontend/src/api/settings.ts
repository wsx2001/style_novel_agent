import client from './client'
import type { ApiKeyConfig, ApiKeySave, DepthMapping, GlobalAppSettings, GlobalAppSettingsUpdate } from '@/types'

/**
 * 设置相关 API（对应 TECH.md §5.6；V1 全局设置与思维深度映射，docs/TECHv1.md §5.8）。
 */
export const settingsApi = {
  /** GET /settings/keys —— API Key 列表（脱敏） */
  async listKeys(): Promise<ApiKeyConfig[]> {
    const { data } = await client.get<ApiKeyConfig[]>('/settings/keys')
    return data
  },

  /** POST /settings/keys —— 保存 API Key（明文传入，后端加密存储） */
  async saveKey(payload: ApiKeySave): Promise<ApiKeyConfig> {
    const { data } = await client.post<ApiKeyConfig>('/settings/keys', payload)
    return data
  },

  /** DELETE /settings/keys/{key_id} —— 删除 */
  async deleteKey(keyId: string): Promise<void> {
    await client.delete(`/settings/keys/${keyId}`)
  },

  /** GET /settings/app —— 全局设置（默认模型配置 / 默认提示词模板） */
  async getAppSettings(): Promise<GlobalAppSettings> {
    const { data } = await client.get<GlobalAppSettings>('/settings/app')
    return data
  },

  /** PATCH /settings/app —— 更新全局设置（仅显式传入的字段） */
  async updateAppSettings(payload: GlobalAppSettingsUpdate): Promise<GlobalAppSettings> {
    const { data } = await client.patch<GlobalAppSettings>('/settings/app', payload)
    return data
  },

  /** GET /settings/depth-mapping —— 思维深度映射配置（未配置时后端返回内置默认） */
  async getDepthMapping(): Promise<DepthMapping> {
    const { data } = await client.get<Record<string, unknown>>('/settings/depth-mapping')
    return {
      default: (data.default as Record<string, unknown>) ?? {},
      ...(data.model_overrides ? { modelOverrides: data.model_overrides as Record<string, unknown> } : {}),
    }
  },

  /** PATCH /settings/depth-mapping —— 更新思维深度映射（partial update，省略的字段保留） */
  async updateDepthMapping(mapping: DepthMapping): Promise<DepthMapping> {
    const body: Record<string, unknown> = {}
    if (mapping.default) body.default = mapping.default
    if (mapping.modelOverrides) body.model_overrides = mapping.modelOverrides
    const { data } = await client.patch<Record<string, unknown>>('/settings/depth-mapping', body)
    return {
      default: (data.default as Record<string, unknown>) ?? {},
      ...(data.model_overrides ? { modelOverrides: data.model_overrides as Record<string, unknown> } : {}),
    }
  },
}
