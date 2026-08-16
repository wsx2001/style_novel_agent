import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getErrorMessage } from '@/api/client'
import { projectsApi } from '@/api'
import { conversationsApi } from '@/api/conversations'
import { promptTemplatesApi } from '@/api/promptTemplates'
import { settingsApi } from '@/api/settings'
import { cn } from '@/lib/utils'
import { useSettingsPanelStore } from '@/store/settingsPanel'
import type { DepthLevel, SettingsPanelScope } from '@/types'
import ModelSettingsTab, { type NormalizedModelConfig } from './ModelSettingsTab'
import PromptSettingsTab from './PromptSettingsTab'

interface ModelPromptSettingsProps {
  /** 作用范围：global 设置页 / project 项目工作台 / conversation 对话工作台 */
  scope: SettingsPanelScope
  /** 项目 id（scope=project 时必传） */
  projectId?: string | null
  /** 会话 id（scope=conversation 时必传） */
  conversationId?: string | null
}

const DEFAULT_CONFIG: NormalizedModelConfig = { depth: 'auto', temperature: 0.7, maxTokens: 0 }

const DEPTH_VALUES: DepthLevel[] = ['none', 'auto', 'low', 'medium', 'high', 'extreme']

/** 将作用域配置归一化为表单值（兼容 snake `max_tokens` 与 camel `maxTokens`） */
function normalizeConfig(cfg: Record<string, unknown> | undefined): NormalizedModelConfig {
  const temperature =
    typeof cfg?.temperature === 'number'
      ? cfg.temperature
      : typeof cfg?.temperature === 'string'
        ? Number(cfg.temperature)
        : DEFAULT_CONFIG.temperature
  const rawMax = (cfg?.max_tokens ?? cfg?.maxTokens) as unknown
  const maxTokens =
    typeof rawMax === 'number'
      ? rawMax
      : typeof rawMax === 'string'
        ? Number(rawMax)
        : DEFAULT_CONFIG.maxTokens
  const depth = DEPTH_VALUES.includes(cfg?.depth as DepthLevel) ? (cfg?.depth as DepthLevel) : DEFAULT_CONFIG.depth
  return {
    depth,
    temperature: Number.isFinite(temperature) ? temperature : DEFAULT_CONFIG.temperature,
    maxTokens: Number.isFinite(maxTokens) ? maxTokens : DEFAULT_CONFIG.maxTokens,
  }
}

const TABS = [
  { value: 'model', label: '模型设置' },
  { value: 'prompt', label: '提示词设置' },
] as const

/**
 * 模型/提示词设置抽屉面板（PRDv1 §1.2 / §2.2，docs/TECHv1.md §5.8）。
 *
 * 打开状态由 Zustand store（store/settingsPanel.ts）全局管理，任意宿主调用
 * `openPanel()` / `togglePanel()` 即可打开；作用范围通过 props 传入，按范围调用
 * 不同 API：
 *   - global：       GET/PATCH /settings/app（全局默认模型配置与默认模板）
 *   - project：      GET/PATCH /projects/{id}（项目默认模型配置与默认模板）
 *   - conversation： GET/PATCH /conversations/{id}（会话模型配置 / 模板 / 临时覆盖）
 */
export default function ModelPromptSettings({
  scope,
  projectId = null,
  conversationId = null,
}: ModelPromptSettingsProps) {
  const open = useSettingsPanelStore((s) => s.open)
  const closePanel = useSettingsPanelStore((s) => s.closePanel)
  const queryClient = useQueryClient()

  const [tab, setTab] = useState<'model' | 'prompt'>('model')
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // 成功提示横幅自动消失
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

  // Esc 关闭
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closePanel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, closePanel])

  // 每次打开面板回到「模型设置」标签页
  useEffect(() => {
    if (open) setTab('model')
  }, [open])

  // ===== 数据查询（仅面板打开时拉取） =====
  const { data: globalTemplates = [] } = useQuery({
    queryKey: ['prompt-templates', { scope: 'global' }],
    queryFn: () => promptTemplatesApi.listPromptTemplates('global'),
    enabled: open,
  })

  const { data: conversation } = useQuery({
    queryKey: ['conversation', conversationId],
    queryFn: () => conversationsApi.getConversation(conversationId!),
    enabled: open && scope === 'conversation' && !!conversationId,
  })

  const effectiveProjectId =
    scope === 'project' ? projectId : scope === 'conversation' ? (conversation?.projectId ?? null) : null

  const { data: projectTemplates = [] } = useQuery({
    queryKey: ['prompt-templates', { scope: 'project', projectId: effectiveProjectId }],
    queryFn: () => promptTemplatesApi.listPromptTemplates('project', effectiveProjectId!),
    enabled: open && !!effectiveProjectId,
  })

  const templates = useMemo(() => [...globalTemplates, ...projectTemplates], [globalTemplates, projectTemplates])

  const { data: appSettings } = useQuery({
    queryKey: ['settings-app'],
    queryFn: settingsApi.getAppSettings,
    enabled: open && scope === 'global',
  })
  const { data: project } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => projectsApi.get(projectId!),
    enabled: open && scope === 'project' && !!projectId,
  })

  const currentConfig: Record<string, unknown> | undefined =
    scope === 'global'
      ? (appSettings?.global_default_model_config ?? undefined)
      : scope === 'project'
        ? (project?.default_model_config ?? undefined)
        : (conversation?.modelConfig as Record<string, unknown> | undefined)

  const currentTemplateId: string | null =
    scope === 'global'
      ? (appSettings?.global_default_prompt_template_id || null)
      : scope === 'project'
        ? (project?.default_prompt_template_id ?? null)
        : (conversation?.systemPromptTemplateId ?? null)

  const hasOverride = scope === 'conversation' ? conversation?.systemPromptOverride != null : false

  const loading =
    scope === 'global' ? !appSettings : scope === 'project' ? !project : !conversation

  const initialConfig = normalizeConfig(currentConfig)

  // ===== 保存 / 应用逻辑 =====
  const invalidateScope = () => {
    if (scope === 'global') queryClient.invalidateQueries({ queryKey: ['settings-app'] })
    else if (scope === 'project') queryClient.invalidateQueries({ queryKey: ['project', projectId] })
    else queryClient.invalidateQueries({ queryKey: ['conversation', conversationId] })
  }

  const saveModelMutation = useMutation({
    mutationFn: (config: NormalizedModelConfig): Promise<unknown> => {
      if (scope === 'conversation') {
        return conversationsApi.updateConversation(conversationId!, {
          modelConfig: { depth: config.depth, temperature: config.temperature, maxTokens: config.maxTokens },
        })
      }
      const wire = { depth: config.depth, temperature: config.temperature, max_tokens: config.maxTokens }
      return scope === 'project'
        ? projectsApi.update(projectId!, { default_model_config: wire })
        : settingsApi.updateAppSettings({ global_default_model_config: wire })
    },
    onSuccess: () => {
      invalidateScope()
      notify('新设置将应用于后续消息，不影响已有消息。')
    },
    onError: (err) => reportError(getErrorMessage(err)),
  })

  const applyTemplateMutation = useMutation({
    mutationFn: (templateId: string | null): Promise<unknown> => {
      if (scope === 'conversation') {
        // 应用模板时同时清除临时覆盖，让所选模板立即生效
        return conversationsApi.updateConversation(conversationId!, {
          systemPromptTemplateId: templateId,
          systemPromptOverride: null,
        })
      }
      if (scope === 'project') return projectsApi.update(projectId!, { default_prompt_template_id: templateId })
      return settingsApi.updateAppSettings({ global_default_prompt_template_id: templateId ?? '' })
    },
    onSuccess: () => {
      invalidateScope()
      notify('新设置将应用于后续消息，不影响已有消息。')
    },
    onError: (err) => reportError(getErrorMessage(err)),
  })

  const title =
    scope === 'conversation' ? '会话模型/提示词设置' : scope === 'project' ? '项目模型/提示词设置' : '全局模型/提示词设置'
  const scopeLabel = scope === 'conversation' ? '当前会话' : scope === 'project' ? '当前项目' : '全局'

  return (
    <div className={cn('fixed inset-0 z-50', !open && 'pointer-events-none')} aria-hidden={!open}>
      {/* 遮罩 */}
      <div
        className={cn('absolute inset-0 bg-black/40 transition-opacity duration-200', open ? 'opacity-100' : 'opacity-0')}
        onClick={closePanel}
      />
      {/* 抽屉 */}
      <aside
        className={cn(
          'absolute right-0 top-0 flex h-full w-full max-w-xl flex-col bg-card shadow-2xl transition-transform duration-200',
          open ? 'translate-x-0' : 'translate-x-full',
        )}
      >
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-border px-4">
          <div>
            <h2 className="text-sm font-semibold text-foreground">{title}</h2>
            <p className="mt-0.5 text-[11px] text-slate-400">作用范围：{scopeLabel}</p>
          </div>
          <button
            type="button"
            onClick={closePanel}
            aria-label="关闭"
            className="rounded-md p-1.5 text-slate-400 hover:bg-background hover:text-foreground"
          >
            ✕
          </button>
        </header>

        {/* 通知横幅 */}
        {(notice || error) && (
          <div
            className={cn(
              'border-b px-4 py-2 text-xs',
              notice ? 'border-primary/20 bg-primary/5 text-primary' : 'border-danger/20 bg-danger/5 text-danger',
            )}
          >
            {notice ?? error}
          </div>
        )}

        {/* 标签页 */}
        <nav className="flex shrink-0 border-b border-border px-2">
          {TABS.map((t) => (
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

        {/* 内容 */}
        <div className="min-h-0 flex-1 overflow-auto p-4">
          {tab === 'model' ? (
            <ModelSettingsTab
              key={`${open ? 'open' : 'closed'}:${JSON.stringify(initialConfig)}`}
              initialConfig={initialConfig}
              loading={loading}
              saving={saveModelMutation.isPending}
              onSave={(cfg) => saveModelMutation.mutate(cfg)}
            />
          ) : (
            <PromptSettingsTab
              scope={scope}
              templates={templates}
              loading={loading}
              currentTemplateId={currentTemplateId}
              projectId={effectiveProjectId}
              conversationId={conversationId}
              hasOverride={hasOverride}
              applying={applyTemplateMutation.isPending}
              onApplyTemplate={(id) => applyTemplateMutation.mutate(id)}
              onSaved={notify}
              onError={reportError}
            />
          )}
        </div>
      </aside>
    </div>
  )
}
