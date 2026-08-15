import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { getErrorMessage } from '@/api/client'
import { conversationsApi } from '@/api/conversations'
import { promptTemplatesApi } from '@/api/promptTemplates'
import { cn } from '@/lib/utils'
import type { PromptTemplate, SettingsPanelScope } from '@/types'

/** 模板可插入的占位符变量（docs/TECHv1.md §7.1） */
const VARIABLE_BUTTONS: Array<{ label: string; placeholder: string }> = [
  { label: '知识库', placeholder: '{{KNOWLEDGE_BASE}}' },
  { label: '当前章节', placeholder: '{{CURRENT_CHAPTER}}' },
  { label: '文风卡', placeholder: '{{STYLE_CARD}}' },
  { label: '用户输入', placeholder: '{{USER_INPUT}}' },
  { label: '项目信息', placeholder: '{{PROJECT_INFO}}' },
  { label: '对话历史', placeholder: '{{CONVERSATION_HISTORY}}' },
]

/** 编辑保存的作用范围（PRDv1 §2.2：仅本会话 / 保存为项目模板 / 全局模板） */
type SaveScope = 'conversation' | 'project' | 'global'

interface PromptSettingsTabProps {
  /** 面板作用范围 */
  scope: SettingsPanelScope
  /** 当前作用域可用模板（全局 + 项目，已合并） */
  templates: PromptTemplate[]
  /** 模板 / 当前配置加载中 */
  loading: boolean
  /** 当前作用域已选模板 id（会话模板 / 项目默认 / 全局默认） */
  currentTemplateId: string | null
  /** 生效项目 id（conversation 作用域为会话所属项目；全局为 null） */
  projectId: string | null
  /** 会话 id（仅 conversation 作用域需要；临时覆盖用） */
  conversationId: string | null
  /** 会话是否已使用临时覆盖（展示提示徽标） */
  hasOverride: boolean
  /** 应用模板请求进行中 */
  applying: boolean
  /** 应用模板到当前作用域（null 表示清空 / 恢复默认） */
  onApplyTemplate: (templateId: string | null) => void
  /** 成功提示 */
  onSaved: (message: string) => void
  /** 错误提示 */
  onError: (message: string) => void
}

/**
 * 「提示词设置」标签页（PRDv1 §2.2 / docs/TECHv1.md §5.7）：
 * 当前模板下拉 + 模板列表（区分全局/项目、系统标记）+ 编辑区（变量插入、作用范围）+ CRUD。
 */
export default function PromptSettingsTab({
  scope,
  templates,
  loading,
  currentTemplateId,
  projectId,
  conversationId,
  hasOverride,
  applying,
  onApplyTemplate,
  onSaved,
  onError,
}: PromptSettingsTabProps) {
  const queryClient = useQueryClient()

  // 编辑区状态
  const [editingId, setEditingId] = useState<string | null>(null) // null = 新建
  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [saveScope, setSaveScope] = useState<SaveScope>(
    scope === 'global' ? 'global' : scope === 'conversation' ? 'conversation' : 'project',
  )
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const currentLabel =
    scope === 'conversation' ? '当前会话模板' : scope === 'project' ? '项目默认模板' : '全局默认模板'

  const invalidateTemplates = () => queryClient.invalidateQueries({ queryKey: ['prompt-templates'] })

  // ===== 保存（作用范围：仅本会话 → 临时覆盖；项目/全局 → 新建或就地更新模板） =====
  const saveMutation = useMutation({
    mutationFn: async () => {
      const trimmedName = name.trim()
      if (!trimmedName) throw new Error('模板名称不能为空')
      if (!content.trim()) throw new Error('模板内容不能为空')

      if (saveScope === 'conversation') {
        if (!conversationId) throw new Error('缺少会话上下文，无法临时覆盖')
        return conversationsApi.updateConversation(conversationId, { systemPromptOverride: content })
      }
      const targetScope: SaveScope = saveScope
      if (targetScope === 'project' && !projectId) throw new Error('缺少项目上下文')
      // 就地更新：编辑的是同作用域的非系统模板；否则按所选作用域新建（系统模板编辑即另存为）
      const editing = templates.find((t) => t.id === editingId)
      const canUpdate = editing && !editing.isSystem && editing.scope === targetScope
      if (canUpdate) {
        return promptTemplatesApi.updatePromptTemplate(editing.id, { name: trimmedName, content })
      }
      return promptTemplatesApi.createPromptTemplate({
        name: trimmedName,
        content,
        scope: targetScope as 'global' | 'project',
        projectId: targetScope === 'project' ? projectId ?? undefined : undefined,
      })
    },
    onSuccess: () => {
      invalidateTemplates()
      onSaved('新设置将应用于后续消息，不影响已有消息。')
      if (saveScope !== 'conversation') setEditingId(null)
    },
    onError: (err) => onError(getErrorMessage(err)),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => promptTemplatesApi.deletePromptTemplate(id),
    onSuccess: () => invalidateTemplates(),
    onError: (err) => onError(getErrorMessage(err)),
  })

  const duplicateMutation = useMutation({
    mutationFn: (tpl: PromptTemplate) =>
      promptTemplatesApi.duplicatePromptTemplate(tpl.id, {
        newName: `${tpl.name} 副本`,
        scope: tpl.scope,
        projectId: tpl.projectId ?? undefined,
      }),
    onSuccess: () => {
      invalidateTemplates()
      onSaved('已复制模板')
    },
    onError: (err) => onError(getErrorMessage(err)),
  })

  // ===== 编辑区操作 =====
  const startNew = () => {
    setEditingId(null)
    setName('')
    setContent('')
    setSaveScope(scope === 'global' ? 'global' : 'project')
  }

  const startEdit = (tpl: PromptTemplate) => {
    setEditingId(tpl.id)
    setName(tpl.name)
    setContent(tpl.content)
    setSaveScope(tpl.scope === 'global' ? 'global' : 'project')
  }

  const handleDelete = (tpl: PromptTemplate) => {
    if (tpl.isSystem) return
    if (window.confirm(`确定删除模板「${tpl.name}」？`)) deleteMutation.mutate(tpl.id)
  }

  /** 在光标处插入变量占位符 */
  const insertVariable = (placeholder: string) => {
    const el = textareaRef.current
    if (!el) {
      setContent((c) => c + placeholder)
      return
    }
    const start = el.selectionStart ?? content.length
    const end = el.selectionEnd ?? content.length
    setContent(content.slice(0, start) + placeholder + content.slice(end))
    requestAnimationFrame(() => {
      el.focus()
      el.setSelectionRange(start + placeholder.length, start + placeholder.length)
    })
  }

  const saveScopeOptions: Array<{ value: SaveScope; label: string; disabled: boolean }> = [
    { value: 'conversation', label: '仅本会话（临时覆盖）', disabled: scope !== 'conversation' || !conversationId },
    { value: 'project', label: '保存为项目模板', disabled: !projectId },
    { value: 'global', label: '保存为全局模板', disabled: false },
  ]

  return (
    <div className="space-y-5">
      {/* 当前模板下拉 */}
      <section>
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-foreground">{currentLabel}</h3>
          {hasOverride && (
            <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
              已使用临时覆盖
            </span>
          )}
        </div>
        <div className="mt-2 flex gap-2">
          <select
            value={currentTemplateId ?? ''}
            disabled={applying || loading}
            onChange={(e) => onApplyTemplate(e.target.value || null)}
            className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:border-primary focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
          >
            <option value="">（不指定 — 回退默认）</option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}（{t.scope === 'global' ? '全局' : '项目'}
                {t.isSystem ? '·系统' : ''}）
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={applying || loading || currentTemplateId == null}
            onClick={() => onApplyTemplate(null)}
            className="shrink-0 rounded-md border border-border px-3 py-1.5 text-xs text-slate-500 hover:border-primary/40 hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
          >
            重置为默认
          </button>
        </div>
        <p className="mt-1 text-[11px] text-slate-400">选择后立即应用于{scope === 'conversation' ? '本会话后续消息' : '新建会话'}。</p>
      </section>

      {/* 模板列表 */}
      <section>
        <h3 className="text-sm font-medium text-foreground">模板列表</h3>
        <ul className="mt-2 divide-y divide-border rounded-lg border border-border">
          {loading && (
            <li className="px-3 py-4 text-center text-xs text-slate-400">加载中…</li>
          )}
          {!loading && templates.length === 0 && (
            <li className="px-3 py-4 text-center text-xs text-slate-400">暂无模板，点击下方「新建」创建</li>
          )}
          {!loading &&
            templates.map((t) => (
              <li key={t.id} className={cn('px-3 py-2', t.id === currentTemplateId && 'bg-primary/5')}>
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      'h-1.5 w-1.5 shrink-0 rounded-full',
                      t.id === currentTemplateId ? 'bg-primary' : 'bg-slate-300',
                    )}
                  />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                    {t.name}
                  </span>
                  <span
                    className={cn(
                      'rounded px-1.5 py-0.5 text-[10px] font-medium',
                      t.scope === 'global' ? 'bg-sky-100 text-sky-600' : 'bg-amber-100 text-amber-600',
                    )}
                  >
                    {t.scope === 'global' ? '全局' : '项目'}
                  </span>
                  {t.isSystem && (
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">
                      系统
                    </span>
                  )}
                </div>
                <div className="mt-1 flex items-center gap-3 pl-3.5">
                  <button
                    type="button"
                    className="text-xs text-slate-400 hover:text-primary"
                    onClick={() => startEdit(t)}
                  >
                    编辑
                  </button>
                  <button
                    type="button"
                    className="text-xs text-slate-400 hover:text-primary"
                    onClick={() => duplicateMutation.mutate(t)}
                  >
                    复制
                  </button>
                  <button
                    type="button"
                    className="text-xs text-slate-400 hover:text-danger disabled:cursor-not-allowed disabled:opacity-40"
                    disabled={t.isSystem}
                    onClick={() => handleDelete(t)}
                  >
                    删除
                  </button>
                </div>
              </li>
            ))}
        </ul>
      </section>

      {/* 编辑区 */}
      <section className="rounded-lg border border-border p-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-foreground">{editingId ? '编辑模板' : '新建模板'}</h3>
          <button type="button" className="text-xs text-slate-400 hover:text-primary" onClick={startNew}>
            ＋ 新建
          </button>
        </div>

        <label className="mt-2 block text-xs text-slate-500">
          名称
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="模板名称"
            className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:border-primary focus:outline-none"
          />
        </label>

        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-slate-500">插入变量：</span>
          {VARIABLE_BUTTONS.map((v) => (
            <button
              key={v.placeholder}
              type="button"
              onClick={() => insertVariable(v.placeholder)}
              title={v.placeholder}
              className="rounded-md border border-border px-1.5 py-0.5 text-[11px] text-slate-500 hover:border-primary/50 hover:text-primary"
            >
              {v.label}
            </button>
          ))}
        </div>

        <textarea
          ref={textareaRef}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={8}
          placeholder="输入系统提示词内容…（可插入 {{变量}}，发送请求时自动替换）"
          className="mt-2 w-full rounded-md border border-border bg-background px-2 py-1.5 font-mono text-xs leading-relaxed focus:border-primary focus:outline-none"
        />

        <div className="mt-3">
          <span className="text-xs text-slate-500">保存为：</span>
          <div className="mt-1 space-y-1.5">
            {saveScopeOptions.map((opt) => (
              <label
                key={opt.value}
                className={cn(
                  'flex cursor-pointer items-center gap-2 text-xs text-slate-600',
                  opt.disabled && 'cursor-not-allowed opacity-40',
                )}
              >
                <input
                  type="radio"
                  name="save-scope"
                  checked={saveScope === opt.value}
                  disabled={opt.disabled}
                  onChange={() => setSaveScope(opt.value)}
                  className="h-3.5 w-3.5 accent-primary"
                />
                {opt.label}
              </label>
            ))}
          </div>
          {saveScope === 'conversation' && (
            <p className="mt-1.5 text-[11px] text-amber-600">仅本会话生效的临时覆盖，不影响原模板。</p>
          )}
        </div>

        <div className="mt-3 flex justify-end gap-2">
          <button
            type="button"
            onClick={startNew}
            className="rounded-md border border-border px-3 py-1.5 text-xs text-slate-500 hover:border-primary/40 hover:text-primary"
          >
            新建
          </button>
          <button
            type="button"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending || !name.trim() || !content.trim()}
            className="rounded-md bg-primary px-4 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saveMutation.isPending ? '保存中…' : '保存'}
          </button>
        </div>
      </section>
    </div>
  )
}
