import { useRef, useState, type KeyboardEvent } from 'react'
import { cn } from '@/lib/utils'

interface ChatInputProps {
  /** 发送回调（传入已 trim 的文本，父级负责清空输入） */
  onSend: (text: string) => void
  /** 流式回复进行中，禁用发送 */
  disabled?: boolean
}

/**
 * 底部输入框：多行自适应 textarea，Enter 发送（Shift+Enter 换行），发送按钮。
 */
export default function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const submit = () => {
    const text = value.trim()
    if (!text || disabled) return
    onSend(text)
    setValue('')
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // 中文输入法选词（isComposing）时不触发发送
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }

  /** 随内容自动增高（上限 160px） */
  const autoResize = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }

  return (
    <div className="flex items-end gap-2 border-t border-border bg-card px-4 py-3">
      <textarea
        ref={textareaRef}
        value={value}
        rows={1}
        disabled={disabled}
        onChange={(e) => {
          setValue(e.target.value)
          autoResize()
        }}
        onKeyDown={handleKeyDown}
        placeholder="输入消息，Enter 发送，Shift+Enter 换行"
        className="max-h-40 min-h-[44px] flex-1 resize-none rounded-lg border border-border bg-background px-3 py-2.5 text-sm leading-relaxed focus:border-primary focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
      />
      <button
        type="button"
        onClick={submit}
        disabled={disabled || !value.trim()}
        className={cn(
          'h-11 shrink-0 rounded-lg px-5 text-sm font-medium text-primary-foreground transition-colors',
          disabled || !value.trim() ? 'cursor-not-allowed bg-primary/50' : 'bg-primary hover:bg-primary-hover',
        )}
      >
        {disabled ? '回复中…' : '发送'}
      </button>
    </div>
  )
}
