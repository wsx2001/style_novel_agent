import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getErrorMessage } from '@/api/client'
import { conversationsApi } from '@/api/conversations'
import { useConversationStore } from '@/store/conversation'
import { useSettingsPanelStore } from '@/store/settingsPanel'
import type { Message } from '@/types'
import ConversationList from '@/components/conversation/ConversationList'
import MessageBubble from '@/components/conversation/MessageBubble'
import ChatInput from '@/components/conversation/ChatInput'
import ModelPromptSettings from '@/components/settings/ModelPromptSettings'

/** 乐观消息 id 前缀：本地临时消息，流式完成后由服务端数据替换 */
const LOCAL_USER_PREFIX = 'local-user-'
const LOCAL_ASSISTANT_PREFIX = 'local-assistant-'

/**
 * 对话工作台（docs/TECHv1.md §5.6 / PRDv1 §1.3）：
 * - 左侧：对话列表（新建/选择/删除）
 * - 中间：消息区（user/assistant，自动滚动到底部）+ 流式回复增量渲染
 * - 顶部：可编辑对话标题 + 「模型/提示词设置」（作用范围为当前会话）
 * - 底部：输入框（Enter 发送）
 */
export default function ConversationWorkspace() {
  const { projectId } = useParams<{ projectId: string }>()
  const queryClient = useQueryClient()

  const currentConversationId = useConversationStore((s) => s.currentConversationId)
  const setCurrentConversationId = useConversationStore((s) => s.setCurrentConversationId)
  const streaming = useConversationStore((s) => s.streaming)
  const setStreaming = useConversationStore((s) => s.setStreaming)
  const togglePanel = useSettingsPanelStore((s) => s.togglePanel)

  // 当前进行中的流（用于切换/卸载时中断）
  const abortRef = useRef<AbortController | null>(null)
  // 乐观消息：发送后立即显示用户消息 + assistant 占位，流式结束由服务端数据替换
  const [localMessages, setLocalMessages] = useState<Message[]>([])
  const [error, setError] = useState<string | null>(null)

  // 标题编辑
  const [editingTitle, setEditingTitle] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')

  const { data: conversation, isLoading } = useQuery({
    queryKey: ['conversation', currentConversationId],
    queryFn: () => conversationsApi.getConversation(currentConversationId!),
    enabled: !!currentConversationId,
  })

  // 切换项目时重置选中
  useEffect(() => {
    setCurrentConversationId(null)
  }, [projectId, setCurrentConversationId])

  // 切换对话 / 卸载时中止流并清理本地状态
  useEffect(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setLocalMessages([])
    setError(null)
    setEditingTitle(false)
    setStreaming(false)
  }, [currentConversationId, setStreaming])

  useEffect(() => () => abortRef.current?.abort(), [])

  // ===== 发送消息（SSE 流式） =====
  const handleSend = async (text: string) => {
    if (!currentConversationId || streaming) return
    const now = new Date().toISOString()
    const optimisticUser: Message = {
      id: `${LOCAL_USER_PREFIX}${Date.now()}`,
      conversationId: currentConversationId,
      role: 'user',
      content: text,
      metadata: {},
      createdAt: now,
    }
    const placeholder: Message = {
      id: `${LOCAL_ASSISTANT_PREFIX}${Date.now()}`,
      conversationId: currentConversationId,
      role: 'assistant',
      content: '',
      metadata: {},
      createdAt: now,
    }
    setLocalMessages([optimisticUser, placeholder])
    setError(null)
    setStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      await conversationsApi.sendMessage(
        currentConversationId,
        text,
        (delta) => {
          setLocalMessages((prev) => {
            const next = [...prev]
            const last = next[next.length - 1]
            if (last?.role === 'assistant' && last.id.startsWith(LOCAL_ASSISTANT_PREFIX)) {
              next[next.length - 1] = { ...last, content: last.content + delta }
            }
            return next
          })
        },
        async () => {
          // 流式完成：先等服务端刷新（含用户消息与完整回复），再移除乐观消息
          await queryClient.invalidateQueries({ queryKey: ['conversation', currentConversationId] })
          await queryClient.invalidateQueries({ queryKey: ['conversations', projectId] })
          abortRef.current = null
          setLocalMessages([])
          setStreaming(false)
        },
        controller.signal,
      )
    } catch (err) {
      // 出错：移除 assistant 占位，保留用户消息，展示错误横幅（主动中断不算错误）
      setLocalMessages((prev) => prev.slice(0, -1))
      setStreaming(false)
      const aborted = err instanceof DOMException && err.name === 'AbortError'
      if (!aborted) setError(getErrorMessage(err))
    }
  }

  // ===== 标题重命名 =====
  const renameMutation = useMutation({
    mutationFn: (title: string) => conversationsApi.updateConversation(currentConversationId!, { title }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['conversation', currentConversationId] })
      queryClient.invalidateQueries({ queryKey: ['conversations', projectId] })
    },
    onError: (err) => setError(getErrorMessage(err)),
  })

  const commitTitle = () => {
    const title = titleDraft.trim()
    if (title && currentConversationId) renameMutation.mutate(title)
    setEditingTitle(false)
  }

  // ===== 消息区 =====
  const serverMessages = conversation?.messages ?? []
  const displayMessages = [...serverMessages, ...localMessages]
  const streamingPlaceholderId =
    streaming && localMessages.length > 0 && localMessages[localMessages.length - 1].id.startsWith(LOCAL_ASSISTANT_PREFIX)
      ? localMessages[localMessages.length - 1].id
      : null

  const scrollRef = useRef<HTMLDivElement>(null)
  const lastKey = displayMessages.length
    ? `${displayMessages[displayMessages.length - 1].id}:${displayMessages[displayMessages.length - 1].content.length}`
    : 'empty'
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lastKey])

  return (
    <div className="flex h-full min-w-0">
      <ConversationList projectId={projectId!} currentId={currentConversationId} onSelect={setCurrentConversationId} />

      {currentConversationId ? (
        <div className="flex min-w-0 flex-1 flex-col">
          {/* 顶栏：标题（可编辑）+ 模型/提示词设置 */}
          <header className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-card px-4">
            {editingTitle ? (
              <input
                autoFocus
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitTitle()
                  if (e.key === 'Escape') setEditingTitle(false)
                }}
                onBlur={commitTitle}
                className="min-w-0 max-w-md rounded-md border border-primary bg-background px-2 py-1 text-sm focus:outline-none"
              />
            ) : (
              <button
                type="button"
                title="点击编辑标题"
                onClick={() => {
                  setTitleDraft(conversation?.title ?? '')
                  setEditingTitle(true)
                }}
                className="min-w-0 truncate text-sm font-semibold text-foreground hover:text-primary"
              >
                {conversation?.title ?? '…'}
              </button>
            )}
            <button
              type="button"
              onClick={togglePanel}
              title="模型/提示词设置（当前会话）"
              className="shrink-0 rounded-md border border-border px-2.5 py-1 text-xs font-medium text-slate-600 hover:border-primary/50 hover:text-primary"
            >
              ⚙ 模型/提示词设置
            </button>
          </header>

          {/* 消息区 */}
          <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto bg-background px-4 py-4">
            <div className="mx-auto flex max-w-3xl flex-col gap-3">
              {isLoading && <p className="py-8 text-center text-xs text-slate-400">加载中…</p>}
              {!isLoading && displayMessages.length === 0 && (
                <p className="py-8 text-center text-xs text-slate-400">发送第一条消息，开始与写作助手对话</p>
              )}
              {displayMessages.map((m) => (
                <MessageBubble
                  key={m.id}
                  role={m.role}
                  content={m.content}
                  streaming={m.id === streamingPlaceholderId}
                />
              ))}
            </div>
          </div>

          {error && (
            <p className="border-t border-border bg-card px-4 py-1.5 text-xs text-danger">{error}</p>
          )}

          <ChatInput onSend={handleSend} disabled={streaming} />
        </div>
      ) : (
        <div className="flex min-w-0 flex-1 flex-col items-center justify-center gap-3 bg-background">
          <p className="text-4xl">💬</p>
          <p className="text-sm text-slate-400">选择左侧对话，或点击「＋ 新建」开始</p>
        </div>
      )}

      {/* 会话范围模型/提示词设置抽屉 */}
      <ModelPromptSettings scope="conversation" conversationId={currentConversationId} />
    </div>
  )
}
