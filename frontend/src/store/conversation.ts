import { create } from 'zustand'

/**
 * 对话工作台状态（Zustand）：
 * 当前选中对话 + 流式回复状态。供对话列表 / 消息区 / 输入框共享。
 */
interface ConversationState {
  /** 当前选中的对话 id（未选择时为 null） */
  currentConversationId: string | null
  setCurrentConversationId: (id: string | null) => void
  /** 是否有流式回复进行中 */
  streaming: boolean
  setStreaming: (streaming: boolean) => void
}

export const useConversationStore = create<ConversationState>((set) => ({
  currentConversationId: null,
  setCurrentConversationId: (id) => set({ currentConversationId: id }),
  streaming: false,
  setStreaming: (streaming) => set({ streaming }),
}))
