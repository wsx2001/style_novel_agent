import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { projectsApi } from '@/api'
import { getErrorMessage } from '@/api/client'
import { cn } from '@/lib/utils'
import type { Project } from '@/types'

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('zh-CN')
}

/** 新建项目弹窗 */
function CreateProjectModal({
  open,
  onClose,
  onCreate,
}: {
  open: boolean
  onClose: () => void
  onCreate: (payload: { title: string; description?: string; genre?: string }) => void
}) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [genre, setGenre] = useState('')
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-xl bg-card p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-4 text-base font-semibold text-foreground">新建项目</h2>
        <div className="space-y-3">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="项目名称"
            autoFocus
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:border-primary focus:outline-none"
          />
          <input
            value={genre}
            onChange={(e) => setGenre(e.target.value)}
            placeholder="类型（可选，如：都市奇幻 / 科幻）"
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:border-primary focus:outline-none"
          />
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="简介（可选）"
            rows={3}
            className="w-full resize-none rounded-md border border-border bg-background px-3 py-2 text-sm focus:border-primary focus:outline-none"
          />
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button
            className="rounded-md border border-border px-3 py-1.5 text-sm text-slate-600 hover:bg-background"
            onClick={onClose}
          >
            取消
          </button>
          <button
            className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
            disabled={!title.trim()}
            onClick={() => {
              onCreate({ title, description, genre })
              setTitle(''); setDescription(''); setGenre('')
            }}
          >
            创建
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * 项目列表页（应用首页）。
 * 展示项目卡片，支持新建 / 打开 / 删除。
 */
export default function ProjectList() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)

  const { data: projects = [], isLoading, isError } = useQuery({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
  })

  const createMutation = useMutation({
    mutationFn: projectsApi.create,
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/project/${project.id}/chapters`)
    },
  })

  const removeMutation = useMutation({
    mutationFn: projectsApi.remove,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects'] }),
  })

  const handleDelete = (project: Project) => {
    if (window.confirm(`确定删除项目「${project.title}」？该操作会级联删除其文档、知识卡与章节。`)) {
      removeMutation.mutate(project.id)
    }
  }

  return (
    <div className="min-h-full bg-background px-8 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">项目列表</h1>
          <p className="mt-1 text-sm text-slate-500">选择或创建一个本地小说项目</p>
        </div>
        <button
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover"
          onClick={() => setCreateOpen(true)}
        >
          + 新建项目
        </button>
      </header>

      {isLoading && <p className="text-sm text-slate-400">加载中…</p>}
      {isError && <p className="text-sm text-danger">项目列表加载失败</p>}

      {projects.length === 0 && !isLoading && (
        <div className="flex h-48 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-card/50">
          <p className="text-sm text-slate-500">还没有项目</p>
          <button
            className="text-sm font-medium text-primary hover:text-primary-hover"
            onClick={() => setCreateOpen(true)}
          >
            创建一个新项目开始写作
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {projects.map((project) => (
          <div
            key={project.id}
            className="group cursor-pointer rounded-xl border border-border bg-card p-4 transition-shadow hover:shadow-md"
            onClick={() => navigate(`/project/${project.id}/chapters`)}
          >
            <div className="flex items-start justify-between gap-2">
              <h2 className="truncate text-base font-semibold text-foreground">{project.title}</h2>
              <button
                className="shrink-0 text-slate-400 opacity-0 transition-opacity hover:text-danger group-hover:opacity-100"
                onClick={(e) => {
                  e.stopPropagation()
                  handleDelete(project)
                }}
                aria-label="删除项目"
                title="删除项目"
              >
                ✕
              </button>
            </div>
            {project.genre && (
              <span className="mt-1 inline-block rounded bg-primary/10 px-1.5 py-0.5 text-xs text-primary">
                {project.genre}
              </span>
            )}
            <p className={cn('mt-2 line-clamp-2 min-h-[2.5rem] text-sm text-slate-500')}>
              {project.description || '暂无简介'}
            </p>
            <p className="mt-2 text-xs text-slate-400">更新于 {formatDate(project.updated_at)}</p>
          </div>
        ))}
      </div>

      <CreateProjectModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreate={(payload) => {
          createMutation.mutate(payload)
          setCreateOpen(false)
        }}
      />
      {createMutation.isError && (
        <p className="mt-2 text-xs text-danger">{getErrorMessage(createMutation.error)}</p>
      )}
    </div>
  )
}
