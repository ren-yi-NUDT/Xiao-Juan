# -*- coding: utf-8 -*-
"""知识文档与知识块的落库操作，导入器与管理端共用。"""
from __future__ import annotations

import sqlite3

from app.services.chunker import Chunk
from app.services.embedding import get_embedder, to_blob


def create_doc(conn: sqlite3.Connection, area_id: str, name: str, doc_type: str,
               source_file: str = "", file_size: int = 0,
               status: str = "approved", note: str = "") -> int:
    cur = conn.execute(
        """INSERT INTO knowledge_doc
           (area_id, name, doc_type, source_file, file_size, status, note)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (area_id, name, doc_type, source_file, file_size, status, note),
    )
    return int(cur.lastrowid)


def add_chunks(conn: sqlite3.Connection, doc_id: int, area_id: str,
               chunks: list[Chunk], start_seq: int = 0,
               status: str = "pending") -> int:
    if not chunks:
        return 0
    embedder = get_embedder()
    vectors = embedder.encode_many([c.content for c in chunks])
    rows = []
    for offset, (chunk, vector) in enumerate(zip(chunks, vectors)):
        rows.append((
            doc_id, area_id, chunk.attraction_id, start_seq + offset,
            chunk.title, chunk.content, chunk.parent_text,
            to_blob(vector), embedder.name, len(chunk.content), status,
        ))
    conn.executemany(
        """INSERT INTO knowledge_chunk
           (doc_id, area_id, attraction_id, seq, title, content, parent_text,
            vector, embed_model, char_count, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    return len(rows)


def refresh_doc_status(conn: sqlite3.Connection, doc_id: int) -> str:
    """按知识块状态汇总文档状态：有待审 -> pending；有通过 -> approved；否则 offline。"""
    counts = {
        row["status"]: row["n"]
        for row in conn.execute(
            "SELECT status, COUNT(*) AS n FROM knowledge_chunk WHERE doc_id=? GROUP BY status",
            (doc_id,),
        ).fetchall()
    }
    total = sum(counts.values())
    if total == 0:
        current = conn.execute(
            "SELECT status FROM knowledge_doc WHERE id=?", (doc_id,)).fetchone()
        return current["status"] if current else "offline"
    if counts.get("pending"):
        status = "pending"
    elif counts.get("approved"):
        status = "approved"
    else:
        status = "offline"
    conn.execute(
        "UPDATE knowledge_doc SET status=?, chunk_count=? WHERE id=?",
        (status, total, doc_id),
    )
    return status


def doc_payload(row: sqlite3.Row | dict) -> dict:
    data = dict(row)
    return data
