import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { chaptersApi } from '@/api/chapters'
import { getErrorMessage } from '@/api/client'
import { cn } from '@/lib/utils'
import type { ChapterVersion } from '@/types'

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', { hour12: false })
}

/** 备注 → 展示样式 */
function noteBadge(note: string): { label: string; className: string } {
  if (note === '自动快照') return { label: '自动', className: 'bg-slate-100 text-slate-600' }
  if (note === '回滚前快照') return { label: '回滚前', className: 'bg-amber-100 text-amber-700' }
  return { label: note || '手动', className: 'bg-primary/10 text-primary' }
}

/**
 * 章节历史版本弹窗：
 * - 手动保存当前内容为快照
 * - 查看版本列表（时间 / 备注 / 内容预览）
 * - 回滚到指定版本（回滚后通过 onRolledBack 通知编辑器刷新正文）
 */
export function ChapterVersionsModal({
  open,
  onClose,
  chapterId,
  currentContent,
  onRolledBack,
}: {
  open: boolean
  onClose: () => void
  chapterId: string
  currentContent: string
  onRolledBack: (content: string) => void
}) {
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)

  const { data: versions = [], isLoading } = useQuery({
    queryKey: ['chapter-versions', chapterId],
    queryFn: () => chaptersApi.versions(chapterId),
    enabled: open && !!chapterId,
  })

  const snapshotMutation = useMutation({
    mutationFn: () =>
      chaptersApi.createVersion(chapterId, { content: currentContent, note: '手动快照' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chapter-versions', chapterId] })
      setError(null)
    },
    onError: (err) => setError(getErrorMessage(err)),
  })

  const rollbackMutation = useMutation({
    mutationFn: (versionId: string) => chaptersApi.rollback(chapterId, versionId),
    onSuccess: (chapter) => {
      queryClient.invalidateQueries({ queryKey: ['chapter-versions', chapterId] })
      onRolledBack(chapter.content)
      setError(null)
    },
    onError: (err) => setError(getErrorMessage(err)),
  })

  if (!open) return null

  const handleRollback = (version: ChapterVersion) => {
    if (window.confirm('回滚将用该版本覆盖当前正文，且会保留一个「回滚前快照」用于撤销，确定继续？')) {
      rollbackMutation.mutate(version.id)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="flex max-h-[80vh] w-full max-w-lg flex-col overflow-hidden rounded-xl bg-card shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 className="text-base font-semibold text-foreground">历史版本</h2>
          <button className="text-slate-400 hover:text-foreground" onClick={onClose} aria-label="关闭">
            ✕
          </button>
        </header>

        <div className="flex items-center justify-between border-b border-border px-5 py-2.5">
          <p className="text-xs text-slate-400">共 {versions.length} 条版本</p>
          <button
            className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
            disabled={snapshotMutation.isPending || !currentContent.trim()}
            onClick={() => snapshotMutation.mutate()}
          >
            {snapshotMutation.isPending ? '保存中…' : '将当前内容存为版本'}
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {isLoading && <p className="p-3 text-center text-sm text-slate-400">加载中…</p>}
          {!isLoading && versions.length === 0 && (
            <p className="p-3 text-center text-sm text-slate-400">
              暂无版本。保存章节会自动生成快照，也可手动保存。
            </p>
          )}
          <div className="space-y-2">
            {versions.map((version) => {
              const badge = noteBadge(version.note)
              return (
                <div key={version.id} className="rounded-lg border border-border p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-medium', badge.className)}>
                        {badge.label}
                      </span>
                      <span className="text-xs text-slate-500">{formatTime(version.created_at)}</span>
                    </div>
                    <button
                      className="rounded-md border border-primary px-2.5 py-0.5 text-xs font-medium text-primary hover:bg-primary/5 disabled:opacity-50"
                      disabled={rollbackMutation.isPending}
                      onClick={() => handleRollback(version)}
                    >
                      回滚
                    </button>
                  </div>
                  <p className="mt-1.5 line-clamp-3 whitespace-pre-wrap text-xs text-slate-600">
                    {version.content || '（空）'}
                  </p>
                </div>
              )
            })}
          </div>
        </div>

        {error && <p className="border-t border-border px-5 py-2 text-xs text-danger">{error}</p>}
      </div>
    </div>
  )
}
