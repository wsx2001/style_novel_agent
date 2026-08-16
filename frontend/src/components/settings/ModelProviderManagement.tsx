import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getErrorMessage } from '@/api'
import { modelProvidersApi, settingsApi } from '@/api'
import { cn } from '@/lib/utils'
import type { KeyDetectResult, ProviderSummary } from '@/types'
import ModelProviderForm from './ModelProviderForm'
import { PROVIDER_TYPE_LABELS } from './providerPresets'

/**
 * 模型提供商管理标签页（docs/TECHv1.1.md §5.1 / PRD v1.1 §2.1）。
 *
 * - 提供商列表（TanStack Query 管理）：卡片展示名称 / 类型 / Key 数量 / 模型数量 /
 *   默认标记 / 状态，提供「检测连接」「设为全局默认」「编辑」「删除」操作。
 * - 检测连接：逐个 Key 请求 /models，卡片内展示每个 Key 的连通状态（有效 / 无效）。
 * - 设为全局默认：调用 PATCH /settings/app 写入 global_default_provider_id，
 *   后端同步 ModelProvider.is_default（唯一全局默认）。
 */

/** Key 检测结果（合并脱敏后的 Key 信息，供卡片内展示每个 Key 的状态） */
interface KeyStatusRow extends KeyDetectResult {
  keyMasked: string
  enabled: boolean
}

export default function ModelProviderManagement() {
  const queryClient = useQueryClient()

  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // formMode 非空时挂载弹窗：{} 新建 / { providerId } 编辑
  const [formMode, setFormMode] = useState<{ providerId?: string | null } | null>(null)
  const [detectingId, setDetectingId] = useState<string | null>(null)
  // 每个提供商检测后的 Key 状态（providerId → KeyStatusRow[]）
  const [keyStatus, setKeyStatus] = useState<Record<string, KeyStatusRow[]>>({})
  // 卡片内 Key 状态区域是否展开
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  const { data: providers = [], isLoading, isError } = useQuery({
    queryKey: ['model-providers'],
    queryFn: modelProvidersApi.listModelProviders,
  })

  // 成功提示自动消失
  useEffect(() => {
    if (!notice) return
    const timer = setTimeout(() => setNotice(null), 3500)
    return () => clearTimeout(timer)
  }, [notice])

  const notify = (message: string) => {
    setError(null)
    setNotice(message)
  }
  const reportError = (message: string) => {
    setNotice(null)
    setError(message)
  }

  const setDefaultMutation = useMutation({
    mutationFn: (providerId: string) =>
      settingsApi.updateAppSettings({ global_default_provider_id: providerId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['model-providers'] })
      queryClient.invalidateQueries({ queryKey: ['settings-app'] })
      notify('已设为全局默认提供商')
    },
    onError: (err) => reportError(getErrorMessage(err)),
  })

  const deleteMutation = useMutation({
    mutationFn: (providerId: string) => modelProvidersApi.deleteModelProvider(providerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['model-providers'] })
      queryClient.invalidateQueries({ queryKey: ['settings-app'] })
      notify('已删除提供商')
    },
    onError: (err) => reportError(getErrorMessage(err)),
  })

  const handleDelete = (provider: ProviderSummary) => {
    if (!window.confirm(`确定删除提供商「${provider.name}」？\n相关项目 / 会话将回退到全局默认，此操作不可撤销。`)) return
    deleteMutation.mutate(provider.id)
  }

  /** 检测连接：请求所有 Key 的状态，并拉取详情合并脱敏 Key 信息 */
  const handleDetect = async (provider: ProviderSummary) => {
    setDetectingId(provider.id)
    setError(null)
    try {
      const results = await modelProvidersApi.detectProvider(provider.id)
      const detail = await modelProvidersApi.getModelProvider(provider.id)
      const masked = new Map(detail.apiKeys.map((k) => [k.keyId, k.keyMasked]))
      const enabled = new Map(detail.apiKeys.map((k) => [k.keyId, k.enabled]))
      const rows: KeyStatusRow[] = results.map((r) => ({
        ...r,
        keyMasked: masked.get(r.keyId) ?? r.keyId,
        enabled: enabled.get(r.keyId) ?? true,
      }))
      setKeyStatus((prev) => ({ ...prev, [provider.id]: rows }))
      setExpanded((prev) => ({ ...prev, [provider.id]: true }))
      queryClient.invalidateQueries({ queryKey: ['model-providers'] })
    } catch (err) {
      reportError(getErrorMessage(err))
    } finally {
      setDetectingId(null)
    }
  }

  const handleSaved = (message?: string) => {
    setFormMode(null)
    if (message && message.includes('未获取到模型')) {
      setNotice(message)
    } else {
      notify(message ?? '已保存')
    }
  }

  return (
    <div className="space-y-5">
      {/* 标题 + 添加按钮 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-foreground">模型提供商（{providers.length}）</h2>
          <p className="mt-0.5 text-xs text-slate-400">
            管理 AI 服务商与 API Key；添加后可自动获取模型列表，并设置全局默认提供商。
          </p>
        </div>
        <button
          onClick={() => setFormMode({})}
          className="shrink-0 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover"
        >
          ＋ 添加提供商
        </button>
      </div>

      {/* 提示 / 错误横幅（「未获取到模型」等后端警告用 warning 色调） */}
      {(notice || error) && (
        <div
          className={cn(
            'rounded-lg border px-4 py-2 text-xs',
            notice
              ? notice.includes('未获取到模型')
                ? 'border-warning/20 bg-warning/5 text-warning'
                : 'border-primary/20 bg-primary/5 text-primary'
              : 'border-danger/20 bg-danger/5 text-danger',
          )}
        >
          {notice ?? error}
        </div>
      )}

      {/* 提供商卡片列表 */}
      {isLoading && <p className="rounded-xl border border-border bg-card p-8 text-center text-sm text-slate-400">加载中…</p>}
      {isError && (
        <p className="rounded-xl border border-border bg-card p-8 text-center text-sm text-danger">
          加载提供商列表失败，请确认后端服务已启动。
        </p>
      )}
      {!isLoading && !isError && providers.length === 0 && (
        <p className="rounded-xl border border-dashed border-border bg-card p-10 text-center text-sm text-slate-400">
          尚未添加模型提供商。点击右上角「＋ 添加提供商」开始配置。
        </p>
      )}

      {providers.map((provider) => (
        <article key={provider.id} className="rounded-xl border border-border bg-card p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-foreground">{provider.name}</h3>
            <span className="rounded bg-background px-1.5 py-0.5 text-[10px] font-medium text-slate-500">
              {PROVIDER_TYPE_LABELS[provider.type]}
            </span>
            {provider.isDefault && (
              <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                ★ 全局默认
              </span>
            )}
            <span
              className={cn(
                'ml-auto inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium',
                provider.status === 'ready' ? 'bg-success/10 text-success' : 'bg-warning/10 text-warning',
              )}
            >
              <span className={cn('h-1.5 w-1.5 rounded-full', provider.status === 'ready' ? 'bg-success' : 'bg-warning')} />
              状态：{provider.status === 'ready' ? '有效' : '无启用 Key'}
            </span>
          </div>

          <p className="mt-2 text-xs text-slate-400">
            Key {provider.keyCount}（启用 {provider.enabledKeyCount}）· 模型 {provider.modelCount}（启用{' '}
            {provider.enabledModelCount}）
          </p>
          {provider.baseUrl && <p className="mt-0.5 truncate text-xs text-slate-400">{provider.baseUrl}</p>}

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              onClick={() => handleDetect(provider)}
              disabled={detectingId === provider.id}
              className="rounded-md border border-border px-3 py-1.5 text-xs text-slate-600 hover:border-primary/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
            >
              {detectingId === provider.id ? '检测中…' : '检测连接'}
            </button>
            <button
              onClick={() => setDefaultMutation.mutate(provider.id)}
              disabled={provider.isDefault || setDefaultMutation.isPending}
              className={cn(
                'rounded-md border border-border px-3 py-1.5 text-xs',
                provider.isDefault
                  ? 'cursor-default text-slate-300'
                  : 'text-slate-600 hover:border-primary/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50',
              )}
            >
              {provider.isDefault ? '已为全局默认' : '设为全局默认'}
            </button>
            <button
              onClick={() => setFormMode({ providerId: provider.id })}
              className="rounded-md border border-border px-3 py-1.5 text-xs text-slate-600 hover:border-primary/40 hover:text-foreground"
            >
              编辑
            </button>
            <button
              onClick={() => handleDelete(provider)}
              className="ml-auto rounded-md border border-border px-3 py-1.5 text-xs text-danger hover:border-danger/40 hover:bg-danger/5"
            >
              删除
            </button>
          </div>

          {/* Key 连接状态（检测后展示） */}
          {expanded[provider.id] && keyStatus[provider.id] && (
            <div className="mt-3 rounded-lg border border-border bg-background p-3">
              <div className="flex items-center justify-between">
                <p className="text-[11px] font-medium text-slate-500">Key 连接状态</p>
                <button
                  onClick={() => setExpanded((prev) => ({ ...prev, [provider.id]: false }))}
                  className="text-[11px] text-slate-400 hover:text-foreground"
                >
                  收起
                </button>
              </div>
              <ul className="mt-2 space-y-1.5">
                {keyStatus[provider.id].map((row) => (
                  <li key={row.keyId} className="flex flex-wrap items-center gap-2 text-xs">
                    <code className="rounded bg-border/60 px-1.5 py-0.5 text-slate-600">{row.keyMasked}</code>
                    <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-medium', row.enabled ? 'bg-border/40 text-slate-500' : 'bg-border/40 text-slate-400')}>
                      {row.enabled ? '已启用' : '已禁用'}
                    </span>
                    {row.valid ? (
                      <span className="font-medium text-success">✓ 有效 · {row.modelCount} 个模型</span>
                    ) : (
                      <span className="font-medium text-danger" title={row.error ?? undefined}>
                        ✕ 无效{row.error ? `：${row.error}` : ''}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </article>
      ))}

      {/* 添加 / 编辑弹窗 */}
      {formMode && (
        <ModelProviderForm
          providerId={formMode.providerId}
          onClose={() => setFormMode(null)}
          onSaved={handleSaved}
        />
      )}
    </div>
  )
}
