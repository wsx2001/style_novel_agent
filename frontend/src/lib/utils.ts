import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * 合并 Tailwind 类名（shadcn/ui 同款工具函数）。
 * clsx 负责条件拼接，tailwind-merge 负责去重冲突类。
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
