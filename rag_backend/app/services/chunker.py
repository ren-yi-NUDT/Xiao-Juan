# -*- coding: utf-8 -*-
"""文档切块。

对齐 lmam 分支的做法：
  * 按空行 / 章节切出“父段落”；
  * 父段落再按句切分，相邻两句合成一个知识块；
  * 每个块带 title（来源位置）与 parent_text（父段落）元数据。

在此之上补充了 docx 的标题层级、表格行、景点数据集的字段级切块。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import docx
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.services.textutil import clean_text, cut_long

_HEADING_RE = re.compile(r"^(?:Heading|标题)\s*(\d)", re.IGNORECASE)


@dataclass
class Chunk:
    title: str
    content: str
    parent_text: str = ""
    attraction_id: str | None = None


@dataclass
class Section:
    title: str = "正文"
    paragraphs: list[str] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)


def iter_block_items(parent):
    """按文档流顺序产出 Paragraph / Table（python-docx 官方推荐写法）。"""
    if isinstance(parent, DocxDocument):
        parent_elm = parent.element.body
    else:
        parent_elm = parent._tc
    for child in parent_elm.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(child, parent)
        elif tag == "tbl":
            yield Table(child, parent)


def load_docx(source: str | Path | bytes):
    if isinstance(source, (bytes, bytearray)):
        return docx.Document(BytesIO(source))
    return docx.Document(str(source))


def sections_from_docx(doc) -> list[Section]:
    """按 Heading 层级切章节；无标题的文档整体作为“正文”一节。"""
    stack: dict[int, str] = {}
    sections: list[Section] = []
    cur = Section()
    for block in iter_block_items(doc):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                continue
            style = block.style.name if block.style is not None else ""
            if style.lower() == "title":
                continue
            match = _HEADING_RE.match(style or "")
            if match:
                level = int(match.group(1))
                stack[level] = text
                for key in [k for k in stack if k > level]:
                    del stack[key]
                if cur.paragraphs or cur.tables:
                    sections.append(cur)
                cur = Section(title=" · ".join(stack[k] for k in sorted(stack)))
            else:
                cur.paragraphs.append(text)
            continue

        rows: list[list[str]] = []
        for row in block.rows:
            cells = [clean_text(cell.text) for cell in row.cells]
            if any(cells):
                rows.append(cells)
        if rows:
            cur.tables.append(rows)

    if cur.paragraphs or cur.tables:
        sections.append(cur)
    return sections or [Section()]


def chunks_from_table(title: str, table: list[list[str]],
                      max_chars: int = 500, pair: bool = True) -> list[Chunk]:
    """表格切块：宽表（数据集）按字段切，窄表（键值/票种）按行切。"""
    if not table:
        return []
    headers = [h or f"列{i + 1}" for i, h in enumerate(table[0])]
    out: list[Chunk] = []
    for row in table[1:]:
        cells = [c or "" for c in row]
        if not any(cells):
            continue
        if len(headers) >= 4:
            # 景点结构化数据集：第一列景区名、第二列景点 ID、第三列景点名称
            name = cells[2] if len(cells) > 2 else cells[0]
            rid = cells[1] if len(cells) > 1 else ""
            parent = "；".join(
                f"{h}：{v}" for h, v in zip(headers, cells) if v)
            for header, value in zip(headers, cells):
                if not value:
                    continue
                for piece in cut_long(value, max_chars, pair):
                    out.append(Chunk(
                        title=f"{rid} {name} · {header}".strip(),
                        content=piece,
                        parent_text=parent,
                        attraction_id=rid or None,
                    ))
        else:
            key = cells[0] or title
            parts = []
            for i, value in enumerate(cells):
                if not value:
                    continue
                header = headers[i] if i < len(headers) else ""
                parts.append(f"{header}：{value}" if header else value)
            content = "；".join(parts) or "；".join(cells)
            out.append(Chunk(
                title=f"{title} · {key}" if title and key != title else title,
                content=content,
                parent_text=title,
            ))
    return out


def chunks_from_sections(sections: list[Section], max_chars: int = 500,
                         pair: bool = True) -> list[Chunk]:
    out: list[Chunk] = []
    for section in sections:
        body = "\n".join(section.paragraphs)
        parent = (section.title + "\n" + body).strip() if body else section.title
        for piece in cut_long(body, max_chars, pair):
            out.append(Chunk(section.title, piece, parent))
        for table in section.tables:
            out.extend(chunks_from_table(section.title, table, max_chars, pair))
    return out


def chunks_from_docx(source: str | Path | bytes, doc_type: str = "long_doc",
                     max_chars: int = 500, pair: bool = True) -> list[Chunk]:
    """doc_type: long_doc（按章节）/ structured（按表格字段）。"""
    doc = load_docx(source)
    sections = sections_from_docx(doc)
    if doc_type == "structured":
        # 结构化文档优先按表格切；若没有表格，退回章节切块
        table_chunks: list[Chunk] = []
        for section in sections:
            for table in section.tables:
                table_chunks.extend(
                    chunks_from_table(section.title, table, max_chars, pair))
        if table_chunks:
            return table_chunks
    return chunks_from_sections(sections, max_chars, pair)


def chunks_from_text(text: str, title: str = "正文",
                     max_chars: int = 500, pair: bool = True) -> list[Chunk]:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]
    out: list[Chunk] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        head = lines[0] if len(lines[0]) <= 40 else title
        body = block if head == title else "\n".join(lines[1:])
        for piece in cut_long(body or block, max_chars, pair):
            out.append(Chunk(head, piece, block[:800]))
    return out
