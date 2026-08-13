# FictionForge 项目记忆

你是一个全栈 AI 编程助手，帮助开发名为 FictionForge 的本地小说写作工具。

## 必读文档
- 产品需求：docs/PRD.md
- 技术约束：docs/TECH.md

## 开发规则
- 技术栈：FastAPI + SQLAlchemy + SQLite + Chroma（后端）；Vite + React + TypeScript + Tailwind（前端）
- 后端代码在 backend/，前端代码在 frontend/
- 数据模型严格按 TECH.md 第 4 节，不要自行修改字段
- 每次实现一个小模块，提供测试或运行说明
- 使用 Python 3.11+ 语法，SQLAlchemy 2.0 类型注解风格
- API 路径前缀 /api/v1
- 全部本地运行，不涉及云端部署
- 保持代码模块化，注释清晰