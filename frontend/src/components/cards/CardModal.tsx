import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { cardsApi } from '@/api/cards'
import { getErrorMessage } from '@/api/client'
import { cn } from '@/lib/utils'
import { CARD_TYPES, CARD_TYPE_LABELS } from '@/lib/cardTypes'
import type { CardType, KnowledgeCard } from '@/types'

/** content_json 的键值对行 */
interface KVRow {
  key: string
  value: string
}

function objectToRows(obj: Record<string, unknown> | undefined): KVRow[] {
  if (!obj) return [{ key: '', value: '' }]
  const entries = Object.entries(obj).filter(([, v]) => v !== undefined && v !== null)
  if (!entries.length) return [{ key: '', value: '' }]
  return entries.map(([key, value]) => ({ key, value: String(value) }))
}

function rowsToObject(rows: KVRow[]): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const row of rows) {
    const key = row.key.trim()
    if (key) out[key] = row.value
  }
  return out
}

/**
 * 知识卡新建 / 编辑弹窗。
 * - 编辑模式传入 card，保存走 PATCH；否则走 POST
 * - content_json 以「键值对」形式编辑，tags 用逗号分隔输入
 */
export function CardModal({
  open,
  onClose,
  projectId,
  card,
  onSaved,
}: {
  open: boolean
  onClose: () => void
  projectId: string
  card?: KnowledgeCard | null
  onSaved?: (card: KnowledgeCard) => void
}) {
  const queryClient = useQueryClient()
  const [cardType, setCardType] = useState<CardType>('character')
  const [title, setTitle] = useState('')
  const [rows, setRows] = useState<KVRow[]>([{ key: '', value: '' }])
  const [tags, setTags] = useState('')
  const [error, setError] = useState<string | null>(null)

  // 打开时按 card（编辑）或空（新建）初始化
  useEffect(() => {
    if (open) {
      setCardType(card?.card_type ?? 'character')
      setTitle(card?.title ?? '')
      setRows(objectToRows(card?.content_json))
      setTags((card?.tags ?? []).join(', '))
      setError(null)
    }
  }, [open, card])

  const mutation = useMutation({
    mutationFn: async () => {
      const payload = {
        card_type: cardType,
        title,
        content_json: rowsToObject(rows),
        tags: tags.split(/[,，]/).map((t) => t.trim()).filter(Boolean),
      }
      return card
        ? cardsApi.update(card.id, payload)
        : cardsApi.create(projectId, payload)
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ['cards', projectId] })
      onSaved?.(saved)
      onClose()
    },
    onError: (err) => setError(getErrorMessage(err)),
  })

  if (!open) return null

  const updateRow = (i: number, patch: Partial<KVRow>) =>
    setRows((prev) => prev.map((row, idx) => (idx === i ? { ...row, ...patch } : row)))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="flex max-h-[85vh] w-full max-w-lg flex-col overflow-hidden rounded-xl bg-card shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-base font-semibold text-foreground">
            {card ? '编辑知识卡' : '新建知识卡'}
          </h2>
          <button className="text-slate-400 hover:text-foreground" onClick={onClose} aria-label="关闭">
            ✕
          </button>
        </header>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
          {/* 类型 */}
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">卡片类型</label>
            <div className="flex flex-wrap gap-2">
              {CARD_TYPES.map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setCardType(t)}
                  className={cn(
                    'rounded-md border px-2.5 py-1 text-xs font-medium transition-colors',
                    cardType === t
                      ? 'border-primary bg-primary text-primary-foreground'
                      : 'border-border text-slate-600 hover:border-primary/50',
                  )}
                >
                  {CARD_TYPE_LABELS[t]}
                </button>
              ))}
            </div>
          </div>

          {/* 标题 */}
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">标题</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="如：艾拉"
              className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:border-primary focus:outline-none"
            />
          </div>

          {/* 结构化字段（键值对） */}
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">
              结构化字段（如：性格 / 身份 / 定义）
            </label>
            <div className="space-y-2">
              {rows.map((row, i) => (
                <div key={i} className="flex items-center gap-2">
                  <input
                    value={row.key}
                    onChange={(e) => updateRow(i, { key: e.target.value })}
                    placeholder="字段名"
                    className="w-1/3 rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:border-primary focus:outline-none"
                  />
                  <input
                    value={row.value}
                    onChange={(e) => updateRow(i, { value: e.target.value })}
                    placeholder="值"
                    className="flex-1 rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:border-primary focus:outline-none"
                  />
                  <button
                    className="text-slate-400 hover:text-danger"
                    onClick={() => setRows((prev) => prev.filter((_, idx) => idx !== i))}
                    aria-label="删除字段"
                  >
                    ✕
                  </button>
                </div>
              ))}
              <button
                type="button"
                className="text-xs font-medium text-primary hover:text-primary-hover"
                onClick={() => setRows((prev) => [...prev, { key: '', value: '' }])}
              >
                + 添加字段
              </button>
            </div>
          </div>

          {/* 标签 */}
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">
              标签（逗号分隔）
            </label>
            <input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="主角, 雾都"
              className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm focus:border-primary focus:outline-none"
            />
          </div>

          {error && <p className="text-xs text-danger">{error}</p>}
        </div>

        <footer className="flex justify-end gap-2 border-t border-border px-5 py-3">
          <button
            className="rounded-md border border-border px-3 py-1.5 text-sm text-slate-600 hover:bg-background"
            onClick={onClose}
          >
            取消
          </button>
          <button
            className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
            disabled={!title.trim() || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? '保存中…' : '保存'}
          </button>
        </footer>
      </div>
    </div>
  )
}
