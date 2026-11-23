# -*- coding: utf-8 -*-
"""游客端 / AI 接入侧的公开 API。

提供检索、单轮问答、多轮问答与流式回答，用于让检索热词、问答日志、
命中溯源有真实数据。MCP / 密钥配额等接口后续在此扩展。

多轮会话的约定：客户端在响应里拿到 session_id，后续请求带上同一个值；
历史从 qa_log 同 session_id 且已有 answer 的行取最近若干轮，不额外建表。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import get_config
from app.db import rows, session
from app.services.llm import generate_answer, stream_answer
from app.services.retrieval import retrieve_for_answer, search

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public", tags=["游客端 / AI 接入"])

VALID_SOURCES = {"web", "doubao", "api"}


class SearchIn(BaseModel):
    area_id: str
    q: str = Field(min_length=1, max_length=500)
    top_k: int | None = Field(default=None, ge=1, le=20)
    source: str = "web"


class AskIn(SearchIn):
    session_id: str | None = Field(
        default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class FeedbackIn(BaseModel):
    qa_id: int
    content: str = Field(min_length=1, max_length=2000)


class SatisfiedIn(BaseModel):
    satisfied: bool | None = None


def _resolve_source(conn: sqlite3.Connection, request: Request, declared: str) -> str:
    key = request.headers.get("x-api-key", "").strip()
    if key:
        found = conn.execute(
            "SELECT id, client_name FROM api_key WHERE key=? AND status='active'",
            (key,)).fetchone()
        if not found:
            raise HTTPException(status_code=401, detail="API 密钥无效")
        conn.execute(
            "UPDATE api_key SET last_used_at=datetime('now','localtime') WHERE id=?",
            (found["id"],))
        return "api"
    return declared if declared in VALID_SOURCES else "web"


def _log_qa(conn: sqlite3.Connection, *, area_id: str, source: str, ip: str,
            question: str, answer: str | None, model: str, latency_ms: int,
            hits: list[dict], session_id: str = "") -> int:
    cur = conn.execute(
        """INSERT INTO qa_log
           (area_id, source, ip, session_id, question, answer, model, latency_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (area_id, source, ip, session_id, question, answer, model, latency_ms))
    qa_id = int(cur.lastrowid)
    if hits:
        conn.executemany(
            """INSERT OR IGNORE INTO qa_log_chunk (qa_id, chunk_id, rank, score)
               VALUES (?, ?, ?, ?)""",
            [(qa_id, hit["chunk_id"], rank, hit["score"])
             for rank, hit in enumerate(hits, start=1)])
    return qa_id


def _chat_limits() -> tuple[int, int]:
    chat = getattr(get_config(), "chat", None)
    turns = int(getattr(chat, "history_turns", 5) or 5)
    max_chars = int(getattr(chat, "max_history_chars", 4000) or 4000)
    return max(0, turns), max(0, max_chars)


def _chat_history(conn: sqlite3.Connection, session_id: str) -> list[dict]:
    """取同一会话最近若干轮的问答，转成 messages；超长时从最旧的轮次开始裁。"""
    turns, max_chars = _chat_limits()
    if not session_id or turns <= 0:
        return []
    found = conn.execute(
        """SELECT question, answer FROM qa_log
           WHERE session_id=? AND answer IS NOT NULL AND length(answer)>0
           ORDER BY id DESC LIMIT ?""",
        (session_id, turns)).fetchall()
    messages: list[dict] = []
    for row in reversed(found):
        messages.append({"role": "user", "content": row["question"]})
        messages.append({"role": "assistant", "content": row["answer"]})
    total = sum(len(item["content"]) for item in messages)
    while len(messages) > 2 and total > max_chars:
        total -= len(messages[0]["content"]) + len(messages[1]["content"])
        messages = messages[2:]
    return messages


def _resolve_session(value: str | None) -> str:
    return value or uuid.uuid4().hex


def _check_area(conn: sqlite3.Connection, area_id: str) -> dict:
    area = conn.execute(
        "SELECT id, name, tag, intro FROM scenic_area WHERE id=?", (area_id,)).fetchone()
    if not area:
        raise HTTPException(status_code=404, detail="景区不存在")
    return dict(area)


def _citations(hits: list[dict]) -> list[dict]:
    return [
        {"chunk_id": hit["chunk_id"], "title": hit["title"],
         "doc_name": hit["doc_name"], "score": hit["score"]}
        for hit in hits
    ]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _finish_stream(qa_id: int, answer: str, model: str, latency_ms: int) -> None:
    """流式结束后回写日志；一个字都没生成则删除占位日志，避免污染热词统计。"""
    with session() as conn:
        if answer:
            conn.execute(
                "UPDATE qa_log SET answer=?, model=?, latency_ms=? WHERE id=?",
                (answer, model, latency_ms, qa_id))
        else:
            conn.execute("DELETE FROM qa_log WHERE id=?", (qa_id,))


@router.get("/areas")
def public_areas():
    with session() as conn:
        return rows(conn, """
            SELECT a.id, a.name, a.tag, a.intro,
                   (SELECT COUNT(*) FROM attraction t WHERE t.area_id = a.id) AS attractions,
                   (SELECT COUNT(*) FROM knowledge_chunk c
                     WHERE c.area_id = a.id AND c.status='approved') AS chunks
            FROM scenic_area a ORDER BY a.created_at, a.id
        """)


@router.get("/areas/{area_id}/attractions")
def area_attractions(area_id: str):
    with session() as conn:
        _check_area(conn, area_id)
        return rows(conn, """
            SELECT id, name, location, params, core_function, culture,
                   highlights, performance_info, remark
            FROM attraction WHERE area_id=? ORDER BY sort_order
        """, (area_id,))


@router.get("/attractions/{attraction_id}")
def attraction_detail(attraction_id: str):
    with session() as conn:
        found = conn.execute(
            "SELECT * FROM attraction WHERE id=?", (attraction_id,)).fetchone()
        if not found:
            raise HTTPException(status_code=404, detail="景点不存在")
        data = dict(found)
        data["performances"] = rows(conn, """
            SELECT show_time, duration_min, note FROM performance
            WHERE attraction_id=? ORDER BY show_time
        """, (attraction_id,))
        return data


@router.get("/chunks/{chunk_id}")
def public_chunk(chunk_id: int):
    with session() as conn:
        found = conn.execute("""
            SELECT c.id, c.title, c.content, c.attraction_id, c.area_id,
                   d.name AS doc_name
            FROM knowledge_chunk c JOIN knowledge_doc d ON d.id = c.doc_id
            WHERE c.id=? AND c.status='approved'
        """, (chunk_id,)).fetchone()
        if not found:
            raise HTTPException(status_code=404, detail="知识块不存在或已下架")
        return dict(found)


@router.post("/search")
def public_search(body: SearchIn, request: Request):
    with session() as conn:
        _check_area(conn, body.area_id)
        started = time.perf_counter()
        hits = search(conn, body.area_id, body.q, top_k=body.top_k, min_score=0.0)
        latency = int((time.perf_counter() - started) * 1000)
        source = _resolve_source(conn, request, body.source)
        qa_id = _log_qa(
            conn, area_id=body.area_id, source=source,
            ip=request.client.host if request.client else "",
            question=body.q, answer=None, model="search",
            latency_ms=latency, hits=hits)
        return {"qa_id": qa_id, "hits": hits, "took_ms": latency}


@router.post("/ask")
def public_ask(body: AskIn, request: Request):
    with session() as conn:
        area = _check_area(conn, body.area_id)
        started = time.perf_counter()
        session_id = _resolve_session(body.session_id)
        history = _chat_history(conn, session_id)
        hits = retrieve_for_answer(conn, body.area_id, body.q, top_k=body.top_k)
        answer, model = generate_answer(body.q, hits, history)
        latency = int((time.perf_counter() - started) * 1000)
        source = _resolve_source(conn, request, body.source)
        qa_id = _log_qa(
            conn, area_id=body.area_id, source=source,
            ip=request.client.host if request.client else "",
            question=body.q, answer=answer, model=model,
            latency_ms=latency, hits=hits, session_id=session_id)
        return {
            "qa_id": qa_id,
            "session_id": session_id,
            "area": area,
            "answer": answer,
            "model": model,
            "hits": hits,
            "citations": _citations(hits),
            "took_ms": latency,
        }


@router.post("/ask/stream")
def public_ask_stream(body: AskIn, request: Request):
    """SSE 流式问答：meta（会话与引用）→ delta（增量文本）→ done（完整答案）。"""
    with session() as conn:
        _check_area(conn, body.area_id)
        started = time.perf_counter()
        session_id = _resolve_session(body.session_id)
        history = _chat_history(conn, session_id)
        hits = retrieve_for_answer(conn, body.area_id, body.q, top_k=body.top_k)
        source = _resolve_source(conn, request, body.source)
        qa_id = _log_qa(
            conn, area_id=body.area_id, source=source,
            ip=request.client.host if request.client else "",
            question=body.q, answer=None, model="stream",
            latency_ms=0, hits=hits, session_id=session_id)
        citations = _citations(hits)

    def event_stream():
        parts: list[str] = []
        model = "extractive"
        finished = False
        try:
            yield _sse("meta", {
                "qa_id": qa_id,
                "session_id": session_id,
                "citations": citations,
            })
            for kind, payload in stream_answer(body.q, hits, history):
                if kind == "delta":
                    parts.append(payload)
                    yield _sse("delta", {"text": payload})
                elif kind == "done":
                    model = payload

            answer = "".join(parts).strip()
            latency = int((time.perf_counter() - started) * 1000)
            _finish_stream(qa_id, answer, model, latency)
            finished = True
            yield _sse("done", {
                "qa_id": qa_id,
                "session_id": session_id,
                "answer": answer,
                "model": model,
                "took_ms": latency,
            })
        except Exception:  # noqa: BLE001 生成异常不能留下半截日志或裸连接
            logger.exception("流式问答异常 qa_id=%s", qa_id)
            answer = "".join(parts).strip()
            latency = int((time.perf_counter() - started) * 1000)
            _finish_stream(qa_id, answer, model, latency)
            finished = True
            yield _sse("error", {"detail": "生成失败，请重试"})
        finally:
            # 客户端提前断开时 Starlette 会关闭生成器，这里补写已有内容
            if not finished:
                _finish_stream(
                    qa_id, "".join(parts).strip(), model,
                    int((time.perf_counter() - started) * 1000))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/feedback", status_code=201)
def submit_feedback(body: FeedbackIn):
    with session() as conn:
        qa = conn.execute("SELECT id FROM qa_log WHERE id=?", (body.qa_id,)).fetchone()
        if not qa:
            raise HTTPException(status_code=404, detail="关联问答不存在")
        cur = conn.execute(
            "INSERT INTO feedback (qa_id, content) VALUES (?, ?)",
            (body.qa_id, body.content.strip()))
        return {"id": int(cur.lastrowid), "status": "pending"}


@router.patch("/qa/{qa_id}")
def update_satisfied(qa_id: int, body: SatisfiedIn):
    """游客点“有帮助/没帮助”时回写 qa_log.satisfied。"""
    with session() as conn:
        found = conn.execute("SELECT id FROM qa_log WHERE id=?", (qa_id,)).fetchone()
        if not found:
            raise HTTPException(status_code=404, detail="问答记录不存在")
        value = None if body.satisfied is None else (1 if body.satisfied else 0)
        conn.execute("UPDATE qa_log SET satisfied=? WHERE id=?", (value, qa_id))
        return {"id": qa_id, "satisfied": body.satisfied}
