import type { CardType } from '@/types'

/** 卡片类型中文名（供卡片选择器 / 筛选 / 展示共用） */
export const CARD_TYPE_LABELS: Record<CardType, string> = {
  character: '角色卡',
  world: '世界观卡',
  term: '术语卡',
  style: '文风卡',
  event: '事件卡',
}

export const CARD_TYPES = Object.keys(CARD_TYPE_LABELS) as CardType[]
