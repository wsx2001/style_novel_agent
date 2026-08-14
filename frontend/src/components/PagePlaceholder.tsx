import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * 页面占位组件：尚未实现的功能页统一骨架。
 * 实现具体功能后替换为真实页面内容。
 */
export function PagePlaceholder({
  title,
  description,
  children,
  className,
}: {
  title: string
  description?: string
  children?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex min-h-full flex-col px-8 py-8', className)}>
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-foreground">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-500">{description}</p>}
      </header>
      <div className="flex flex-1 items-center justify-center rounded-xl border border-dashed border-border bg-card/50 p-12">
        {children ?? (
          <div className="text-center text-sm text-slate-400">
            功能开发中……
            <br />
            <span className="mt-1 inline-block text-xs">该模块将在后续迭代中实现</span>
          </div>
        )}
      </div>
    </div>
  )
}
