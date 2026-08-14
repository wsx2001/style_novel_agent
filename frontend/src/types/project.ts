import type { Timestamped } from './common'

/** 项目（对应后端 Project 模型 / ProjectOut schema） */
export interface Project extends Timestamped {
  id: string
  title: string
  description: string | null
  genre: string | null
  cover_path: string | null
}

/** 新建项目请求体 */
export interface ProjectCreate {
  title: string
  description?: string
  genre?: string
}

/** 更新项目请求体 */
export interface ProjectUpdate {
  title?: string
  description?: string
  genre?: string
}
