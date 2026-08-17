import { useMemo } from 'react'
import { cn } from '@/lib/utils'
import type { ParseProgressFrame } from '@/api/documents'

/** 后端 _unit_summary 返回的类别键 → 中文标签 */
const CATEGORY_LABELS: Record<string, string> = {
  characters: '人物',
  worldSettings: '场景',
  terms: '术语',
  keyEvents: '事件',
}

interface ParseProgressPanelProps {
  /** 总单元数（来自进度帧的 total） */
  total: number
  /** 已收到的进度帧（同一 index 取最新一条） */
  units: ParseProgressFrame[]
}

/**
 * 文档解析进度面板：进度条 + 进行中清单 + 已完成每章简略结果。
 * 由 DocumentParse 页在解析期间渲染，随 SSE progress 帧增量更新。
 */
export function ParseProgressPanel({ total, units }: ParseProgressPanelProps) {
  const completed = units.filter(
    (u) => u.status === 'done' || u.status === 'error' || u.status === 'skipped',
  ).length
  const inFlight = units.filter((u) => u.status === 'start')
  const pct = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0
  // 按 index 稳定排序，容忍 start/done 乱序到达
  const sorted = useMemo(() => [...units].sort((a, b) => a.index - b.index), [units])

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <header className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">解析进度</h3>
        <span className="text-xs text-slate-400">
          {completed}/{total} 章
        </span>
      </header>

      <div className="mb-3 h-2 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className="h-full rounded-full bg-primary transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>

      {inFlight.length > 0 && (
        <p className="mb-2 text-xs text-slate-500">
          正在解析（{inFlight.length} 并行）：{inFlight.map((u) => u.label).join(' · ')}…
        </p>
      )}

      <ul className="max-h-64 space-y-1 overflow-y-auto">
        {sorted.map((u) => (
          <li key={u.index} className="flex items-center gap-2 text-xs">
            <span
              className={cn(
                'shrink-0',
                u.status === 'done' && 'text-emerald-500',
                u.status === 'error' && 'text-danger',
                u.status === 'skipped' && 'text-slate-400',
                u.status === 'start' && 'animate-pulse text-primary',
              )}
            >
              {u.status === 'done' && '✔'}
              {u.status === 'error' && '✗'}
              {u.status === 'skipped' && '−'}
              {u.status === 'start' && '⏳'}
            </span>
            <span className="truncate text-foreground">{u.label}</span>
            {u.status === 'done' && u.result && (
              <span className="ml-auto shrink-0 text-slate-400">
                {(() => {
                  const parts = Object.entries(u.result).filter(([, n]) => (n ?? 0) > 0)
                  return parts.length
                    ? parts.map(([k, n]) => `${CATEGORY_LABELS[k] ?? k} ${n}`).join(' · ')
                    : '无抽取'
                })()}
              </span>
            )}
            {u.status === 'error' && <span className="ml-auto shrink-0 text-danger">解析失败</span>}
            {u.status === 'skipped' && <span className="ml-auto shrink-0 text-slate-400">无内容</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}
