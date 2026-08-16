import client, { getErrorMessage } from './client'

export { client, getErrorMessage }
export type { ApiErrorBody } from './client'
export { projectsApi } from './projects'
export type { ExportFormat } from './projects'
export { modelProvidersApi } from './modelProviders'
export { documentsApi } from './documents'
export type { SnippetChunk, ConfirmImportResult } from './documents'
export { cardsApi } from './cards'
export { chaptersApi } from './chapters'
export type { ChapterVersionCreate } from './chapters'
export { generationsApi, generationUrls, continueGeneration, rewriteGeneration, toModelConfigWire } from './generations'
export type {
  ContinuePayload,
  RewritePayload,
  ContinueParams,
  RewriteParams,
  InspireParams,
  InspireResult,
  ModelConfigWire,
} from './generations'
export { settingsApi } from './settings'
export { conversationsApi } from './conversations'
export type { SendMessageHandlers } from './conversations'
export { promptTemplatesApi } from './promptTemplates'
