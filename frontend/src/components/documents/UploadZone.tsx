import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { cn } from '@/lib/utils'

/**
 * 文档拖拽上传区（react-dropzone）。
 * 接受 txt / md / docx，单文件，选择后立即回调 onUpload。
 */
export function UploadZone({
  onUpload,
  disabled,
}: {
  onUpload: (file: File) => void
  disabled?: boolean
}) {
  const onDrop = useCallback(
    (accepted: File[]) => {
      const file = accepted[0]
      if (file) onUpload(file)
    },
    [onUpload],
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'text/plain': ['.txt'],
      'text/markdown': ['.md', '.markdown'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
    },
    multiple: false,
    disabled,
  })

  return (
    <div
      {...getRootProps()}
      className={cn(
        'flex cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors',
        isDragActive
          ? 'border-primary bg-primary/5'
          : 'border-border bg-card hover:border-primary/50 hover:bg-card/80',
        disabled && 'cursor-not-allowed opacity-60',
      )}
    >
      <input {...getInputProps()} />
      <span className="text-2xl">📄</span>
      <p className="text-sm font-medium text-foreground">
        {isDragActive ? '松开以上传' : '拖拽文档到这里，或点击选择文件'}
      </p>
      <p className="text-xs text-slate-400">支持 txt / md / docx，最大 10MB</p>
    </div>
  )
}
