# -*- coding: utf-8 -*-
"""切块用的文本工具。

pair_sentences 沿用 lmam 分支 build_vector_db 的思路：按句切分后相邻两句合并，
让一个知识块自成一个语义单元，同时保留父段落用于上下文补充。
"""
from __future__ import annotations

import re

_SENTENCE_RE = re.compile(r"[^。！？!?；;]+[。！？!?；;]?")


def clean_text(text: str) -> str:
    text = (text or "").replace("　", " ").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.findall(text or "") if s.strip()]


def pair_sentences(text: str, pair: bool = True) -> list[str]:
    sentences = split_sentences(text)
    if not pair:
        return sentences
    out: list[str] = []
    for i in range(0, len(sentences), 2):
        merged = sentences[i] + (sentences[i + 1] if i + 1 < len(sentences) else "")
        if merged.strip():
            out.append(merged.strip())
    return out


def cut_long(text: str, max_chars: int = 500, pair: bool = True) -> list[str]:
    """把一段文字切成不超过 max_chars 的块；优先按句子边界。"""
    text = clean_text(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    pieces = pair_sentences(text, pair=pair) or [text]
    out: list[str] = []
    buffer = ""
    for piece in pieces:
        if len(piece) > max_chars:
            # 单句过长：先冲掉缓冲，再硬切
            if buffer:
                out.append(buffer)
                buffer = ""
            for i in range(0, len(piece), max_chars):
                out.append(piece[i:i + max_chars])
            continue
        if buffer and len(buffer) + len(piece) > max_chars:
            out.append(buffer)
            buffer = ""
        buffer += piece
    if buffer:
        out.append(buffer)
    return out
