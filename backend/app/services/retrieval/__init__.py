"""知识检索服务：Chroma 向量库封装（docs/TECH.md §6.3 / §6.4）。

- PersistentClient 持久化目录从 config 读取（CHROMA_PERSIST_DIR）；
- 每个项目一个 collection（project_{project_id}）；
- upsert_snippets：为片段批量生成 embedding 并写入；
- query_snippets：query 文本 embedding 后检索 top_k 相似片段。
"""
