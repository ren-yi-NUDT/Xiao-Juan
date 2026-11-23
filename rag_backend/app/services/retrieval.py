# -*- coding: utf-8 -*-
"""知识块检索：向量召回 + 关键词覆盖度加权。

只检索 status='approved' 的知识块，下架内容不会出现在游客端或 AI 回答里。
"""
from __future__ import annotations

import re
import sqlite3

from app.config import get_config
from app.services.embedding import cosine, from_blob, get_embedder

_CJK_RE = re.compile(r"[一-鿿]")

# 口语问法的轻量同义扩展：让“带老人半天怎么逛”能命中“休息区域 / 4 小时路线”。
# 向量与关键词都基于扩展后的查询，日志仍记录游客原话。
_QUERY_EXPANSIONS = {
    "老人": "无障碍 休息 缓行 电梯 长辈",
    "半天": "小时 半日 路线 游线",
    "逛": "游览 路线 游线",
    "怎么走": "路线 游线 步行",
    "几点": "时间 场次 演出",
    "几场": "场次 演出 时间",
    "开演": "演出 场次 表演",
    "演出": "场次 表演 时间",
    "晚上": "夜间 灯光秀 夜游 禅行",
    "夜景": "夜间 灯光秀 夜游",
    "票价": "门票 价格 元",
    "多少钱": "价格 元 票价",
    "停车": "停车场 车位",
    "吃饭": "餐饮 餐厅 素食",
}

# 口语里没有检索价值的填充词，先剔掉再匹配，避免拉低关键词覆盖率。
_FILLERS = ("今天", "现在", "请问", "一下", "你好", "帮我", "我想", "想问", "的话")

# 问句意图 -> 期望的字段块，命中时给小幅加权（由表结构直接支撑，可解释）。
_FIELD_HINTS = (
    (("几点", "几场", "开演", "演出", "场次", "时刻"), "演艺/开放信息", 0.12),
    (("门票", "票价", "多少钱", "价格", "免费"), "门票", 0.12),
    (("怎么走", "路线", "逛", "半天", "一天", "小时"), "路线", 0.10),
    (("休息", "老人", "轮椅", "无障碍", "孩子"), "休息", 0.06),
)


def normalize_query(query: str) -> str:
    for filler in _FILLERS:
        query = query.replace(filler, "")
    return query.strip() or query


def expand_query(query: str) -> str:
    extras = [value for key, value in _QUERY_EXPANSIONS.items() if key in query]
    return query + (" " + " ".join(extras) if extras else "")


def _field_bonus(query: str, title: str) -> float:
    bonus = 0.0
    for keywords, needle, weight in _FIELD_HINTS:
        if any(keyword in query for keyword in keywords) and needle in (title or ""):
            bonus += weight
    return bonus


def _keyword_coverage(query: str, text: str) -> float:
    chars = _CJK_RE.findall(query or "")
    if not chars:
        return 0.0
    grams = {chars[i] + chars[i + 1] for i in range(len(chars) - 1)} or set(chars)
    hits = sum(1 for gram in grams if gram in text)
    return hits / len(grams)


def search(conn: sqlite3.Connection, area_id: str, query: str,
           top_k: int | None = None, min_score: float | None = None) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []

    cfg = get_config().retrieval
    top_k = int(top_k or getattr(cfg, "top_k", 5))
    min_score = float(getattr(cfg, "min_score", 0.05) if min_score is None else min_score)

    embedder = get_embedder()
    normalized = normalize_query(query)
    expanded = expand_query(normalized)
    query_vector = embedder.encode(expanded)

    rows = conn.execute(
        """SELECT c.id, c.doc_id, c.attraction_id, c.title, c.content, c.vector,
                  d.name AS doc_name
           FROM knowledge_chunk c
           JOIN knowledge_doc d ON d.id = c.doc_id
           WHERE c.area_id = ? AND c.status = 'approved' AND c.vector IS NOT NULL""",
        (area_id,),
    ).fetchall()

    scored: list[dict] = []
    for row in rows:
        vector = from_blob(row["vector"])
        if vector.shape != query_vector.shape:
            continue
        semantic = cosine(query_vector, vector)
        coverage = _keyword_coverage(expanded, row["content"] + row["title"])
        score = 0.7 * semantic + 0.3 * coverage
        phrase_bonus = 0.15 if normalized in row["content"] else 0.0
        final = score + phrase_bonus + _field_bonus(normalized, row["title"])
        if final >= min_score:
            scored.append({
                "chunk_id": row["id"],
                "doc_id": row["doc_id"],
                "doc_name": row["doc_name"],
                "attraction_id": row["attraction_id"],
                "title": row["title"],
                "content": row["content"],
                "score": round(final, 4),
                "semantic": round(semantic, 4),
                "keyword": round(coverage, 4),
            })

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:top_k]


def retrieve_for_answer(conn: sqlite3.Connection, area_id: str, question: str,
                        top_k: int | None = None) -> list[dict]:
    hits = search(conn, area_id, question, top_k=top_k, min_score=0.0)
    hits = [hit for hit in hits if hit["score"] >= 0.08]
    if not hits:
        return []
    # 只保留与最佳命中差距不大的块，避免把“搭车”的低分段落塞进答案
    cutoff = max(0.15, hits[0]["score"] * 0.7)
    return [hit for hit in hits if hit["score"] >= cutoff][: top_k or 5]
