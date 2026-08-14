# backend/app/utils/file_parser.py
"""文档文件解析：提取纯文本。

支持 txt / md / docx 三种格式，供文档上传接口（docs/TECH.md §5.2）使用。
对外暴露异步函数 parse_file_content(filename, content_bytes) -> (file_type, text)。
"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

# 扩展名 -> 规范化 file_type
SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".txt": "txt",
    ".md": "md",
    ".markdown": "md",
    ".docx": "docx",
}


def _detect_file_type(filename: str) -> str:
    """根据扩展名识别文件类型，不支持则抛 ValueError。"""
    ext = Path(filename).suffix.lower()
    file_type = SUPPORTED_EXTENSIONS.get(ext)
    if file_type is None:
        raise ValueError(f"不支持的文件类型：{ext or '(无扩展名)'}（仅支持 txt/md/docx）")
    return file_type


def _decode_text(content_bytes: bytes) -> str:
    """解码 txt/md 文本：优先 UTF-8（含 BOM），回退 GBK（常见中文编码）。"""
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return content_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    # 兜底：替换无法解码的字节，避免上传直接失败
    return content_bytes.decode("utf-8", errors="replace")


def _extract_docx_text(content_bytes: bytes) -> str:
    """提取 docx 纯文本：按文档顺序输出段落与表格（表格单元格以 | 连接）。"""
    doc = DocxDocument(io.BytesIO(content_bytes))
    lines: list[str] = []
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            text = Paragraph(child, doc).text
            if text:
                lines.append(text)
        elif child.tag == qn("w:tbl"):
            table = Table(child, doc)
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                lines.append(" | ".join(cells))
    return "\n".join(lines).strip()


async def parse_file_content(filename: str, content_bytes: bytes) -> tuple[str, str]:
    """解析文件内容，返回 (file_type, 纯文本)。

    file_type 为规范化类型：txt / md / docx。
    不支持的扩展名或损坏的文档会抛 ValueError。
    """
    file_type = _detect_file_type(filename)
    if file_type == "docx":
        # python-docx 为同步库，放入线程池避免阻塞事件循环
        text = await asyncio.to_thread(_extract_docx_text, content_bytes)
    else:
        text = _decode_text(content_bytes)
    return file_type, text
