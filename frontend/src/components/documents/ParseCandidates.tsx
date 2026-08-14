import { useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { documentsApi, type SnippetChunk } from '@/api/documents'
import { getErrorMessage } from '@/api/client'
import { CARD_TYPE_LABELS } from '@/lib/cardTypes'
import { cn } from '@/lib/utils'
import type { CandidateCard } from '@/types'

/** 提取文本中的 CJK 连续段，用于片段关键词匹配 */
function cjkTokens(text: string): string[] {
  const runs = text.match(/[一-鿿]+/g) ?? []
  const tokens: string[] = []
  for (const run of runs) {
    if (run.length >= 2) tokens.push(run)
    if (run.length >= 4) {
      tokens.push(run.slice(0, 2))
      tokens.push(run.slice(-2))
    }
  }
  return tokens
}

/** 为候选卡片匹配原文片段：按标题/字段关键词命中；无命中则回退为全部分块 */
function matchSnippets(card: CandidateCard, chunks: SnippetChunk[]): string[] {
  if (!chunks.length) return []
  const hay = [card.title, ...Object.values(card.content_json ?? {}).map(String)]
  const uniq = [...new Set(hay.flatMap(cjkTokens).filter((t) => t.length >= 2))]
  if (!uniq.length) return chunks.map((c) => c.id)
  const matched = chunks.filter((c) => uniq.some((t) => c.text.includes(t))).map((c) => c.id)
  return matched.length ? matched : chunks.map((c) => c.id)
}

/**
 * 解析候选卡片确认区：勾选卡片 → 自动匹配片段 → 导入知识库。
 * 导入后通过 onImported 通知父组件刷新文档列表。
 */
export function ParseCandidates({
  projectId,
  documentId,
  candidates,
  chunks,
  onImported,
}: {
  projectId: string
  documentId: string
  candidates: CandidateCard[]
  chunks: SnippetChunk[]
  onImported: () => void
}) {
  const queryClient = useQueryClient()
  // 默认全选；用候选索引作为勾选 key（candidates 每次解析后固定）
  const [checked, setChecked] = useState<Set<number>>(new Set(candidates.map((_, i) => i)))
  const [error, setError] = useState<string | null>(null)

  const snippetCounts = useMemo(
    () => candidates.map((c) => matchSnippets(c, chunks).length),
    [candidates, chunks],
  )

  const mutation = useMutation({
    mutationFn: async () => {
      const cards = candidates
        .filter((_, i) => checked.has(i))
        .map((c) => ({ ...c, snippet_ids: matchSnippets(c, chunks) }))
      if (!cards.length) throw new Error('请至少勾选一张卡片')
      return documentsApi.confirmImport(documentId, { cards })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', projectId] })
      onImported()
    },
    onError: (err) => setError(getErrorMessage(err)),
  })

  const toggle = (i: number) =>
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <header className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">解析候选卡片（{candidates.length}）</h3>
        <div className="flex items-center gap-3">
          <button
            type="button"
            className="text-xs font-medium text-primary hover:text-primary-hover"
            onClick={() => setChecked(new Set(candidates.map((_, i) => i)))}
          >
            全选
          </button>
          <button
            type="button"
            className="text-xs font-medium text-slate-500 hover:text-foreground"
            onClick={() => setChecked(new Set())}
          >
            清空
          </button>
        </div>
      </header>

      <div className="max-h-72 space-y-2 overflow-y-auto">
        {candidates.map((card, i) => (
          <label
            key={i}
            className={cn(
              'flex cursor-pointer items-start gap-3 rounded-lg border border-border p-3 transition-colors',
              checked.has(i) ? 'border-primary/60 bg-primary/5' : 'hover:bg-background',
            )}
          >
            <input
              type="checkbox"
              checked={checked.has(i)}
              onChange={() => toggle(i)}
              className="mt-1 h-4 w-4 accent-primary"
            />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">
                  {CARD_TYPE_LABELS[card.card_type]}
                </span>
                <span className="truncate text-sm font-medium text-foreground">{card.title}</span>
              </div>
              {Object.entries(card.content_json ?? {}).length > 0 && (
                <p className="mt-1 line-clamp-2 text-xs text-slate-500">
                  {Object.entries(card.content_json!)
                    .map(([k, v]) => `${k}：${String(v)}`)
                    .join('；')}
                </p>
              )}
            </div>
            <span className="shrink-0 text-xs text-slate-400">
              {snippetCounts[i]} 片段
            </span>
          </label>
        ))}
      </div>

      {error && <p className="mt-2 text-xs text-danger">{error}</p>}

      <footer className="mt-3 flex justify-end">
        <button
          className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
          disabled={mutation.isPending || checked.size === 0}
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending ? '导入中…' : `导入勾选的 ${checked.size} 张卡片`}
        </button>
      </footer>
    </div>
  )
}
