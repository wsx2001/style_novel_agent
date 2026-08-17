import { create } from 'zustand'
import { getErrorMessage } from '@/api/client'
import { documentsApi, type ParseProgressFrame, type SnippetChunk } from '@/api/documents'
import type { CandidateCard, Document } from '@/types'

/**
 * 文档解析会话全局状态（Zustand）。
 *
 * 解析流程与结果原先全部存在 DocumentParse 页的组件局部 useState 里，切换页面
 * 组件卸载后即丢失，导致无法查看进度 / 结果，也无法确认导入。这里提升到全局：
 * - startParse 在 store action 内驱动 SSE 流（不依赖组件生命周期），切页后进度
 *   继续在后台累积，任意页面都能通过 ParseProgressOverlay 看到；
 * - 完成后 candidates / chunks 保存在 store，回到文档页可直接确认导入；
 * - restoreParseResult 从后端 GET /documents/{id}/parse-result 恢复已解析结果，
 *   刷新页面后仍可继续确认导入（后端在解析完成时已暂存 parse_result_json）。
 */
export type ParseSessionStatus = 'idle' | 'running' | 'done' | 'error'

interface ParseSessionState {
  status: ParseSessionStatus
  projectId: string | null
  documentId: string | null
  parseTarget: Document | null
  progressUnits: ParseProgressFrame[]
  progressTotal: number
  candidates: CandidateCard[] | null
  chunks: SnippetChunk[]
  error: string | null
  /** 启动 SSE 解析并持续写入 store（切页后进度继续累积） */
  startParse: (doc: Document, projectId: string, threshold?: string) => Promise<void>
  /** 从后端恢复已解析结果（刷新后进入文档页时调用） */
  restoreParseResult: (doc: Document, projectId: string) => Promise<void>
  /** 确认导入成功后清理会话 */
  clear: () => void
}

export const useParseSessionStore = create<ParseSessionState>((set) => ({
  status: 'idle',
  projectId: null,
  documentId: null,
  parseTarget: null,
  progressUnits: [],
  progressTotal: 0,
  candidates: null,
  chunks: [],
  error: null,

  startParse: async (doc, projectId, threshold) => {
    set({
      status: 'running',
      projectId,
      documentId: doc.id,
      parseTarget: doc,
      progressUnits: [],
      progressTotal: 0,
      candidates: null,
      chunks: [],
      error: null,
    })
    try {
      await documentsApi.parseStream(
        doc.id,
        { threshold },
        {
          onProgress: (frame) =>
            set((s) => ({
              progressTotal: frame.total,
              progressUnits: [
                ...s.progressUnits.filter((u) => u.index !== frame.index),
                frame,
              ],
            })),
          onDone: async (cands) => {
            const chunkList = await documentsApi.chunks(doc.id)
            set({ candidates: cands, chunks: chunkList, status: 'done' })
          },
          onError: (message) =>
            set({ error: message, candidates: null, status: 'error' }),
        },
      )
    } catch (err) {
      set({ error: getErrorMessage(err), candidates: null, status: 'error' })
    }
  },

  restoreParseResult: async (doc, projectId) => {
    set({
      status: 'idle',
      projectId,
      documentId: doc.id,
      parseTarget: doc,
      progressUnits: [],
      progressTotal: 0,
      candidates: null,
      chunks: [],
      error: null,
    })
    try {
      const result = await documentsApi.parseResult(doc.id)
      const chunkList = await documentsApi.chunks(doc.id)
      set({ candidates: result.candidates, chunks: chunkList, status: 'done' })
    } catch (err) {
      set({ error: getErrorMessage(err), candidates: null, status: 'error' })
    }
  },

  clear: () =>
    set({
      status: 'idle',
      projectId: null,
      documentId: null,
      parseTarget: null,
      progressUnits: [],
      progressTotal: 0,
      candidates: null,
      chunks: [],
      error: null,
    }),
}))
