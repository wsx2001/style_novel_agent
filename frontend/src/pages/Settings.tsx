import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { settingsApi } from '@/api/settings'
import { getErrorMessage } from '@/api/client'
import { cn } from '@/lib/utils'
import type { ApiKeyConfig, ApiProvider } from '@/types'

/** 常见提供商的默认 base_url（选择时自动填充） */
const PROVIDER_PRESETS: Record<Exclude<ApiProvider, 'custom'>, string> = {
  openai: 'https://api.openai.com/v1',
  deepseek: 'https://api.deepseek.com/v1',
  kimi: 'https://api.moonshot.cn/v1',
  moonshot: 'https://api.moonshot.cn/v1',
}

const PROVIDER_MODEL_HINT: Record<ApiProvider, string> = {
  openai: 'gpt-4o-mini',
  deepseek: 'deepseek-chat',
  kimi: 'moonshot-v1-8k',
  moonshot: 'moonshot-v1-8k',
  custom: '你的模型名',
}

/**
 * 设置页：API Key 管理（加密存储 / 脱敏展示）。
 * 配置的 Key 供解析、embedding 与 AI 生成使用（项目级优先，回退全局）。
 */
export default function Settings() {
  const queryClient = useQueryClient()
  const { data: keys = [], isLoading } = useQuery({
    queryKey: ['settings-keys'],
    queryFn: settingsApi.listKeys,
  })

  const [provider, setProvider] = useState<ApiProvider>('deepseek')
  const [name, setName] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(PROVIDER_PRESETS.deepseek)
  const [model, setModel] = useState('')
  const [isDefault, setIsDefault] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const saveMutation = useMutation({
    mutationFn: () =>
      settingsApi.saveKey({
        provider,
        name,
        api_key: apiKey,
        base_url: baseUrl,
        model: model.trim() || undefined,
        is_default: isDefault,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings-keys'] })
      setName('')
      setApiKey('')
      setModel('')
      setIsDefault(false)
      setError(null)
    },
    onError: (err) => setError(getErrorMessage(err)),
  })

  const deleteMutation = useMutation({
    mutationFn: (keyId: string) => settingsApi.deleteKey(keyId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settings-keys'] }),
  })

  const handleProviderChange = (value: ApiProvider) => {
    setProvider(value)
    if (value !== 'custom') setBaseUrl(PROVIDER_PRESETS[value])
  }

  const handleDelete = (key: ApiKeyConfig) => {
    if (window.confirm(`确定删除 API Key「${key.name}」？`)) deleteMutation.mutate(key.id)
  }

  return (
    <div className="mx-auto min-h-full max-w-3xl space-y-6 bg-background px-6 py-6">
      <header>
        <h1 className="text-2xl font-bold text-foreground">设置</h1>
        <p className="mt-1 text-sm text-slate-500">
          配置 API Key（AES-GCM 加密存储，不暴露明文），供文档解析、embedding 与 AI 生成使用
        </p>
      </header>

      {/* 已配置的 Key */}
      <section className="rounded-xl border border-border bg-card">
        <header className="border-b border-border px-4 py-2.5">
          <h2 className="text-sm font-semibold text-foreground">已配置的 API Key（{keys.length}）</h2>
        </header>
        {isLoading && <p className="p-4 text-sm text-slate-400">加载中…</p>}
        {!isLoading && keys.length === 0 && (
          <p className="p-4 text-sm text-slate-400">尚未配置 API Key，请在下方添加</p>
        )}
        <ul className="divide-y divide-border">
          {keys.map((key) => (
            <li key={key.id} className="flex items-center gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 text-sm font-medium text-foreground">
                  {key.name}
                  {key.is_default && (
                    <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                      默认
                    </span>
                  )}
                </p>
                <p className="mt-0.5 truncate text-xs text-slate-400">
                  {key.provider} · <code className="text-slate-500">{key.key_masked}</code>
                  {key.model ? ` · ${key.model}` : ''}
                </p>
                <p className="truncate text-xs text-slate-400">{key.base_url}</p>
              </div>
              <button
                className="shrink-0 text-xs text-slate-400 hover:text-danger"
                onClick={() => handleDelete(key)}
              >
                删除
              </button>
            </li>
          ))}
        </ul>
      </section>

      {/* 新增 / 更新表单 */}
      <section className="rounded-xl border border-border bg-card p-5">
        <h2 className="mb-4 text-sm font-semibold text-foreground">添加 API Key</h2>
        <div className="grid grid-cols-2 gap-3">
          <label className="text-xs text-slate-500">
            提供商
            <select
              value={provider}
              onChange={(e) => handleProviderChange(e.target.value as ApiProvider)}
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:border-primary focus:outline-none"
            >
              {(['openai', 'deepseek', 'kimi', 'moonshot', 'custom'] as ApiProvider[]).map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </label>
          <label className="text-xs text-slate-500">
            名称
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="如：deepseek-main"
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:border-primary focus:outline-none"
            />
          </label>
          <label className="col-span-2 text-xs text-slate-500">
            API Key
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:border-primary focus:outline-none"
            />
          </label>
          <label className="col-span-2 text-xs text-slate-500">
            Base URL
            <input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.example.com/v1"
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:border-primary focus:outline-none"
            />
          </label>
          <label className="text-xs text-slate-500">
            模型
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={PROVIDER_MODEL_HINT[provider]}
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:border-primary focus:outline-none"
            />
          </label>
          <div className="flex items-end pb-1">
            <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-500">
              <input
                type="checkbox"
                checked={isDefault}
                onChange={(e) => setIsDefault(e.target.checked)}
                className="h-4 w-4 accent-primary"
              />
              设为默认（优先使用）
            </label>
          </div>
        </div>

        {error && <p className="mt-3 text-xs text-danger">{error}</p>}

        <div className="mt-4 flex justify-end">
          <button
            className={cn(
              'rounded-md px-5 py-2 text-sm font-medium text-primary-foreground',
              saveMutation.isPending ? 'bg-primary/60' : 'bg-primary hover:bg-primary-hover',
            )}
            disabled={saveMutation.isPending || !apiKey.trim() || !name.trim() || !baseUrl.trim()}
            onClick={() => saveMutation.mutate()}
          >
            {saveMutation.isPending ? '保存中…' : '保存'}
          </button>
        </div>
      </section>
    </div>
  )
}
