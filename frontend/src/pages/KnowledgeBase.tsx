import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { cardsApi } from '@/api/cards'
import { getErrorMessage } from '@/api/client'
import { CardModal } from '@/components/cards/CardModal'
import { CARD_TYPE_LABELS } from '@/lib/cardTypes'
import { cn } from '@/lib/utils'
import type { CardType, KnowledgeCard } from '@/types'

const TYPE_TABS: Array<CardType | 'all'> = ['all', 'character', 'world', 'term', 'style', 'event']

/** 内容摘要：键值对文本，超长截断 */
function contentPreview(card: KnowledgeCard): string {
  const entries = Object.entries(card.content_json ?? {})
  if (!entries.length) return '（无结构化字段）'
  return entries.map(([k, v]) => `${k}：${String(v)}`).join('；')
}

/**
 * 知识库页（项目内 /knowledge 或全局 /knowledge）。
 * 展示全部知识卡，支持按类型筛选、搜索、新建 / 编辑 / 删除。
 */
export default function KnowledgeBase() {
  const { projectId } = useParams<{ projectId: string }>()
  const queryClient = useQueryClient()

  const [typeFilter, setTypeFilter] = useState<CardType | 'all'>('all')
  const [q, setQ] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<KnowledgeCard | null>(null)
  const [error, setError] = useState<string | null>(null)

  const { data: cards = [], isLoading } = useQuery({
    queryKey: ['cards', projectId, typeFilter, q],
    queryFn: () =>
      cardsApi.list(projectId!, {
        card_type: typeFilter === 'all' ? undefined : typeFilter,
        q: q || undefined,
      }),
    enabled: !!projectId,
  })

  const removeMutation = useMutation({
    mutationFn: (cardId: string) => cardsApi.remove(cardId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cards', projectId] })
      setError(null)
    },
    onError: (err) => setError(getErrorMessage(err)),
  })

  // 全局 /knowledge 入口没有项目上下文
  if (!projectId) {
    return (
      <div className="flex min-h-full flex-col items-center justify-center gap-3 p-8">
        <p className="text-sm text-slate-500">知识库需要先选择一个项目</p>
        <Link to="/" className="text-sm font-medium text-primary hover:text-primary-hover">
          → 去项目列表选择
        </Link>
      </div>
    )
  }

  const handleDelete = (card: KnowledgeCard) => {
    if (window.confirm(`确定删除知识卡「${card.title}」？`)) removeMutation.mutate(card.id)
  }

  return (
    <div className="min-h-full space-y-5 bg-background px-6 py-6">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-foreground">知识库</h1>
          <p className="mt-1 text-sm text-slate-500">管理角色、世界观、术语、文风与事件设定卡</p>
        </div>
        <button
          className="shrink-0 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover"
          onClick={() => {
            setEditing(null)
            setModalOpen(true)
          }}
        >
          + 新建卡片
        </button>
      </header>

      {/* 筛选 */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1 rounded-lg bg-card p-1">
          {TYPE_TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              className={cn(
                'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                typeFilter === t
                  ? 'bg-primary text-primary-foreground'
                  : 'text-slate-500 hover:text-foreground',
              )}
            >
              {t === 'all' ? '全部' : CARD_TYPE_LABELS[t]}
            </button>
          ))}
        </div>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="搜索标题…"
          className="ml-auto w-48 rounded-md border border-border bg-card px-3 py-1.5 text-sm focus:border-primary focus:outline-none"
        />
      </div>

      {error && <p className="text-sm text-danger">{error}</p>}
      {isLoading && <p className="text-sm text-slate-400">加载中…</p>}

      {!isLoading && cards.length === 0 && (
        <div className="flex h-40 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-card/50">
          <p className="text-sm text-slate-500">暂无卡片</p>
          <p className="text-xs text-slate-400">可在「文档」页解析导入，或手动新建</p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {cards.map((card) => (
          <div key={card.id} className="flex flex-col rounded-xl border border-border bg-card p-4">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <h3 className="truncate text-base font-semibold text-foreground">{card.title}</h3>
                <span className="mt-1 inline-block rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">
                  {CARD_TYPE_LABELS[card.card_type]}
                </span>
              </div>
              <div className="flex shrink-0 gap-1">
                <button
                  className="rounded px-1.5 py-0.5 text-xs text-slate-400 hover:text-primary"
                  onClick={() => {
                    setEditing(card)
                    setModalOpen(true)
                  }}
                >
                  编辑
                </button>
                <button
                  className="rounded px-1.5 py-0.5 text-xs text-slate-400 hover:text-danger"
                  onClick={() => handleDelete(card)}
                >
                  删除
                </button>
              </div>
            </div>
            <p className="mt-2 line-clamp-4 flex-1 text-sm text-slate-600">{contentPreview(card)}</p>
            {card.tags.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {card.tags.map((tag) => (
                  <span key={tag} className="rounded bg-background px-1.5 py-0.5 text-[10px] text-slate-500">
                    #{tag}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <CardModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        projectId={projectId}
        card={editing}
        onSaved={() => {
          setModalOpen(false)
          setEditing(null)
        }}
      />
    </div>
  )
}
