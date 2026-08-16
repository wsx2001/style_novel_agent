import type { ModelProviderType } from '@/types'

/**
 * 模型提供商表单预设常量（docs/TECHv1.1.md §4.2 / §5.1）。
 * 独立成文件以共享给 ModelProviderForm 与 ModelProviderManagement，避免组件文件
 * 导出非常量导致 Fast Refresh 失效（oxlint only-export-components）。
 */

/** 提供商类型选项 */
export const PROVIDER_TYPE_OPTIONS: Array<{ value: ModelProviderType; label: string }> = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'kimi', label: 'Kimi' },
  { value: 'opencode_go', label: 'Opencode Go' },
  { value: 'custom', label: '自定义 OpenAI 兼容' },
  { value: 'other', label: '其他' },
]

/** 提供商类型展示名映射（管理页卡片类型徽标复用） */
export const PROVIDER_TYPE_LABELS: Record<ModelProviderType, string> = Object.fromEntries(
  PROVIDER_TYPE_OPTIONS.map((o) => [o.value, o.label]),
) as Record<ModelProviderType, string>

/** 常见提供商的默认 base_url（选择类型时自动填充，未填写过或等于旧预设时生效） */
export const BASE_URL_PRESETS: Partial<Record<ModelProviderType, string>> = {
  openai: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com/v1',
  deepseek: 'https://api.deepseek.com/v1',
  kimi: 'https://api.moonshot.cn/v1',
}
