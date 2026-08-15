import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'
import type { MessageRole } from '@/types'

interface MessageBubbleProps {
  role: MessageRole
  content: string
  /** 流式生成中的占位气泡（内容为空时显示等待动画） */
  streaming?: boolean
}

/**
 * 单条消息气泡：
 * - user：右侧主色块（纯文本，保留换行）
 * - assistant：左侧卡片，Markdown 渲染（复用 .markdown-preview 样式）
 * - system：居中灰底提示
 */
export default function MessageBubble({ role, content, streaming }: MessageBubbleProps) {
  if (role === 'system') {
    return (
      <div className="flex justify-center">
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-500">{content}</span>
      </div>
    )
  }

  const isUser = role === 'user'

  return (
    <div className={cn('flex', isUser ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed',
          isUser
            ? 'rounded-br-sm bg-primary text-primary-foreground'
            : 'markdown-preview rounded-bl-sm border border-border bg-card text-foreground',
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap break-words">{content}</p>
        ) : (
          <div className="min-w-0">
            {content ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            ) : streaming ? (
              <span className="inline-flex items-center gap-1 py-1">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary [animation-delay:150ms]" />
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary [animation-delay:300ms]" />
              </span>
            ) : (
              <span className="text-slate-400">（空回复）</span>
            )}
            {streaming && content && (
              <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-primary align-text-bottom" />
            )}
          </div>
        )}
      </div>
    </div>
  )
}
