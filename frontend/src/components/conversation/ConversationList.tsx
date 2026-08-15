import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getErrorMessage } from '@/api/client'
import { conversationsApi } from '@/api/conversations'
import { cn } from '@/lib/utils'
import type { Conversation } from '@/types'

interface ConversationListProps {
  projectId: string
  /** 当前选中对话 id（高亮） */
  currentId: string | null
  /** 选中 / 取消选中（删除当前对话时传 null） */
  onSelect: (id: string | null) => void
}

/** 相对时间：今天显示 HH:mm，否则 MM-DD */
function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  if (d.toDateString() === new Date().toDateString()) return `${pad(d.getHours())}:${pad(d.getMinutes())}`
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/**
 * 对话列表（左侧栏）：项目下所有对话 + 新建（内联标题输入）/ 删除。
 */
export default function ConversationList({ projectId, currentId, onSelect }: ConversationListProps) {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [error, setError] = useState<string | null>(null)
  const titleInputRef = useRef<HTMLInputElement>(null)

  const { data: conversations = [], isLoading } = useQuery({
    queryKey: ['conversations', projectId],
    queryFn: () => conversationsApi.listConversations(projectId),
  })

  useEffect(() => {
    if (creating) titleInputRef.current?.focus()
  }, [creating])

  const createMutation = useMutation({
    mutationFn: (title: string) => conversationsApi.createConversation(projectId, { title }),
    onSuccess: (conv: Conversation) => {
      queryClient.invalidateQueries({ queryKey: ['conversations', projectId] })
      setCreating(false)
      setNewTitle('')
      onSelect(conv.id)
    },
    onError: (err) => setError(getErrorMessage(err)),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => conversationsApi.deleteConversation(id),
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: ['conversations', projectId] })
      if (id === currentId) onSelect(null)
    },
    onError: (err) => setError(getErrorMessage(err)),
  })

  const handleCreate = () => {
    const title = newTitle.trim() || '新对话'
    createMutation.mutate(title)
  }

  const handleDelete = (c: Conversation) => {
    if (window.confirm(`确定删除对话「${c.title}」？其消息将一并删除。`)) deleteMutation.mutate(c.id)
  }

  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-card">
      <header className="flex items-center justify-between px-3 py-2.5">
        <h2 className="text-sm font-semibold text-foreground">对话</h2>
        <button
          type="button"
          onClick={() => {
            setCreating(true)
            setError(null)
          }}
          className="rounded-md px-2 py-1 text-xs font-medium text-primary hover:bg-primary/10"
        >
          ＋ 新建
        </button>
      </header>

      {error && <p className="mx-3 mb-2 rounded-md bg-danger/5 px-2 py-1.5 text-xs text-danger">{error}</p>}

      {creating && (
        <div className="mx-3 mb-2 flex gap-1.5">
          <input
            ref={titleInputRef}
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleCreate()
              if (e.key === 'Escape') setCreating(false)
            }}
            placeholder="对话标题（可留空）"
            className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-xs focus:border-primary focus:outline-none"
          />
          <button
            type="button"
            onClick={handleCreate}
            disabled={createMutation.isPending}
            className="shrink-0 rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
          >
            创建
          </button>
        </div>
      )}

      <ul className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {isLoading && <li className="px-2 py-3 text-center text-xs text-slate-400">加载中…</li>}
        {!isLoading && conversations.length === 0 && (
          <li className="px-2 py-3 text-center text-xs text-slate-400">暂无对话，点击「＋ 新建」开始</li>
        )}
        {conversations.map((c) => {
          const active = c.id === currentId
          return (
            <li key={c.id}>
              <div
                role="button"
                tabIndex={0}
                onClick={() => onSelect(c.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') onSelect(c.id)
                }}
                className={cn(
                  'group flex cursor-pointer items-center gap-1 rounded-lg px-2 py-1.5 transition-colors',
                  active ? 'bg-primary/10' : 'hover:bg-background',
                )}
              >
                <span
                  className={cn(
                    'min-w-0 flex-1 truncate text-sm',
                    active ? 'font-medium text-primary' : 'text-slate-600',
                  )}
                >
                  {c.title}
                </span>
                <span className="shrink-0 text-[10px] text-slate-400">{formatTime(c.updatedAt)}</span>
                <button
                  type="button"
                  title="删除对话"
                  onClick={(e) => {
                    e.stopPropagation()
                    handleDelete(c)
                  }}
                  className="shrink-0 rounded p-1 text-xs text-slate-300 opacity-0 transition-opacity group-hover:opacity-100 hover:text-danger"
                >
                  🗑
                </button>
              </div>
            </li>
          )
        })}
      </ul>
    </aside>
  )
}
