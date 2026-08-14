import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { documentsApi, type SnippetChunk } from '@/api/documents'
import { getErrorMessage } from '@/api/client'
import { UploadZone } from '@/components/documents/UploadZone'
import { ParseCandidates } from '@/components/documents/ParseCandidates'
import { cn } from '@/lib/utils'
import type { CandidateCard, Document, DocumentStatus } from '@/types'

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
 */
export default function DocumentParse() {
  const { projectId } = useParams<{ projectId: string }>()
  const queryClient = useQueryClient()

  const { data: documents = [], isLoading } = useQuery({
    queryKey: ['documents', projectId],
    queryFn: () => documentsApi.list(projectId!),
    enabled: !!projectId,
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) => documentsApi.upload(projectId!, file),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['documents', projectId] }),
    onError: (err) => setError(getErrorMessage(err)),
  })

  // 解析结果（一次一个文档）
  const [parsingId, setParsingId] = useState<string | null>(null)
  const [candidates, setCandidates] = useState<CandidateCard[] | null>(null)
  const [chunks, setChunks] = useState<SnippetChunk[]>([])
  const [parseTarget, setParseTarget] = useState<Document | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleParse = async (doc: Document) => {
    setError(null)
    setParsingId(doc.id)
    try {
      const [cands, chunkList] = await Promise.all([
        documentsApi.parse(doc.id, { threshold: doc.parse_threshold }),
        documentsApi.chunks(doc.id),
      ])
      setCandidates(cands)
      setChunks(chunkList)
      setParseTarget(doc)
    } catch (err) {
      setError(getErrorMessage(err))
      setCandidates(null)
    } finally {
      setParsingId(null)
    }
  }

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
      {uploadMutation.isError && (
        <p className="text-xs text-danger">{getErrorMessage(uploadMutation.error)}</p>
      )}

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
                <button
                  className="rounded-md border border-primary px-3 py-1 text-sm font-medium text-primary hover:bg-primary/5 disabled:opacity-50"
                  disabled={parsingId !== null || doc.status === 'parsing'}
                  onClick={() => handleParse(doc)}
                >
                  {parsingId === doc.id ? '解析中…' : doc.status === 'parsed' ? '重新解析' : '解析'}
                </button>
              </li>
            )
          })}
        </ul>
      </section>

      {error && <p className="text-sm text-danger">{error}</p>}

      {/* 解析候选卡片确认 */}
      {candidates && projectId && parseTarget && (
        <ParseCandidates
          projectId={projectId}
          documentId={parseTarget.id}
          candidates={candidates}
          chunks={chunks}
          onImported={() => {
            setCandidates(null)
            setParseTarget(null)
            queryClient.invalidateQueries({ queryKey: ['documents', projectId] })
          }}
        />
      )}
    </div>
  )
}
