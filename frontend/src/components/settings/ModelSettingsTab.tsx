import { useState } from 'react'
import { cn } from '@/lib/utils'
import type { DepthLevel } from '@/types'

/** 六档思维深度选项（docs/TECHv1.md §8.1 / PRDv1 §1.1） */
const DEPTH_OPTIONS: Array<{ value: DepthLevel; label: string; hint: string }> = [
  { value: 'none', label: '无', hint: '不施加深度控制，完全使用模型默认行为' },
  { value: 'auto', label: '自动', hint: '根据上下文自动选择合适深度（默认选项）' },
  { value: 'low', label: '低', hint: '快速生成，推理少，响应快' },
  { value: 'medium', label: '中等', hint: '均衡推理与速度，输出较连贯' },
  { value: 'high', label: '高', hint: '深度推理，更严谨遵循设定' },
  { value: 'extreme', label: '极高', hint: '最大深度推理，输出最结构化' },
]

/** 归一化后的模型配置（表单形态，camelCase） */
export interface NormalizedModelConfig {
  depth: DepthLevel
  temperature: number
  maxTokens: number
}

interface ModelSettingsTabProps {
  /** 当前配置（由父级按作用域解析后归一化；父级用 key 重挂载以同步外部变更） */
  initialConfig: NormalizedModelConfig
  /** 配置仍在加载中（禁用表单） */
  loading: boolean
  /** 保存请求进行中 */
  saving: boolean
  onSave: (config: NormalizedModelConfig) => void
}

/**
 * 「模型设置」标签页（PRDv1 §1.2）：思维深度 / 随机性滑块 / 最大输出长度。
 */
export default function ModelSettingsTab({
  initialConfig,
  loading,
  saving,
  onSave,
}: ModelSettingsTabProps) {
  const [depth, setDepth] = useState<DepthLevel>(initialConfig.depth)
  const [temperature, setTemperature] = useState(initialConfig.temperature)
  const [maxTokens, setMaxTokens] = useState(initialConfig.maxTokens)

  const active = DEPTH_OPTIONS.find((d) => d.value === depth)

  return (
    <div className="space-y-5">
      {/* 思维深度 */}
      <section>
        <h3 className="text-sm font-medium text-foreground">思维深度</h3>
        <p className="mt-0.5 text-xs text-slate-400">{active?.hint}</p>
        <div className="mt-2 grid grid-cols-3 gap-1.5">
          {DEPTH_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              disabled={loading}
              onClick={() => setDepth(opt.value)}
              title={opt.hint}
              className={cn(
                'rounded-md border px-2 py-1.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50',
                depth === opt.value
                  ? 'border-primary bg-primary/10 font-medium text-primary'
                  : 'border-border text-slate-600 hover:border-primary/40 hover:text-foreground',
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </section>

      {/* 随机性 */}
      <section>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-foreground">随机性（创意性）</h3>
          <span className="font-mono text-sm text-slate-500">{temperature.toFixed(2)}</span>
        </div>
        <input
          type="range"
          min={0}
          max={2}
          step={0.1}
          value={temperature}
          disabled={loading}
          onChange={(e) => setTemperature(Number(e.target.value))}
          className="mt-2 w-full accent-primary disabled:cursor-not-allowed disabled:opacity-50"
        />
        <div className="flex justify-between text-[10px] text-slate-400">
          <span>0 · 精确稳定</span>
          <span>2 · 发散创意</span>
        </div>
      </section>

      {/* 最大输出长度（0 = 无上限，省略 max_tokens 交由提供商默认） */}
      <section>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-foreground">最大输出长度</h3>
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-500">
            <input
              type="checkbox"
              checked={maxTokens === 0}
              disabled={loading}
              onChange={(e) => setMaxTokens(e.target.checked ? 0 : 2048)}
              className="h-3.5 w-3.5 accent-primary"
            />
            无上限
          </label>
        </div>
        <input
          type="number"
          min={1}
          step={1}
          value={maxTokens === 0 ? '' : maxTokens}
          placeholder={maxTokens === 0 ? '无上限' : ''}
          disabled={loading || maxTokens === 0}
          onChange={(e) => {
            const v = Number(e.target.value)
            if (Number.isNaN(v)) return
            setMaxTokens(Math.max(1, Math.floor(v)))
          }}
          className="mt-1.5 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:border-primary focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
        />
      </section>

      <div className="border-t border-border pt-3">
        <p className="mb-2 text-[11px] text-slate-400">
          保存后，新设置将应用于后续消息，不影响已有消息。
        </p>
        <button
          type="button"
          disabled={loading || saving}
          onClick={() => onSave({ depth, temperature, maxTokens })}
          className={cn(
            'w-full rounded-md px-4 py-2 text-sm font-medium text-primary-foreground transition-colors',
            saving ? 'bg-primary/60' : 'bg-primary hover:bg-primary-hover',
            (loading || saving) && 'cursor-not-allowed opacity-60',
          )}
        >
          {saving ? '保存中…' : '保存'}
        </button>
      </div>
    </div>
  )
}
