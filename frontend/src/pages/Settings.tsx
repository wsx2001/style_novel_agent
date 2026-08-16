import { useState } from 'react'
import { cn } from '@/lib/utils'
import ModelProviderManagement from '@/components/settings/ModelProviderManagement'
import ModelPromptSettings from '@/components/settings/ModelPromptSettings'
import { useSettingsPanelStore } from '@/store/settingsPanel'

const SETTINGS_TABS = [
  { value: 'providers', label: '模型提供商' },
  { value: 'model', label: '模型 / 提示词设置' },
] as const

type SettingsTab = (typeof SETTINGS_TABS)[number]['value']

/**
 * 设置页（docs/TECHv1.1.md §5.1 / PRD v1.1 §2.1）。
 *
 * - 「模型提供商」标签页：管理 AI 服务商 / API Key / 模型列表，可检测连接并设置全局默认。
 * - 「模型 / 提示词设置」标签页：全局默认思维深度、随机性、最大输出长度与系统提示词模板。
 *
 * V1.1 起旧 ApiKeyConfig 管理（/settings/keys）已迁移到模型提供商，原「已配置的 API Key」
 * 与「添加 API Key」区块随之移除（对应端点已从后端删除）。
 */
export default function Settings() {
  const [tab, setTab] = useState<SettingsTab>('providers')
  const togglePanel = useSettingsPanelStore((s) => s.togglePanel)

  return (
    <div className="mx-auto min-h-full max-w-3xl space-y-6 bg-background px-6 py-6">
      <header>
        <h1 className="text-2xl font-bold text-foreground">设置</h1>
        <p className="mt-1 text-sm text-slate-500">
          管理 AI 模型提供商（API Key 加密存储，不暴露明文）与全局模型 / 提示词默认值
        </p>
      </header>

      {/* 标签页导航 */}
      <nav className="flex shrink-0 border-b border-border">
        {SETTINGS_TABS.map((t) => (
          <button
            key={t.value}
            type="button"
            onClick={() => setTab(t.value)}
            className={cn(
              'border-b-2 px-4 py-2.5 text-sm transition-colors',
              tab === t.value
                ? 'border-primary font-medium text-primary'
                : 'border-transparent text-slate-500 hover:text-foreground',
            )}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === 'providers' ? (
        <ModelProviderManagement />
      ) : (
        <section className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-sm font-semibold text-foreground">模型 / 提示词设置</h2>
              <p className="mt-1 text-xs text-slate-400">
                配置全局默认思维深度、随机性、最大输出长度与系统提示词模板；新创建的项目会继承这些默认值。
              </p>
            </div>
            <button
              className="shrink-0 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover"
              onClick={togglePanel}
            >
              ⚙ 打开设置面板
            </button>
          </div>
        </section>
      )}

      {/* 全局模型/提示词设置抽屉（任一标签页均可打开） */}
      <ModelPromptSettings scope="global" />
    </div>
  )
}
