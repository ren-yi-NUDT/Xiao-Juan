# -*- coding: utf-8 -*-
"""管理端 API：F5 景区与资料管理 / F6 知识审核 / F7 检索热词。"""
from __future__ import annotations

import hashlib
import hmac
import re
import sqlite3
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.config import get_config
from app.db import rows, session
from app.security import make_token, require_admin
from app.services.chunker import chunks_from_docx, chunks_from_text
from app.services.docs import add_chunks, create_doc, refresh_doc_status
from app.services.embedding import embedding_info, get_embedder, to_blob
from app.services.importers import import_behavior_xlsx

router = APIRouter(prefix="/api/admin", tags=["管理端"])

DOC_STATUS = {"approved", "pending", "offline"}
CHUNK_STATUS = {"approved", "pending", "offline"}
DOC_TYPES = {"long_doc", "structured", "detail"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class LoginIn(BaseModel):
    username: str
    password: str


class AreaIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    tag: str = ""


class ChunkPatch(BaseModel):
    status: str | None = None
    title: str | None = None
    content: str | None = None


class FeedbackPatch(BaseModel):
    status: str
    note: str = ""


def _safe_filename(name: str) -> str:
    base = Path(name or "upload").name
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).strip(" .")
    return (base or "upload")[:120]


def _area_id(name: str) -> str:
    return "area_" + hashlib.md5(name.encode("utf-8")).hexdigest()[:8]


def _doc_payload(conn: sqlite3.Connection, doc_id: int) -> dict:
    found = conn.execute(
        """SELECT d.*, a.name AS area_name FROM knowledge_doc d
           JOIN scenic_area a ON a.id = d.area_id WHERE d.id = ?""",
        (doc_id,),
    ).fetchone()
    if not found:
        raise HTTPException(status_code=404, detail="文档不存在")
    return dict(found)


# ---------------- 登录 / 概览 ----------------

@router.post("/login")
def login(body: LoginIn):
    cfg = get_config().app
    ok_user = hmac.compare_digest(body.username, str(cfg.admin_user))
    ok_pass = hmac.compare_digest(body.password, str(cfg.admin_password))
    if not (ok_user and ok_pass):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    return {"token": make_token(body.username), "user": body.username}


@router.get("/me")
def me(user: str = Depends(require_admin)):
    return {"user": user}


@router.get("/overview")
def overview(_: str = Depends(require_admin)):
    with session() as conn:
        def count(sql: str) -> int:
            return int(conn.execute(sql).fetchone()[0])
        return {
            "areas": count("SELECT COUNT(*) FROM scenic_area"),
            "docs": count("SELECT COUNT(*) FROM knowledge_doc"),
            "chunks": count("SELECT COUNT(*) FROM knowledge_chunk"),
            "pending_chunks": count("SELECT COUNT(*) FROM knowledge_chunk WHERE status='pending'"),
            "questions": count("SELECT COUNT(*) FROM qa_log"),
            "today_questions": count(
                "SELECT COUNT(*) FROM qa_log WHERE date(created_at)=date('now','localtime')"),
            "embedding": embedding_info(),
        }


# ---------------- 景区（F5） ----------------

@router.get("/areas")
def list_areas(_: str = Depends(require_admin)):
    with session() as conn:
        return rows(conn, """
            SELECT a.id, a.name, a.tag, a.level, a.intro, a.created_at,
                   (SELECT COUNT(*) FROM knowledge_doc d WHERE d.area_id = a.id) AS docs,
                   (SELECT COUNT(*) FROM knowledge_chunk c WHERE c.area_id = a.id) AS chunks,
                   (SELECT COUNT(*) FROM qa_log q WHERE q.area_id = a.id) AS hits,
                   (SELECT COUNT(DISTINCT TRIM(q.question)) FROM qa_log q
                     WHERE q.area_id = a.id) AS words
            FROM scenic_area a
            ORDER BY a.created_at, a.id
        """)


@router.post("/areas", status_code=201)
def create_area(body: AreaIn, _: str = Depends(require_admin)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写景区名称")
    with session() as conn:
        exists = conn.execute(
            "SELECT id FROM scenic_area WHERE name = ?", (name,)).fetchone()
        if exists:
            raise HTTPException(status_code=409, detail="已存在同名景区")
        area_id = _area_id(name)
        conn.execute(
            "INSERT INTO scenic_area (id, name, tag) VALUES (?, ?, ?)",
            (area_id, name, body.tag.strip()))
        found = conn.execute(
            "SELECT * FROM scenic_area WHERE id = ?", (area_id,)).fetchone()
        data = dict(found)
        data.update({"docs": 0, "chunks": 0, "hits": 0, "words": 0})
        return data


@router.delete("/areas/{area_id}")
def delete_area(area_id: str, _: str = Depends(require_admin)):
    with session() as conn:
        found = conn.execute(
            "SELECT name FROM scenic_area WHERE id = ?", (area_id,)).fetchone()
        if not found:
            raise HTTPException(status_code=404, detail="景区不存在")
        doc_count = conn.execute(
            "SELECT COUNT(*) FROM knowledge_doc WHERE area_id = ?", (area_id,)).fetchone()[0]
        # 问答日志随景区一并清理，避免“已删除景区”的问题仍出现在全部景区的热词里
        conn.execute("DELETE FROM qa_log WHERE area_id = ?", (area_id,))
        conn.execute("DELETE FROM scenic_area WHERE id = ?", (area_id,))
        return {"deleted": area_id, "docs": doc_count}


# ---------------- 文档（F5）+ 知识块（F6） ----------------

@router.get("/docs")
def list_docs(area_id: str | None = None, status: str | None = None,
              q: str | None = None, _: str = Depends(require_admin)):
    clauses, params = [], []
    if area_id and area_id != "all":
        clauses.append("d.area_id = ?")
        params.append(area_id)
    if status and status != "all":
        if status not in DOC_STATUS:
            raise HTTPException(status_code=400, detail="状态取值不合法")
        clauses.append("d.status = ?")
        params.append(status)
    if q:
        clauses.append("d.name LIKE ?")
        params.append(f"%{q.strip()}%")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with session() as conn:
        return rows(conn, f"""
            SELECT d.id, d.area_id, d.name, d.doc_type, d.source_file, d.file_size,
                   d.status, d.chunk_count, d.note, d.uploaded_at, a.name AS area_name
            FROM knowledge_doc d JOIN scenic_area a ON a.id = d.area_id
            {where}
            ORDER BY d.uploaded_at DESC, d.id DESC
        """, params)


def _parse_upload(filename: str, doc_type: str, data: bytes,
                  max_chars: int, pair: bool):
    suffix = Path(filename).suffix.lower()
    if suffix == ".docx":
        return chunks_from_docx(data, doc_type, max_chars, pair), "docx"
    if suffix in (".txt", ".md"):
        text = data.decode("utf-8", errors="replace")
        return chunks_from_text(text, "正文", max_chars, pair), "text"
    if suffix == ".xlsx":
        if doc_type != "detail":
            raise HTTPException(status_code=400,
                                detail="xlsx 仅支持“明细表（直接入库）”类型")
        return None, "xlsx"
    raise HTTPException(status_code=400,
                        detail="暂只支持 .docx / .xlsx / .txt / .md 文件")


@router.post("/docs", status_code=201)
async def upload_doc(
    area_id: str = Form(...),
    name: str = Form(""),
    doc_type: str = Form("long_doc"),
    file: UploadFile = File(...),
    _: str = Depends(require_admin),
):
    if doc_type not in DOC_TYPES:
        raise HTTPException(status_code=400, detail="文档类型不合法")
    filename = _safe_filename(file.filename or "upload")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 50MB 限制")

    cfg = get_config()
    max_chars = int(getattr(cfg.chunking, "max_chars", 500))
    pair = bool(getattr(cfg.chunking, "pair_sentences", True))
    doc_name = (name or "").strip() or filename
    upload_dir = Path(cfg.app.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    with session() as conn:
        if not conn.execute("SELECT 1 FROM scenic_area WHERE id=?", (area_id,)).fetchone():
            raise HTTPException(status_code=404, detail="景区不存在")
        if conn.execute(
                "SELECT 1 FROM knowledge_doc WHERE area_id=? AND name=?",
                (area_id, doc_name)).fetchone():
            raise HTTPException(status_code=409, detail="该景区下已存在同名文档")

        chunks, kind = _parse_upload(filename, doc_type, data, max_chars, pair)

        doc_id = create_doc(
            conn, area_id, doc_name, doc_type, source_file=filename,
            file_size=len(data),
            status="pending" if kind != "xlsx" else "approved",
            note="上传后自动切块，等待审核")
        stored_path = upload_dir / f"{doc_id}_{filename}"
        stored_path.write_bytes(data)

        if kind == "xlsx":
            try:
                count = import_behavior_xlsx(conn, stored_path, doc_id)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"明细表解析失败：{exc}")
            conn.execute(
                "UPDATE knowledge_doc SET status='approved', chunk_count=0, note=? WHERE id=?",
                (f"{count:,} 行明细直接入库，不参与知识切块", doc_id))
        else:
            add_chunks(conn, doc_id, area_id, chunks, status="pending")
            conn.execute(
                "UPDATE knowledge_doc SET chunk_count=?, note=? WHERE id=?",
                (len(chunks), f"自动切分为 {len(chunks)} 个知识块，等待审核", doc_id))

        return _doc_payload(conn, doc_id)


@router.delete("/docs/{doc_id}")
def delete_doc(doc_id: int, _: str = Depends(require_admin)):
    with session() as conn:
        found = conn.execute(
            "SELECT source_file FROM knowledge_doc WHERE id=?", (doc_id,)).fetchone()
        if not found:
            raise HTTPException(status_code=404, detail="文档不存在")
        conn.execute("DELETE FROM knowledge_doc WHERE id=?", (doc_id,))
        return {"deleted": doc_id}


@router.get("/docs/{doc_id}/chunks")
def list_chunks(doc_id: int, _: str = Depends(require_admin)):
    with session() as conn:
        doc = conn.execute(
            "SELECT name FROM knowledge_doc WHERE id=?", (doc_id,)).fetchone()
        if not doc:
            raise HTTPException(status_code=404, detail="文档不存在")
        return rows(conn, """
            SELECT id, doc_id, attraction_id, seq, title, content, char_count,
                   status, embed_model, updated_at
            FROM knowledge_chunk WHERE doc_id=? ORDER BY seq, id
        """, (doc_id,))


@router.patch("/chunks/{chunk_id}")
def patch_chunk(chunk_id: int, body: ChunkPatch, _: str = Depends(require_admin)):
    with session() as conn:
        chunk = conn.execute(
            "SELECT * FROM knowledge_chunk WHERE id=?", (chunk_id,)).fetchone()
        if not chunk:
            raise HTTPException(status_code=404, detail="知识块不存在")
        if body.status is not None and body.status not in CHUNK_STATUS:
            raise HTTPException(status_code=400, detail="状态取值不合法")

        if body.title is not None:
            conn.execute("UPDATE knowledge_chunk SET title=? WHERE id=?",
                         (body.title.strip(), chunk_id))
        if body.content is not None and body.content.strip():
            content = body.content.strip()
            embedder = get_embedder()
            vector = embedder.encode(content)
            conn.execute(
                """UPDATE knowledge_chunk
                   SET content=?, char_count=?, vector=?, embed_model=?,
                       updated_at=datetime('now','localtime')
                   WHERE id=?""",
                (content, len(content), to_blob(vector), embedder.name, chunk_id))
        if body.status is not None:
            conn.execute(
                """UPDATE knowledge_chunk
                   SET status=?, updated_at=datetime('now','localtime') WHERE id=?""",
                (body.status, chunk_id))

        refresh_doc_status(conn, chunk["doc_id"])
        found = conn.execute(
            "SELECT * FROM knowledge_chunk WHERE id=?", (chunk_id,)).fetchone()
        data = dict(found)
        data.pop("vector", None)
        return data


# ---------------- 检索热词（F7） ----------------

@router.get("/stats/hot")
def hot_stats(area_id: str | None = None, limit: int = Query(10, ge=1, le=50),
              _: str = Depends(require_admin)):
    clause, params = "", []
    if area_id and area_id != "all":
        clause, params = " WHERE area_id = ?", [area_id]
    with session() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM qa_log{clause}", params).fetchone()[0]
        distinct = conn.execute(
            f"SELECT COUNT(DISTINCT TRIM(question)) FROM qa_log{clause}",
            params).fetchone()[0]
        today_clause = "date(created_at)=date('now','localtime')"
        if clause:
            today_clause += " AND area_id = ?"
        today = conn.execute(
            f"SELECT COUNT(*) FROM qa_log WHERE {today_clause}", params).fetchone()[0]
        hot_rows = rows(conn, f"""
            SELECT TRIM(question) AS q, COUNT(*) AS count
            FROM qa_log{clause}
            GROUP BY TRIM(question)
            ORDER BY count DESC, q
            LIMIT ?
        """, params + [limit])
        return {"total": total, "distinct": distinct, "today": today,
                "rows": hot_rows}


@router.delete("/stats/hot")
def clear_hot(area_id: str | None = None, _: str = Depends(require_admin)):
    with session() as conn:
        if area_id and area_id != "all":
            cur = conn.execute("DELETE FROM qa_log WHERE area_id=?", (area_id,))
        else:
            cur = conn.execute("DELETE FROM qa_log")
        return {"deleted": cur.rowcount}


# ---------------- 纠错反馈（F4 的管理侧） ----------------

@router.get("/feedback")
def list_feedback(status: str | None = None, _: str = Depends(require_admin)):
    clause, params = "", []
    if status and status != "all":
        clause, params = " WHERE f.status = ?", [status]
    with session() as conn:
        return rows(conn, f"""
            SELECT f.*, q.question, q.answer, q.area_id
            FROM feedback f LEFT JOIN qa_log q ON q.id = f.qa_id
            {clause}
            ORDER BY f.created_at DESC, f.id DESC
        """, params)


@router.patch("/feedback/{feedback_id}")
def patch_feedback(feedback_id: int, body: FeedbackPatch,
                   _: str = Depends(require_admin)):
    if body.status not in {"pending", "resolved", "rejected"}:
        raise HTTPException(status_code=400, detail="状态取值不合法")
    with session() as conn:
        found = conn.execute(
            "SELECT id FROM feedback WHERE id=?", (feedback_id,)).fetchone()
        if not found:
            raise HTTPException(status_code=404, detail="反馈不存在")
        conn.execute(
            """UPDATE feedback SET status=?, note=?,
                   resolved_at=CASE WHEN ?='pending' THEN NULL
                                    ELSE datetime('now','localtime') END
               WHERE id=?""",
            (body.status, body.note, body.status, feedback_id))
        return dict(conn.execute(
            "SELECT * FROM feedback WHERE id=?", (feedback_id,)).fetchone())


# ---------------- 只读辅助 ----------------

@router.get("/meta")
def meta(_: str = Depends(require_admin)):
    return {
        "embedding": embedding_info(),
        "doc_types": sorted(DOC_TYPES),
        "chunk_status": sorted(CHUNK_STATUS),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
