import type { Timestamped, ChapterStatus } from './common'

/** 章节 / 场景（对应后端 Chapter 模型） */
export interface Chapter extends Timestamped {
  id: string
  project_id: string
  parent_id: string | null
  title: string
  order: number
  /** Markdown 正文 */
  content: string
  status: ChapterStatus
  word_count: number
}

/** 新建章节请求体 */
export interface ChapterCreate {
  title: string
  parent_id?: string
  order?: number
}

/** 保存章节请求体 */
export interface ChapterUpdate {
  title?: string
  content?: string
  word_count?: number
}

/** 章节版本快照（对应后端 VersionSnapshot 模型） */
export interface ChapterVersion extends Timestamped {
  id: string
  chapter_id: string
  content: string
  note: string
}

/** 创建版本快照请求体 */
export interface ChapterVersionCreate {
  content: string
  note?: string
}
