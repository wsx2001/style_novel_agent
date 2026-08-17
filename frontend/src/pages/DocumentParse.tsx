import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { documentsApi } from '@/api/documents'
import { getErrorMessage } from '@/api/client'
import { UploadZone } from '@/components/documents/UploadZone'
import { ParseCandidates } from '@/components/documents/ParseCandidates'
import { ParseProgressPanel } from '@/components/documents/ParseProgressPanel'
import { useParseSessionStore } from '@/store/parseSession'
import { cn } from '@/lib/utils'
import type { Document, DocumentStatus } from '@/types'

/** 文档状态中文名与颜色 */
const STATUS_META: Record<DocumentStatus, { label: string; className: string }> = {
  pending: { label: '待解析', className: 'bg-slate-100 text-slate-600' },
  parsing: { label: '解析中', className: 'bg-blue-100 text-blue-700' },
  parsed: { label: '已解析', className: 'bg-amber-100 text-amber-700' },
  imported: { label: '已导入', className: 'bg-green-100 text-green-700' },
  failed: { label: '失败', className: 'bg-red-100 text-red-700' },
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

/**
 * 文档解析页：
 * - 拖拽上传 txt / md / docx
 * - 文档列表 + 「解析」按钮（LLM 抽取候选卡片）
 * - 候选卡片勾选确认 → 导入知识库
 *
 * 解析进度与结果存于全局 store（store/parseSession.ts）：切换页面不丢失，
 * 刷新后可通过「查看解析结果」从后端恢复候选继续导入。
 */
export default function DocumentParse() {
  const { projectId } = useParams<{ projectId: string }>()
  const queryClient = useQueryClient()

  // 解析会话来自全局 store（跨页保留 / 后端可恢复）
  const parseStatus = useParseSessionStore((s) => s.status)
  const parseDocumentId = useParseSessionStore((s) => s.documentId)
  const parseTarget = useParseSessionStore((s) => s.parseTarget)
  const progressUnits = useParseSessionStore((s) => s.progressUnits)
  const progressTotal = useParseSessionStore((s) => s.progressTotal)
  const candidates = useParseSessionStore((s) => s.candidates)
  const chunks = useParseSessionStore((s) => s.chunks)
  const parseError = useParseSessionStore((s) => s.error)
  const startParse = useParseSessionStore((s) => s.startParse)
  const restoreParseResult = useParseSessionStore((s) => s.restoreParseResult)
  const clearParse = useParseSessionStore((s) => s.clear)

  // 上传错误独立于解析会话（解析错误在 store.error）
  const [uploadError, setUploadError] = useState<string | null>(null)

  const { data: documents = [], isLoading } = useQuery({
    queryKey: ['documents', projectId],
    queryFn: () => documentsApi.list(projectId!),
    enabled: !!projectId,
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) => documentsApi.upload(projectId!, file),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['documents', projectId] }),
    onError: (err) => setUploadError(getErrorMessage(err)),
  })

  // 解析完成/失败后刷新文档列表状态（解析中 → 已解析/失败）
  useEffect(() => {
    if (parseStatus === 'done' || parseStatus === 'error') {
      queryClient.invalidateQueries({ queryKey: ['documents', projectId] })
    }
  }, [parseStatus, projectId, queryClient])

  const isBusy = parseStatus === 'running'
  const isActiveDoc = (doc: Document) => parseDocumentId === doc.id

  return (
    <div className="min-h-full space-y-5 bg-background px-6 py-6">
      <header>
        <h1 className="text-2xl font-bold text-foreground">文档解析</h1>
        <p className="mt-1 text-sm text-slate-500">导入资料文档，自动提取设定并导入知识库</p>
      </header>

      <UploadZone
        onUpload={(file) => uploadMutation.mutate(file)}
        disabled={uploadMutation.isPending}
      />
      {uploadMutation.isPending && <p className="text-sm text-slate-400">上传中…</p>}
      {uploadError && <p className="text-xs text-danger">{uploadError}</p>}

      {/* 文档列表 */}
      <section className="overflow-hidden rounded-xl border border-border bg-card">
        <header className="border-b border-border px-4 py-2.5">
          <h2 className="text-sm font-semibold text-foreground">文档列表（{documents.length}）</h2>
        </header>
        {isLoading && <p className="p-4 text-sm text-slate-400">加载中…</p>}
        {!isLoading && documents.length === 0 && (
          <p className="p-4 text-sm text-slate-400">暂无文档，请先上传</p>
        )}
        <ul className="divide-y divide-border">
          {documents.map((doc) => {
            const status = STATUS_META[doc.status]
            const isCurrent = isActiveDoc(doc)
            return (
              <li key={doc.id} className="flex items-center gap-3 px-4 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-foreground">{doc.filename}</p>
                  <p className="text-xs text-slate-400">
                    {doc.file_type.toUpperCase()} · {formatSize(doc.file_size)} ·{' '}
                    {new Date(doc.created_at).toLocaleString('zh-CN')}
                  </p>
                </div>
                <span className={cn('rounded px-2 py-0.5 text-xs font-medium', status.className)}>
                  {status.label}
                </span>
                {doc.status === 'parsed' && !isBusy && !(parseStatus === 'done' && isCurrent) && (
                  <button
                    className="rounded-md border border-border px-2 py-1 text-xs text-slate-600 hover:border-primary/40 hover:text-foreground"
                    onClick={() => restoreParseResult(doc, projectId!)}
                  >
                    查看解析结果
                  </button>
                )}
                <button
                  className="rounded-md border border-primary px-3 py-1 text-sm font-medium text-primary hover:bg-primary/5 disabled:opacity-50"
                  disabled={isBusy}
                  onClick={() => startParse(doc, projectId!, doc.parse_threshold)}
                >
                  {isBusy && isCurrent ? '解析中…' : doc.status === 'parsed' ? '重新解析' : '解析'}
                </button>
              </li>
            )
          })}
        </ul>
      </section>

      {parseError && <p className="text-sm text-danger">{parseError}</p>}

      {/* 解析进度面板（流式期间实时更新；跨页时由全局悬浮面板承接） */}
      {isBusy && <ParseProgressPanel total={progressTotal} units={progressUnits} />}

      {/* 解析候选卡片确认（跨页/刷新后恢复的候选同样在此渲染） */}
      {candidates && projectId && parseTarget && parseTarget.project_id === projectId && (
        <ParseCandidates
          projectId={projectId}
          documentId={parseTarget.id}
          candidates={candidates}
          chunks={chunks}
          onImported={() => {
            clearParse()
            queryClient.invalidateQueries({ queryKey: ['documents', projectId] })
          }}
        />
      )}
    </div>
  )
}
