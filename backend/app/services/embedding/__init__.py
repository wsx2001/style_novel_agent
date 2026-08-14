"""Embedding 服务：远程 OpenAI-compatible 嵌入 + 本地离线哈希嵌入。

参考 docs/TECH.md §6.1：使用用户配置的 API Key 调用 /embeddings 端点。
无 API Key 时回退到本地确定性哈希向量（仅用于离线体验，不依赖任何原生库）。
"""
