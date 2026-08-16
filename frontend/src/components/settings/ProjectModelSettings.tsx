import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getErrorMessage } from '@/api'
import { modelProvidersApi, projectsApi, settingsApi } from '@/api'
import { cn } from '@/lib/utils'

interface ProjectModelSettingsProps {
  projectId: string
}

/**
 * 项目设置 - 模型设置区域（docs/TECHv1.1.md §5.2 / PRD v1.1 §4.2）。
 *
 * - 「使用全局默认」开启：项目不写入 default_provider_id / default_model_id
 *   （保存时提交 null），并只读展示当前全局默认值；
 * - 关闭后：提供商下拉来自全局提供商列表（TanStack Query），选中后自动加载
 *   该提供商已启用的模型列表供选择；切换提供商时模型下拉同步更新；
 * - 保存调用 PATCH /projects/{id}，提交 default_provider_id / default_model_id。
 */
export default function ProjectModelSettings({ projectId }: ProjectModelSettingsProps) {
  const queryClient = useQueryClient()

  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // 项目详情（含 default_provider_id / default_model_id）
  const { data: project } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => projectsApi.get(projectId),
  })

  // 全局提供商列表（来自全局设置）
  const {
    data: providers = [],
    isLoading: providersLoading,
  } = useQuery({
    queryKey: ['model-providers'],
    queryFn: modelProvidersApi.listModelProviders,
  })

  // 全局默认提供商 / 模型（仅用于只读提示）
  const { data: appSettings } = useQuery({
    queryKey: ['settings-app'],
    queryFn: settingsApi.getAppSettings,
  })

  // ===== 表单状态 =====
  const [useGlobalDefault, setUseGlobalDefault] = useState(true)
  const [providerId, setProviderId] = useState('')
  const [modelId, setModelId] = useState('')

  // 项目保存的默认值变化时同步表单（首次加载 / 保存成功后），不打断编辑中的选择
  const projectLoaded = project != null
  const savedProviderId = project?.default_provider_id ?? null
  const savedModelId = project?.default_model_id ?? null
  useEffect(() => {
    if (!projectLoaded) return
    setUseGlobalDefault(savedProviderId == null)
    setProviderId(savedProviderId ?? '')
    setModelId(savedModelId ?? '')
  }, [savedProviderId, savedModelId, projectLoaded])

  // 选中提供商时加载其启用模型列表
  const { data: providerDetail, isLoading: modelLoading } = useQuery({
    queryKey: ['model-provider', providerId],
    queryFn: () => modelProvidersApi.getModelProvider(providerId),
    enabled: !!providerId && !useGlobalDefault,
  })
  const enabledModels = useMemo(
    () => (providerDetail?.models ?? []).filter((m) => m.enabled).map((m) => m.modelId),
    [providerDetail],
  )
  // 切换提供商后，若原所选模型不在新提供商的启用模型中，则回退为空（派生，无需手动清空）
  const selectedModelId = enabledModels.includes(modelId) ? modelId : ''

  // 全局默认展示文本（只读）
  const globalProviderId = appSettings?.global_default_provider_id ?? ''
  const globalModelId = appSettings?.global_default_model_id ?? ''
  const globalProviderName = providers.find((p) => p.id === globalProviderId)?.name
  const globalDefaultText = globalProviderId
    ? `${globalProviderName ?? globalProviderId}${globalModelId ? ` · ${globalModelId}` : ''}`
    : null

  // ===== 保存 =====
  const saveMutation = useMutation({
    mutationFn: () =>
      projectsApi.update(projectId, {
        // 使用全局默认时置空项目默认提供商与模型（docs/TECHv1.1.md §5.2）
        default_provider_id: useGlobalDefault ? null : providerId,
        default_model_id: useGlobalDefault ? null : selectedModelId,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project', projectId] })
      setError(null)
      setNotice('已保存项目模型设置，新设置将应用于后续生成。')
    },
    onError: (err) => {
      setNotice(null)
      setError(getErrorMessage(err))
    },
  })

  // 成功提示自动消失
  useEffect(() => {
    if (!notice) return
    const timer = setTimeout(() => setNotice(null), 3500)
    return () => clearTimeout(timer)
  }, [notice])

  const canSave = useGlobalDefault || (!!providerId && !!selectedModelId)

  return (
    <section className="rounded-xl border border-border bg-card p-5">
      <h2 className="text-sm font-semibold text-foreground">模型设置</h2>
      <p className="mt-1 text-xs text-slate-400">
        选择当前项目使用的提供商与模型；未设置时继承全局默认，不影响全局设置。
      </p>

      {/* 使用全局默认开关 */}
      <fieldset className="mt-4">
        <legend className="text-xs text-slate-500">使用全局默认</legend>
        <div className="mt-1.5 flex gap-6">
          <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-600">
            <input
              type="radio"
              name="project-use-global-default"
              checked={useGlobalDefault}
              onChange={() => setUseGlobalDefault(true)}
              className="h-4 w-4 accent-primary"
            />
            是
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-600">
            <input
              type="radio"
              name="project-use-global-default"
              checked={!useGlobalDefault}
              onChange={() => setUseGlobalDefault(false)}
              className="h-4 w-4 accent-primary"
            />
            否
          </label>
        </div>
      </fieldset>

      {/* 提供商 / 模型（使用全局默认时禁用） */}
      <div className="mt-4 grid gap-3">
        <label className="block text-xs text-slate-500">
          提供商
          <select
            value={providerId}
            disabled={useGlobalDefault || providersLoading}
            onChange={(e) => setProviderId(e.target.value)}
            className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:border-primary focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
          >
            <option value="">{providersLoading ? '加载中…' : '请选择提供商'}</option>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>

        <label className="block text-xs text-slate-500">
          模型
          <select
            value={selectedModelId}
            disabled={useGlobalDefault || !providerId || modelLoading}
            onChange={(e) => setModelId(e.target.value)}
            className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:border-primary focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
          >
            <option value="">
              {!providerId
                ? '请先选择提供商'
                : modelLoading
                  ? '加载中…'
                  : enabledModels.length === 0
                    ? '该提供商暂无已启用模型'
                    : '请选择模型'}
            </option>
            {enabledModels.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* 无提供商提示（指向全局设置） */}
      {!useGlobalDefault && providers.length === 0 && !providersLoading && (
        <p className="mt-3 rounded-lg border border-warning/20 bg-warning/5 px-3 py-2 text-xs text-warning">
          尚未添加模型提供商，请先到
          <Link to="/settings" className="ml-0.5 font-medium underline underline-offset-2">
            全局设置
          </Link>
          中添加。
        </p>
      )}

      {/* 全局默认只读提示（使用全局默认 / 项目未设置时） */}
      {useGlobalDefault && (
        <p className="mt-3 rounded-lg border border-border bg-background px-3 py-2 text-xs text-slate-500">
          当前继承全局默认：
          {globalDefaultText ? (
            <span className="font-medium text-foreground">{globalDefaultText}</span>
          ) : (
            <span className="text-slate-400">全局未设置默认提供商 / 模型</span>
          )}
        </p>
      )}

      {/* 提示 / 错误横幅 */}
      {(notice || error) && (
        <div
          className={cn(
            'mt-3 rounded-lg border px-3 py-2 text-xs',
            notice
              ? 'border-primary/20 bg-primary/5 text-primary'
              : 'border-danger/20 bg-danger/5 text-danger',
          )}
        >
          {notice ?? error}
        </div>
      )}

      <div className="mt-4 flex items-center justify-end gap-3">
        <p className="text-[11px] text-slate-400">保存后仅影响本项目后续生成。</p>
        <button
          type="button"
          disabled={!canSave || saveMutation.isPending}
          onClick={() => saveMutation.mutate()}
          className={cn(
            'rounded-md px-4 py-2 text-sm font-medium text-primary-foreground transition-colors',
            saveMutation.isPending ? 'bg-primary/60' : 'bg-primary hover:bg-primary-hover',
            (!canSave || saveMutation.isPending) && 'cursor-not-allowed opacity-60',
          )}
        >
          {saveMutation.isPending ? '保存中…' : '保存'}
        </button>
      </div>
    </section>
  )
}
