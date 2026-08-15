import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { projectsApi } from '@/api'
import { cardsApi } from '@/api/cards'
import { generationUrls, toModelConfigWire } from '@/api/generations'
import { promptTemplatesApi } from '@/api/promptTemplates'
import { settingsApi } from '@/api/settings'
import { streamSSE, type SSEEvent } from '@/lib/sse'
import { CARD_TYPE_LABELS } from '@/lib/cardTypes'
import { cn } from '@/lib/utils'
import type { CardType, DepthLevel } from '@/types'

/** 生成进行状态 */
type StreamStatus = 'idle' | 'streaming' | 'done' | 'error'

/** 流式结果：候选列表 + 状态 */
interface StreamState {
  status: StreamStatus
  candidates: string[]
  message?: string
}

const VIEW_OPTIONS = ['第一人称', '第三人称', '第三人称限知', '不限']

const TYPE_FILTERS: Array<CardType | 'all'> = ['all', 'character', 'world', 'term', 'style', 'event']

/** 六档思维深度选项（docs/TECHv1.md §8.1，与全局设置面板一致） */
const DEPTH_OPTIONS: Array<{ value: DepthLevel; label: string }> = [
  { value: 'none', label: '无' },
  { value: 'auto', label: '自动' },
  { value: 'low', label: '低' },
  { value: 'medium', label: '中等' },
  { value: 'high', label: '高' },
  { value: 'extreme', label: '极高' },
]

const DEPTH_VALUES: DepthLevel[] = ['none', 'auto', 'low', 'medium', 'high', 'extreme']

function isDepth(value: unknown): value is DepthLevel {
  return typeof value === 'string' && (DEPTH_VALUES as string[]).includes(value)
}

function toNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

/** 模型/提示词临时设置的兜底值（无项目/全局配置时使用，与全局设置面板 DEFAULT_CONFIG 一致） */
const FALLBACK_CONFIG = { depth: 'auto', temperature: 0.7, maxTokens: 2048 } as const

/**
 * AI 生成面板（右侧栏）：
 * - 知识卡选择器（按类型筛选 + 勾选）
 * - 续写：取章节末尾文本流式生成多候选
 * - 重写：对编辑器选中的文本流式生成多候选
 * - 候选文本以标签页展示，支持「使用」回填编辑器
 */
export function GenerationPanel({
  projectId,
  chapterId,
  content,
  selectedText,
  onInsert,
}: {
  projectId: string
  chapterId: string
  content: string
  selectedText: string
  onInsert: (text: string) => void
}) {
  // 知识卡
  const { data: cards = [] } = useQuery({
    queryKey: ['cards', projectId],
    queryFn: () => cardsApi.list(projectId),
  })

  // 生成参数
  const [typeFilter, setTypeFilter] = useState<CardType | 'all'>('all')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [targetWords, setTargetWords] = useState(500)
  const [view, setView] = useState('')
  const [prompt, setPrompt] = useState('')
  const [instruction, setInstruction] = useState('')
  const [styleCardId, setStyleCardId] = useState('')

  // 本次生成的模型/提示词临时设置（初始为项目/全局默认；用户改动仅本次生效，不保存为项目默认）
  const [depth, setDepth] = useState<DepthLevel>('auto')
  const [temperature, setTemperature] = useState<number>(FALLBACK_CONFIG.temperature)
  const [maxTokens, setMaxTokens] = useState<number>(FALLBACK_CONFIG.maxTokens)
  const [templateId, setTemplateId] = useState('')
  const [touched, setTouched] = useState(false)

  // 流式状态
  const [stream, setStream] = useState<StreamState>({ status: 'idle', candidates: [] })
  const [activeTab, setActiveTab] = useState(1)
  const abortRef = useRef<AbortController | null>(null)

  // 卸载时中止未完成的流
  useEffect(() => () => abortRef.current?.abort(), [])

  // 项目/全局默认模型配置与提示词模板（用于填充临时设置，docs/TECHv1.md §5.5 / §7.1）
  const { data: project } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => projectsApi.get(projectId),
    enabled: !!projectId,
  })
  const { data: appSettings } = useQuery({
    queryKey: ['settings-app'],
    queryFn: settingsApi.getAppSettings,
  })
  const { data: globalTemplates = [] } = useQuery({
    queryKey: ['prompt-templates', { scope: 'global' }],
    queryFn: () => promptTemplatesApi.listPromptTemplates('global'),
  })
  const { data: projectTemplates = [] } = useQuery({
    queryKey: ['prompt-templates', { scope: 'project', projectId }],
    queryFn: () => promptTemplatesApi.listPromptTemplates('project', projectId),
  })
  const templates = useMemo(() => [...globalTemplates, ...projectTemplates], [globalTemplates, projectTemplates])

  // 有效默认配置：项目默认 > 全局默认（与后端 services/generation.py resolve_model_config 一致）
  const effectiveConfig = useMemo(() => {
    const projectCfg = project?.default_model_config
    if (projectCfg && Object.keys(projectCfg).length) return projectCfg
    const globalCfg = appSettings?.global_default_model_config
    if (globalCfg && Object.keys(globalCfg).length) return globalCfg
    return null
  }, [project, appSettings])

  const cfgDepth = effectiveConfig?.depth
  const defaultDepth: DepthLevel = isDepth(cfgDepth) ? cfgDepth : FALLBACK_CONFIG.depth
  const defaultTemperature = toNumber(effectiveConfig?.temperature, FALLBACK_CONFIG.temperature)
  const defaultMaxTokens = toNumber(
    effectiveConfig?.max_tokens ?? effectiveConfig?.maxTokens,
    FALLBACK_CONFIG.maxTokens,
  )
  const globalTemplateId = appSettings?.global_default_prompt_template_id?.trim()
  const defaultTemplateId = project?.default_prompt_template_id ?? (globalTemplateId ? globalTemplateId : null)

  // 默认值就绪时填充控件；用户已改动（touched）则不覆盖
  useEffect(() => {
    if (touched) return
    setDepth(defaultDepth)
    setTemperature(defaultTemperature)
    setMaxTokens(defaultMaxTokens)
    setTemplateId(defaultTemplateId ?? '')
  }, [touched, defaultDepth, defaultTemperature, defaultMaxTokens, defaultTemplateId])

  // 切换章节：重置临时覆盖为默认值（临时设置仅本次会话生效）
  useEffect(() => {
    setTouched(false)
    setDepth(defaultDepth)
    setTemperature(defaultTemperature)
    setMaxTokens(defaultMaxTokens)
    setTemplateId(defaultTemplateId ?? '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapterId])

  const styleCards = cards.filter((c) => c.card_type === 'style')
  const visibleCards = typeFilter === 'all' ? cards : cards.filter((c) => c.card_type === typeFilter)

  const toggleCard = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const resetStream = () => {
    abortRef.current?.abort()
    setStream({ status: 'idle', candidates: [] })
    setActiveTab(1)
  }

  const handleEvent = (ev: SSEEvent) => {
    if (ev.event === 'delta') {
      const { index, text } = JSON.parse(ev.data) as { index: number; text: string }
      setStream((prev) => {
        const cands = [...prev.candidates]
        while (cands.length < index) cands.push('')
        cands[index - 1] = (cands[index - 1] ?? '') + text
        return { ...prev, status: 'streaming', candidates: cands }
      })
    } else if (ev.event === 'done') {
      const { candidates } = JSON.parse(ev.data) as { candidates: string[] }
      setStream({ status: 'done', candidates })
    } else if (ev.event === 'error') {
      const { message } = JSON.parse(ev.data) as { message: string }
      setStream((prev) => ({ ...prev, status: 'error', message }))
    }
  }

  const run = async (type: 'continue' | 'rewrite') => {
    if (stream.status === 'streaming') return
    resetStream()
    const controller = new AbortController()
    abortRef.current = controller
    const base = {
      card_ids: [...selected],
      target_words: targetWords,
      temperature,
      candidate_count: 3,
    }
    // V1：本次生成的模型配置与系统提示词模板（docs/TECHv1.md §5.5）
    const modelConfigWire = toModelConfigWire({ depth, temperature, maxTokens })
    const templateField = templateId ? { system_prompt_template_id: templateId } : {}
    const body = type === 'continue'
      ? { ...base, prompt: prompt || undefined, view: view || undefined, model_config: modelConfigWire, ...templateField }
      : {
          ...base,
          selected_text: selectedText,
          instruction: instruction || undefined,
          style_card_id: styleCardId || undefined,
          model_config: modelConfigWire,
          ...templateField,
        }
    const url = type === 'continue'
      ? generationUrls.continue(chapterId)
      : generationUrls.rewrite(chapterId)
    try {
      await streamSSE(url, body, handleEvent, controller.signal)
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setStream((prev) => ({
          ...prev,
          status: 'error',
          message: err instanceof Error ? err.message : String(err),
        }))
      }
    }
  }

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4">
      {/* 知识卡选择器 */}
      <section className="rounded-xl border border-border bg-card p-3">
        <header className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-foreground">知识卡</h3>
          <span className="text-xs text-slate-400">已选 {selected.size}</span>
        </header>
        <div className="mb-2 flex flex-wrap gap-1">
          {TYPE_FILTERS.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTypeFilter(t)}
              className={cn(
                'rounded px-2 py-0.5 text-xs transition-colors',
                typeFilter === t
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-background text-slate-500 hover:text-foreground',
              )}
            >
              {t === 'all' ? '全部' : CARD_TYPE_LABELS[t]}
            </button>
          ))}
        </div>
        <div className="max-h-48 space-y-1 overflow-y-auto pr-1">
          {visibleCards.length === 0 && (
            <p className="py-2 text-center text-xs text-slate-400">暂无卡片</p>
          )}
          {visibleCards.map((card) => (
            <label key={card.id} className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 hover:bg-background">
              <input
                type="checkbox"
                checked={selected.has(card.id)}
                onChange={() => toggleCard(card.id)}
                className="h-3.5 w-3.5 accent-primary"
              />
              <span className="truncate text-xs text-slate-700">{card.title}</span>
              <span className="ml-auto shrink-0 text-[10px] text-slate-400">
                {CARD_TYPE_LABELS[card.card_type]}
              </span>
            </label>
          ))}
        </div>
      </section>

      {/* 生成参数 */}
      <section className="space-y-3 rounded-xl border border-border bg-card p-3">
        <h3 className="text-sm font-semibold text-foreground">生成设置</h3>

        <div className="grid grid-cols-2 gap-2">
          <label className="text-xs text-slate-500">
            目标字数
            <input
              type="number"
              min={50}
              max={5000}
              value={targetWords}
              onChange={(e) => setTargetWords(Number(e.target.value) || 500)}
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1 text-sm focus:border-primary focus:outline-none"
            />
          </label>
          <label className="text-xs text-slate-500">
            最大输出长度
            <input
              type="number"
              min={1}
              step={1}
              value={maxTokens}
              onChange={(e) => {
                const v = Number(e.target.value)
                if (Number.isNaN(v)) return
                setMaxTokens(Math.max(1, Math.floor(v)))
                setTouched(true)
              }}
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1 text-sm focus:border-primary focus:outline-none"
            />
          </label>
        </div>

        {/* 模型/提示词：本次生成临时设置（docs/TECHv1.md §5.5） */}
        <div className="space-y-3 rounded-lg border border-dashed border-border/60 bg-background/50 p-2.5">
          <p className="text-[11px] leading-relaxed text-slate-400">
            以下设置初始为项目/全局默认，临时修改仅用于本次生成，不保存为项目默认。
          </p>
          <label className="block text-xs text-slate-500">
            思维深度
            <select
              value={depth}
              onChange={(e) => {
                setDepth(e.target.value as DepthLevel)
                setTouched(true)
              }}
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1 text-sm focus:border-primary focus:outline-none"
            >
              {DEPTH_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </label>
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-500">随机性（创意性）</span>
              <span className="font-mono text-xs text-slate-500">{temperature.toFixed(1)}</span>
            </div>
            <input
              type="range"
              min={0}
              max={2}
              step={0.1}
              value={temperature}
              onChange={(e) => {
                setTemperature(Number(e.target.value))
                setTouched(true)
              }}
              className="mt-1 w-full accent-primary"
            />
            <div className="flex justify-between text-[10px] text-slate-400">
              <span>0 · 精确稳定</span>
              <span>2 · 发散创意</span>
            </div>
          </div>
          <label className="block text-xs text-slate-500">
            系统提示词模板
            <select
              value={templateId}
              onChange={(e) => {
                setTemplateId(e.target.value)
                setTouched(true)
              }}
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1 text-sm focus:border-primary focus:outline-none"
            >
              <option value="">（不指定 — 跟随项目/全局默认）</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}（{t.scope === 'global' ? '全局' : '项目'}
                  {t.isSystem ? '·系统' : ''}）
                </option>
              ))}
            </select>
          </label>
        </div>

        {styleCards.length > 0 && (
          <label className="block text-xs text-slate-500">
            文风卡
            <select
              value={styleCardId}
              onChange={(e) => setStyleCardId(e.target.value)}
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1 text-sm focus:border-primary focus:outline-none"
            >
              <option value="">（自动选择）</option>
              {styleCards.map((c) => (
                <option key={c.id} value={c.id}>{c.title}</option>
              ))}
            </select>
          </label>
        )}

        <label className="block text-xs text-slate-500">
          叙事视角（续写）
          <select
            value={view}
            onChange={(e) => setView(e.target.value)}
            className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1 text-sm focus:border-primary focus:outline-none"
          >
            <option value="">（维持一致）</option>
            {VIEW_OPTIONS.map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        </label>

        <label className="block text-xs text-slate-500">
          续写要求
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="可选：节奏、悬念等额外要求"
            rows={2}
            className="mt-1 w-full resize-none rounded-md border border-border bg-background px-2 py-1 text-sm focus:border-primary focus:outline-none"
          />
        </label>

        <label className="block text-xs text-slate-500">
          重写指令
          <textarea
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder="可选：更有张力、更简洁等"
            rows={2}
            className="mt-1 w-full resize-none rounded-md border border-border bg-background px-2 py-1 text-sm focus:border-primary focus:outline-none"
          />
        </label>

        {/* 操作按钮 */}
        <div className="flex gap-2 pt-1">
          <button
            className="flex-1 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
            disabled={stream.status === 'streaming' || !content.trim()}
            onClick={() => run('continue')}
          >
            续写
          </button>
          <button
            className="flex-1 rounded-md border border-primary px-3 py-2 text-sm font-medium text-primary hover:bg-primary/5 disabled:opacity-50"
            disabled={stream.status === 'streaming' || !selectedText.trim()}
            onClick={() => run('rewrite')}
            title={selectedText.trim() ? undefined : '请在编辑器中选择文本'}
          >
            重写选中
          </button>
        </div>
      </section>

      {/* 生成结果 */}
      {stream.status !== 'idle' && (
        <section className="flex min-h-0 flex-1 flex-col rounded-xl border border-border bg-card">
          <header className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-sm font-semibold text-foreground">
              {stream.status === 'streaming' && '生成中…'}
              {stream.status === 'done' && `候选（${stream.candidates.length}）`}
              {stream.status === 'error' && '生成失败'}
            </span>
            {stream.status === 'streaming' && (
              <button
                className="text-xs font-medium text-slate-500 hover:text-danger"
                onClick={() => abortRef.current?.abort()}
              >
                停止
              </button>
            )}
          </header>

          {stream.status === 'error' ? (
            <p className="p-3 text-sm text-danger">{stream.message}</p>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col">
              {/* 候选标签页 */}
              <div className="flex shrink-0 gap-1 border-b border-border px-3 py-1.5">
                {stream.candidates.map((_, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => setActiveTab(i + 1)}
                    className={cn(
                      'rounded px-2 py-0.5 text-xs font-medium',
                      activeTab === i + 1
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-background text-slate-500 hover:text-foreground',
                    )}
                  >
                    候选 {i + 1}
                  </button>
                ))}
              </div>
              {/* 候选正文 */}
              <div className="min-h-0 flex-1 overflow-y-auto p-3">
                <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
                  {stream.candidates[activeTab - 1] || (stream.status === 'streaming' ? '正在生成…' : '（空）')}
                </div>
              </div>
              {stream.status === 'done' && stream.candidates[activeTab - 1] && (
                <footer className="shrink-0 border-t border-border p-2">
                  <button
                    className="w-full rounded-md bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/20"
                    onClick={() => onInsert(stream.candidates[activeTab - 1])}
                  >
                    使用此候选
                  </button>
                </footer>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  )
}
