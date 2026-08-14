import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { chaptersApi } from '@/api/chapters'
import { getErrorMessage } from '@/api/client'
import { MarkdownEditor } from '@/components/editor/MarkdownEditor'
import { GenerationPanel } from '@/components/editor/GenerationPanel'
import { ChapterVersionsModal } from '@/components/editor/ChapterVersionsModal'
import { cn } from '@/lib/utils'
import type { Chapter } from '@/types'

/** 本地字数统计（CJK 每字计 1，英文/数字按词计） */
function countWords(text: string): number {
  const cjk = text.match(/[一-鿿㐀-䶿]/g) ?? []
  const words = text.match(/[A-Za-z0-9]+/g) ?? []
  return cjk.length + words.length
}

/**
 * 章节编辑器页（三栏布局）：
 * - 左：章节列表（新建 / 切换）
 * - 中：Markdown 编辑器（标题 + 正文 + 保存）
 * - 右：AI 生成面板（知识卡选择 + 续写 / 重写 + 流式结果）
 */
export default function ChapterEditor() {
  const { projectId } = useParams<{ projectId: string }>()
  const queryClient = useQueryClient()

  const { data: chapters = [], isLoading } = useQuery({
    queryKey: ['chapters', projectId],
    queryFn: () => chaptersApi.list(projectId!),
    enabled: !!projectId,
  })

  const [activeId, setActiveId] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [selectedText, setSelectedText] = useState('')
  const [dirty, setDirty] = useState(false)
  const [versionsOpen, setVersionsOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const selectChapter = (chapter: Chapter) => {
    if (dirty && !window.confirm('当前章节有未保存的更改，切换将丢弃？')) return
    setActiveId(chapter.id)
    setTitle(chapter.title)
    setContent(chapter.content)
    setSelectedText('')
    setDirty(false)
    setError(null)
  }

  // 首次加载时自动选中第一章节
  useEffect(() => {
    if (!activeId && chapters.length) selectChapter(chapters[0])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapters])

  const createMutation = useMutation({
    mutationFn: () =>
      chaptersApi.create(projectId!, { title: '未命名章节', order: chapters.length }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['chapters', projectId] })
      setActiveId(created.id)
      setTitle(created.title)
      setContent('')
      setDirty(false)
      setError(null)
    },
    onError: (err) => setError(getErrorMessage(err)),
  })

  const saveMutation = useMutation({
    mutationFn: () => chaptersApi.update(activeId!, { title, content }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chapters', projectId] })
      setDirty(false)
      setError(null)
    },
    onError: (err) => setError(getErrorMessage(err)),
  })

  const removeMutation = useMutation({
    mutationFn: () => chaptersApi.remove(activeId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chapters', projectId] })
      if (activeId) setActiveId(null)
      setContent('')
      setTitle('')
    },
    onError: (err) => setError(getErrorMessage(err)),
  })

  const handleInsert = (text: string) => {
    setContent((prev) => {
      if (!prev.trim()) return text
      return prev.endsWith('\n') ? `${prev}${text}` : `${prev}\n\n${text}`
    })
    setDirty(true)
  }

  const handleDelete = () => {
    if (window.confirm('确定删除该章节？')) removeMutation.mutate()
  }

  if (isLoading) return <p className="p-6 text-sm text-slate-400">加载中…</p>

  return (
    <div className="flex min-h-full">
      {/* 章节列表 */}
      <aside className="flex w-52 shrink-0 flex-col border-r border-border bg-card">
        <header className="flex items-center justify-between border-b border-border px-3 py-2.5">
          <span className="text-sm font-semibold text-foreground">章节</span>
          <button
            className="rounded bg-primary px-2 py-0.5 text-xs font-medium text-primary-foreground hover:bg-primary-hover"
            onClick={() => createMutation.mutate()}
            disabled={createMutation.isPending}
          >
            + 新建
          </button>
        </header>
        <div className="flex-1 space-y-1 overflow-y-auto p-2">
          {chapters.length === 0 && (
            <p className="py-4 text-center text-xs text-slate-400">还没有章节</p>
          )}
          {chapters.map((ch) => (
            <button
              key={ch.id}
              onClick={() => selectChapter(ch)}
              className={cn(
                'block w-full truncate rounded-md px-3 py-2 text-left text-sm transition-colors',
                activeId === ch.id
                  ? 'bg-primary/10 font-medium text-primary'
                  : 'text-slate-600 hover:bg-background',
              )}
            >
              {ch.title}
            </button>
          ))}
        </div>
      </aside>

      {/* 编辑器 */}
      <main className="flex min-w-0 flex-1 flex-col gap-3 p-4">
        <div className="flex items-center gap-2">
          <input
            value={title}
            onChange={(e) => {
              setTitle(e.target.value)
              setDirty(true)
            }}
            placeholder="章节标题"
            className="min-w-0 flex-1 rounded-md border border-border bg-card px-3 py-2 text-base font-semibold text-foreground focus:border-primary focus:outline-none"
          />
          <span className="shrink-0 text-xs text-slate-400">{countWords(content)} 字</span>
          <span className={cn('shrink-0 text-xs', dirty ? 'text-warning' : 'text-slate-400')}>
            {dirty ? '未保存' : '已保存'}
          </span>
          <button
            className="shrink-0 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
            disabled={!activeId || !dirty || saveMutation.isPending}
            onClick={() => saveMutation.mutate()}
          >
            {saveMutation.isPending ? '保存中…' : '保存'}
          </button>
          <button
            className="shrink-0 rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-600 hover:bg-background disabled:opacity-50"
            disabled={!activeId}
            onClick={() => setVersionsOpen(true)}
          >
            历史版本
          </button>
          <button
            className="shrink-0 text-xs text-slate-400 hover:text-danger disabled:opacity-50"
            disabled={!activeId}
            onClick={handleDelete}
          >
            删除
          </button>
        </div>

        {error && <p className="text-xs text-danger">{error}</p>}

        <MarkdownEditor
          value={content}
          onChange={(v) => {
            setContent(v)
            setDirty(true)
          }}
          onSelectionChange={setSelectedText}
          minHeight={560}
        />
      </main>

      {/* AI 生成面板 */}
      {projectId && activeId && (
        <aside className="w-80 shrink-0 border-l border-border bg-card/60">
          <GenerationPanel
            projectId={projectId}
            chapterId={activeId}
            content={content}
            selectedText={selectedText}
            onInsert={handleInsert}
          />
        </aside>
      )}

      {/* 历史版本弹窗 */}
      <ChapterVersionsModal
        open={versionsOpen}
        onClose={() => setVersionsOpen(false)}
        chapterId={activeId ?? ''}
        currentContent={content}
        onRolledBack={(c) => {
          setContent(c)
          setDirty(false)
          queryClient.invalidateQueries({ queryKey: ['chapters', projectId] })
          setError(null)
        }}
      />
    </div>
  )
}
