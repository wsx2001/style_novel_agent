import client from './client'
import type { ApiKeyConfig, ApiKeySave } from '@/types'

/**
 * 设置相关 API（对应 TECH.md §5.6）。
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
}
