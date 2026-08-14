import { create } from 'zustand'

/**
 * 全局应用状态（Zustand）。
 * 目前只跟踪“当前项目”，后续可扩展 UI 偏好、编辑缓存等。
 */
interface AppState {
  /** 当前打开的项目 id（未打开时为 null） */
  currentProjectId: string | null
  setCurrentProjectId: (id: string | null) => void
}

export const useAppStore = create<AppState>((set) => ({
  currentProjectId: null,
  setCurrentProjectId: (id) => set({ currentProjectId: id }),
}))
