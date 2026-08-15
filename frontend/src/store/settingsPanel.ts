import { create } from 'zustand'

/**
 * 模型/提示词设置面板的打开状态（Zustand）。
 * 面板实例由宿主页面挂载（Settings 页 scope=global、ProjectWorkspace scope=project、
 * 对话工作台 scope=conversation），作用范围通过组件 props 传入；此处只管理 open 布尔状态，
 * 保证任意入口（工具栏按钮）都能打开/关闭同一个面板实例。
 */
interface SettingsPanelState {
  /** 面板是否打开 */
  open: boolean
  /** 打开面板 */
  openPanel: () => void
  /** 关闭面板 */
  closePanel: () => void
  /** 切换开关 */
  togglePanel: () => void
}

export const useSettingsPanelStore = create<SettingsPanelState>((set) => ({
  open: false,
  openPanel: () => set({ open: true }),
  closePanel: () => set({ open: false }),
  togglePanel: () => set((s) => ({ open: !s.open })),
}))
