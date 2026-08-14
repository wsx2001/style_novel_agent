import { useState, type FormEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'

/**
 * Markdown 编辑器（textarea 先实现，编辑/预览切换）。
 * 通过 onSelectionChange 上报当前选区文本，供 AI 重写使用。
 */
export function MarkdownEditor({
  value,
  onChange,
  onSelectionChange,
  disabled,
  minHeight = 480,
}: {
  value: string
  onChange: (v: string) => void
  onSelectionChange?: (text: string) => void
  disabled?: boolean
  minHeight?: number
}) {
  const [mode, setMode] = useState<'edit' | 'preview'>('edit')

  const handleSelect = (e: FormEvent<HTMLTextAreaElement>) => {
    const el = e.currentTarget
    onSelectionChange?.(value.slice(el.selectionStart, el.selectionEnd))
  }

  return (
    <div className="flex flex-col overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
        <div className="flex gap-1">
          {(['edit', 'preview'] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={cn(
                'rounded px-2.5 py-1 text-xs font-medium transition-colors',
                mode === m
                  ? 'bg-primary text-primary-foreground'
                  : 'text-slate-500 hover:text-foreground',
              )}
            >
              {m === 'edit' ? '编辑' : '预览'}
            </button>
          ))}
        </div>
        <span className="text-xs text-slate-400">Markdown</span>
      </div>

      {mode === 'edit' ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onSelect={handleSelect}
          onBlur={handleSelect}
          disabled={disabled}
          placeholder="在这里书写正文……支持 Markdown 语法"
          style={{ minHeight }}
          className="flex-1 resize-none bg-background px-4 py-3 font-mono text-sm leading-relaxed focus:outline-none"
        />
      ) : (
        <div
          className="markdown-preview flex-1 overflow-y-auto bg-background px-4 py-3 text-sm leading-relaxed"
          style={{ minHeight }}
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{value || '*（空）*'}</ReactMarkdown>
        </div>
      )}
    </div>
  )
}
