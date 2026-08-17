import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { getErrorMessage } from '@/api'
import { modelProvidersApi } from '@/api'
import { cn } from '@/lib/utils'
import type { ApiKeyInfo, ModelProvider, ModelProviderType } from '@/types'
import { BASE_URL_PRESETS, PROVIDER_TYPE_OPTIONS } from './providerPresets'

/**
 * 添加 / 编辑模型提供商弹窗（docs/TECHv1.1.md §5.1 / PRD v1.1 §2.1）。
 *
 * - 新建模式：填写类型 / 名称 / API Keys / Base URL 后，可先点「验证并获取模型列表」
 *   （该操作会先创建提供商并保存 Keys，再请求 /models 合并去重模型），随后勾选启用
 *   模型并保存；也可直接点「保存」由后端自动获取模型列表。
 * - 编辑模式：预填提供商详情（Keys 为脱敏占位符，未改动的 Key 后端复用旧密文），
 *   支持增删 Key、调整优先级与启用状态、启停模型。
 * - 未改动的已有 Key 以脱敏占位符回传（key=keyMasked），后端据此识别并复用旧密文。
 */

/** 表单中的 API Key 草稿（keyId 有值表示已有 Key，key 为脱敏占位符或新明文） */
interface KeyDraft {
  keyId?: string
  key: string
  enabled: boolean
  priority: number
}

/** 表单中的模型草稿（modelId + 启用状态 + 是否支持 1M 上下文） */
interface ModelDraft {
  modelId: string
  enabled: boolean
  supports1mContext: boolean
}

interface ModelProviderFormProps {
  /** 编辑模式：目标提供商 id；新建模式不传 */
  providerId?: string | null
  /** 关闭弹窗 */
  onClose: () => void
  /** 保存成功回调（message 为后端提示，如「未获取到模型」） */
  onSaved: (message?: string) => void
}

/** 默认起始行（新建模式 / 无 Key 时） */
const emptyKey = (priority = 1): KeyDraft => ({ key: '', enabled: true, priority })

export default function ModelProviderForm({ providerId, onClose, onSaved }: ModelProviderFormProps) {
  const queryClient = useQueryClient()

  // 表单状态
  const [type, setType] = useState<ModelProviderType>('opencode_go')
  const [name, setName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [keys, setKeys] = useState<KeyDraft[]>([emptyKey()])
  const [models, setModels] = useState<ModelDraft[]>([])
  const [providerIdState, setProviderIdState] = useState<string | null>(null)
  const [manualModel, setManualModel] = useState('')

  // 流程状态
  const [loadingDetail, setLoadingDetail] = useState(!!providerId)
  const [verifying, setVerifying] = useState(false)
  const [saving, setSaving] = useState(false)
  const [fetchResult, setFetchResult] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)
  const [error, setError] = useState<string | null>(null)

  // 生命周期：新建会话内创建的提供商，未保存就关闭/卸载 → 删除，避免残留空提供商
  const lifecycle = useRef({ createdHere: false, providerId: null as string | null, saved: false })
  const disposed = useRef(false)

  // 编辑模式：加载提供商详情并初始化表单
  useEffect(() => {
    if (!providerId) return
    let cancelled = false
    setLoadingDetail(true)
    modelProvidersApi
      .getModelProvider(providerId)
      .then((detail) => {
        if (cancelled) return
        setType(detail.type)
        setName(detail.name)
        setBaseUrl(detail.baseUrl ?? '')
        setKeys(
          detail.apiKeys.length
            ? detail.apiKeys.map((k) => ({ keyId: k.keyId, key: k.keyMasked, enabled: k.enabled, priority: k.priority }))
            : [emptyKey()],
        )
        setModels(
          detail.models.map((m) => ({
            modelId: m.modelId,
            enabled: m.enabled,
            supports1mContext: m.supports1mContext,
          })),
        )
        setProviderIdState(detail.id)
      })
      .catch((err) => {
        if (!cancelled) setError(getErrorMessage(err))
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false)
      })
    return () => {
      cancelled = true
    }
  }, [providerId])

  // 卸载清理：删除「本弹窗新建但未保存」的提供商。
  // ref 作为稳定的可变容器，cleanup 需读取卸载时的最新值（是否本弹窗新建 / 已保存），
  // 在 effect 内即时复制值反而错误 —— 豁免 exhaustive-deps 规则。
  useEffect(() => {
    return () => {
      disposed.current = true
      // oxlint-disable-next-line react-hooks/exhaustive-deps
      const { createdHere, providerId: pid, saved } = lifecycle.current
      if (createdHere && pid && !saved) {
        modelProvidersApi.deleteModelProvider(pid).catch(() => undefined)
        queryClient.invalidateQueries({ queryKey: ['model-providers'] })
      }
    }
  }, [queryClient])

  // Esc 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const canSave = name.trim().length > 0 && keys.length > 0 && keys.every((k) => k.key.trim().length > 0)

  /** 当前表单 Keys 转 API wire 形态 */
  const keysToWire = (): ApiKeyInfo[] =>
    keys.map((k) => ({ key: k.key.trim() || undefined, keyId: k.keyId, enabled: k.enabled, priority: k.priority }))

  /** 选择类型时自动填充 base_url（为空或等于旧预设时） */
  const handleTypeChange = (value: ModelProviderType) => {
    setType(value)
    const preset = BASE_URL_PRESETS[value]
    if (preset && (!baseUrl.trim() || Object.values(BASE_URL_PRESETS).includes(baseUrl.trim()))) {
      setBaseUrl(preset)
    }
  }

  // ---- API Key 行操作 ----
  const addKey = () => {
    const nextPriority = keys.length ? Math.max(...keys.map((k) => k.priority)) + 1 : 1
    setKeys((prev) => [...prev, emptyKey(nextPriority)])
  }
  const updateKey = (index: number, patch: Partial<KeyDraft>) =>
    setKeys((prev) => prev.map((k, i) => (i === index ? { ...k, ...patch } : k)))
  const removeKey = (index: number) => setKeys((prev) => prev.filter((_, i) => i !== index))

  // ---- 模型操作 ----
  const toggleModel = (modelId: string) =>
    setModels((prev) => prev.map((m) => (m.modelId === modelId ? { ...m, enabled: !m.enabled } : m)))
  const toggleModel1m = (modelId: string) =>
    setModels((prev) =>
      prev.map((m) => (m.modelId === modelId ? { ...m, supports1mContext: !m.supports1mContext } : m)),
    )
  const addManualModel = () => {
    const id = manualModel.trim()
    if (!id || models.some((m) => m.modelId === id)) return
    setModels((prev) => [...prev, { modelId: id, enabled: true, supports1mContext: false }])
    setManualModel('')
  }

  /**
   * 保存当前 Keys（新建则创建提供商，否则 PATCH），返回最新提供商详情。
   * 供「验证并获取模型列表」先落盘 Keys，再触发 /models 获取。
   */
  const persistProvider = async (): Promise<ModelProvider> => {
    const wire = keysToWire()
    if (providerIdState) {
      return modelProvidersApi.updateModelProvider(providerIdState, {
        name,
        type,
        baseUrl: baseUrl.trim() || null,
        apiKeys: wire,
      })
    }
    const res = await modelProvidersApi.createModelProvider({
      name,
      type,
      baseUrl: baseUrl.trim() || null,
      apiKeys: wire,
      autoFetch: false,
    })
    setProviderIdState(res.provider.id)
    lifecycle.current.createdHere = true
    lifecycle.current.providerId = res.provider.id
    return res.provider
  }

  /**
   * 用服务器详情回填表单。
   * preserveModelToggles：保留表单中已有的模型启用勾选（验证后合并去重时不覆盖用户选择）。
   */
  const applyDetail = (detail: ModelProvider, opts?: { preserveModelToggles?: boolean }) => {
    setType(detail.type)
    setName(detail.name)
    setBaseUrl(detail.baseUrl ?? '')
    setKeys(
      detail.apiKeys.length
        ? detail.apiKeys.map((k) => ({ keyId: k.keyId, key: k.keyMasked, enabled: k.enabled, priority: k.priority }))
        : [emptyKey()],
    )
    if (opts?.preserveModelToggles) {
      const current = new Map(models.map((m) => [m.modelId, m]))
      setModels(
        detail.models.map((m) => ({
          modelId: m.modelId,
          enabled: current.get(m.modelId)?.enabled ?? m.enabled,
          supports1mContext: current.get(m.modelId)?.supports1mContext ?? m.supports1mContext,
        })),
      )
    } else {
      setModels(
        detail.models.map((m) => ({
          modelId: m.modelId,
          enabled: m.enabled,
          supports1mContext: m.supports1mContext,
        })),
      )
    }
  }

  /** 验证并获取模型列表：先落盘 Keys，再请求 /models，合并去重后回填模型 */
  const handleVerify = async () => {
    if (!name.trim()) {
      setError('请先填写提供商名称')
      return
    }
    if (!keys.length || keys.some((k) => !k.key.trim())) {
      setError('请至少填写一个 API Key')
      return
    }
    setError(null)
    setFetchResult(null)
    setVerifying(true)
    try {
      const saved = await persistProvider()
      if (disposed.current) return
      const result = await modelProvidersApi.fetchModels(saved.id)
      if (disposed.current) return
      const detail = await modelProvidersApi.getModelProvider(saved.id)
      if (disposed.current) return
      applyDetail(detail, { preserveModelToggles: true })
      setFetchResult(
        result.success
          ? { kind: 'success', text: `成功获取 ${result.models.length} 个模型` }
          : { kind: 'error', text: '未获取到模型（可稍后重试，或手动添加模型 ID）' },
      )
    } catch (err) {
      if (!disposed.current) setError(getErrorMessage(err))
    } finally {
      if (!disposed.current) setVerifying(false)
    }
  }

  /** 保存：新建时由后端自动获取模型列表；编辑时保存 Keys 与模型启用状态 */
  const handleSave = async () => {
    if (!name.trim()) {
      setError('请填写提供商名称')
      return
    }
    if (!keys.length || keys.some((k) => !k.key.trim())) {
      setError('请至少填写一个有效的 API Key')
      return
    }
    setError(null)
    setSaving(true)
    try {
      let message: string
      if (!providerIdState) {
        const res = await modelProvidersApi.createModelProvider({
          name,
          type,
          baseUrl: baseUrl.trim() || null,
          apiKeys: keysToWire(),
          autoFetch: true,
        })
        message = res.message ?? `已添加提供商「${res.provider.name}」`
      } else {
        await modelProvidersApi.updateModelProvider(providerIdState, {
          name,
          type,
          baseUrl: baseUrl.trim() || null,
          apiKeys: keysToWire(),
          models: models.map((m) => ({
            modelId: m.modelId,
            enabled: m.enabled,
            supports1mContext: m.supports1mContext,
          })),
        })
        message = '已保存修改'
      }
      lifecycle.current.saved = true
      setSaving(false)
      onSaved(message)
    } catch (err) {
      setError(getErrorMessage(err))
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto" role="dialog" aria-modal="true">
      {/* 遮罩 */}
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />

      {/* 弹窗主体 */}
      <div className="relative z-10 mx-auto my-8 w-full max-w-2xl rounded-xl border border-border bg-card shadow-2xl">
        <header className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h2 className="text-sm font-semibold text-foreground">
              {providerIdState || providerId ? '编辑提供商' : '添加模型提供商'}
            </h2>
            <p className="mt-0.5 text-[11px] text-slate-400">
              {providerIdState || providerId
                ? '修改 API Keys 与模型启用状态，保存后生效'
                : 'API Key 以 AES-GCM 加密存储，仅展示脱敏信息'}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="rounded-md p-1.5 text-slate-400 hover:bg-background hover:text-foreground"
          >
            ✕
          </button>
        </header>

        {/* 错误横幅 */}
        {error && (
          <div className="border-b border-danger/20 bg-danger/5 px-5 py-2 text-xs text-danger">{error}</div>
        )}

        {loadingDetail ? (
          <div className="p-10 text-center text-sm text-slate-400">加载提供商信息…</div>
        ) : (
          <div className="max-h-[70vh] space-y-5 overflow-y-auto p-5">
            {/* 类型 + 名称 */}
            <div className="grid grid-cols-2 gap-3">
              <label className="text-xs text-slate-500">
                提供商类型
                <select
                  value={type}
                  onChange={(e) => handleTypeChange(e.target.value as ModelProviderType)}
                  className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:border-primary focus:outline-none"
                >
                  {PROVIDER_TYPE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-xs text-slate-500">
                名称
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="如：我的 Opencode"
                  className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:border-primary focus:outline-none"
                />
              </label>
            </div>

            {/* API Key 列表 */}
            <section>
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-xs font-medium text-slate-500">API Key 列表</h3>
                <button
                  type="button"
                  onClick={addKey}
                  className="text-xs text-primary hover:text-primary-hover"
                >
                  ＋ 添加 Key
                </button>
              </div>
              <div className="space-y-2">
                {keys.map((k, index) => (
                  <div key={k.keyId ?? `new-${index}`} className="flex items-center gap-2">
                    <span className="w-10 shrink-0 text-[11px] text-slate-400">Key {index + 1}</span>
                    <input
                      type="password"
                      value={k.key}
                      onChange={(e) => updateKey(index, { key: e.target.value })}
                      placeholder={k.keyId ? '（未改动的 Key 保持原样）' : 'sk-...'}
                      className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:border-primary focus:outline-none"
                    />
                    <label className="flex shrink-0 items-center gap-1 text-xs text-slate-500">
                      <input
                        type="checkbox"
                        checked={k.enabled}
                        onChange={(e) => updateKey(index, { enabled: e.target.checked })}
                        className="h-3.5 w-3.5 accent-primary"
                      />
                      启用
                    </label>
                    <label className="flex shrink-0 items-center gap-1 text-xs text-slate-500">
                      优先级
                      <input
                        type="number"
                        min={1}
                        value={k.priority}
                        onChange={(e) => updateKey(index, { priority: Math.max(1, Number(e.target.value) || 1) })}
                        className="w-16 rounded-md border border-border bg-background px-2 py-1 text-sm focus:border-primary focus:outline-none"
                      />
                    </label>
                    <button
                      type="button"
                      onClick={() => removeKey(index)}
                      title="移除该 Key"
                      className="shrink-0 text-xs text-slate-400 hover:text-danger"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
              <p className="mt-1.5 text-[11px] text-slate-400">
                优先级数值越小越优先；生成时优先使用命中目标模型的 Key，失败自动尝试下一个。
              </p>
            </section>

            {/* Base URL */}
            <label className="block text-xs text-slate-500">
              Base URL <span className="text-slate-400">（可选，适用于自定义兼容接口）</span>
              <input
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://api.example.com/v1"
                className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:border-primary focus:outline-none"
              />
            </label>

            {/* 验证并获取模型列表 */}
            <section className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                disabled={verifying || !name.trim() || keys.some((k) => !k.key.trim())}
                onClick={handleVerify}
                className={cn(
                  'rounded-md px-4 py-2 text-sm font-medium text-primary-foreground transition-colors',
                  verifying || !name.trim() || keys.some((k) => !k.key.trim())
                    ? 'cursor-not-allowed bg-primary/60'
                    : 'bg-primary hover:bg-primary-hover',
                )}
              >
                {verifying ? '验证中…' : '验证并获取模型列表'}
              </button>
              {fetchResult && (
                <span
                  className={cn(
                    'rounded-md px-2.5 py-1.5 text-xs font-medium',
                    fetchResult.kind === 'success'
                      ? 'bg-success/10 text-success'
                      : 'bg-warning/10 text-warning',
                  )}
                >
                  {fetchResult.kind === 'success' ? '✅' : '⚠️'} {fetchResult.text}
                </span>
              )}
            </section>

            {/* 模型列表（合并去重，可勾选启用） */}
            <section>
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-xs font-medium text-slate-500">
                  模型列表（{models.length}）<span className="font-normal text-slate-400">· 仅启用项对项目选择器可见</span>
                </h3>
                <div className="flex items-center gap-2">
                  <input
                    value={manualModel}
                    onChange={(e) => setManualModel(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        addManualModel()
                      }
                    }}
                    disabled={!providerIdState && !providerId}
                    placeholder="手动添加模型 ID"
                    className="w-44 rounded-md border border-border bg-background px-2 py-1 text-xs focus:border-primary focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
                  />
                  <button
                    type="button"
                    onClick={addManualModel}
                    disabled={!providerIdState && !providerId}
                    className="rounded-md border border-border px-2.5 py-1 text-xs text-slate-600 hover:border-primary/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    添加
                  </button>
                </div>
              </div>

              {models.length === 0 ? (
                <p className="rounded-md border border-dashed border-border px-3 py-4 text-center text-xs text-slate-400">
                  尚未获取到模型。点击「验证并获取模型列表」自动合并，或先验证后手动添加模型 ID。
                </p>
              ) : (
                <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                  {models.map((m) => (
                    <div
                      key={m.modelId}
                      className="flex items-center gap-2 rounded-md border border-border px-2 py-1.5 text-sm hover:border-primary/40"
                    >
                      <input
                        type="checkbox"
                        checked={m.enabled}
                        onChange={() => toggleModel(m.modelId)}
                        title="启用该模型（对项目选择器可见）"
                        className="h-3.5 w-3.5 shrink-0 accent-primary"
                      />
                      <span
                        className={cn(
                          'truncate font-mono text-xs',
                          m.enabled ? 'text-foreground' : 'text-slate-400 line-through',
                        )}
                      >
                        {m.modelId}
                      </span>
                      <label
                        className={cn(
                          'ml-auto flex shrink-0 cursor-pointer select-none items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium transition-colors',
                          m.supports1mContext
                            ? 'border-primary/50 bg-primary/10 text-primary'
                            : 'border-border text-slate-400 hover:border-primary/40',
                        )}
                        title="开启后该模型按 1M 上下文窗口使用：文档解析整篇喂入、对话历史与续写/重写上下文放宽（需模型真支持 1M）"
                      >
                        <input
                          type="checkbox"
                          checked={m.supports1mContext}
                          onChange={() => toggleModel1m(m.modelId)}
                          className="hidden"
                        />
                        {m.supports1mContext ? '✓ ' : '· '}1M 上下文
                      </label>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}

        {/* 底部操作 */}
        <footer className="flex justify-end gap-2 border-t border-border px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-border px-4 py-2 text-sm text-slate-600 hover:bg-background"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || loadingDetail || !canSave}
            className={cn(
              'rounded-md px-5 py-2 text-sm font-medium text-primary-foreground transition-colors',
              saving || loadingDetail || !canSave ? 'cursor-not-allowed bg-primary/60' : 'bg-primary hover:bg-primary-hover',
            )}
          >
            {saving ? '保存中…' : '保存'}
          </button>
        </footer>
      </div>
    </div>
  )
}
