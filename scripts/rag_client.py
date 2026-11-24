# -*- coding: utf-8 -*-
"""rag_backend HTTP 客户端（语音前端与问答后端解耦）。

契约见 rag_backend 分支：
  POST /api/public/ask/stream  (SSE)
    meta  {"qa_id", "session_id", "citations": [...]}
    delta {"text": "..."}
    done  {"qa_id", "session_id", "answer", "model", "took_ms"}
    error {"detail": "..."}

本模块只负责把一次问答变成 RagAnswer；后端不可达/超时/断流统一抛 RagError，
由 LMAMApp 决定如何降级播报。
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field

import requests

log = logging.getLogger("lmam.rag")

MAX_Q_CHARS = 500  # 后端 AskIn.q 限制 1..500


class RagError(Exception):
    """问答后端调用失败（网络、超时、SSE error 事件、断流）。"""


@dataclass
class RagAnswer:
    answer: str
    session_id: str = ""
    citations: list = field(default_factory=list)
    model: str = ""
    took_ms: int = 0


class RagClient:
    """调用 rag_backend 的 /api/public/ask/stream，维护多轮 session_id。"""

    def __init__(self, api_base: str, area_id: str = "lingshan",
                 timeout_sec: float = 15.0, session_id: str = "",
                 top_k: int | None = None, connect_retries: int = 1,
                 connect_retry_delay: float = 0.2):
        self.api_base = (api_base or "").rstrip("/")
        self.area_id = area_id or "lingshan"
        self.timeout_sec = float(timeout_sec)
        self.session_id = self._normalize_session(session_id)
        self.top_k = top_k
        self.connect_retries = max(0, int(connect_retries))
        self.connect_retry_delay = max(0.0, float(connect_retry_delay))

    @staticmethod
    def _normalize_session(session_id: str) -> str:
        """后端 session_id 只允许 [A-Za-z0-9_-] 且 ≤64；非法值清洗，空则新建。"""
        sid = re.sub(r"[^A-Za-z0-9_-]", "", (session_id or "").strip())[:64]
        return sid or uuid.uuid4().hex

    # ---------- 对外接口 ----------
    def health(self) -> dict | None:
        """探活；不可达返回 None（--check 只提示，不失败）。"""
        try:
            resp = requests.get(f"{self.api_base}/health", timeout=2)
            if resp.status_code == 200:
                return resp.json()
            log.debug("[rag] /health HTTP %s", resp.status_code)
        except Exception as e:  # noqa: BLE001
            log.debug("[rag] /health 不可达: %s", e)
        return None

    def ask(self, text: str, on_delta=None) -> RagAnswer:
        """问一句，返回完整回答。on_delta(token) 可用于边收边播。"""
        q = (text or "").strip()
        if not q:
            raise RagError("问题为空")
        if len(q) > MAX_Q_CHARS:
            q = q[:MAX_Q_CHARS]

        body = {
            "area_id": self.area_id,
            "q": q,
            "session_id": self.session_id,
        }
        if self.top_k:
            body["top_k"] = int(self.top_k)

        url = f"{self.api_base}/api/public/ask/stream"
        attempts = self.connect_retries + 1
        resp = None
        for attempt in range(attempts):
            try:
                resp = requests.post(
                    url, json=body, stream=True, timeout=(3, self.timeout_sec))
                break
            except requests.ConnectionError as e:
                # 只对“根本没连上”重试；已发出请求后的读超时不重试，避免后端重复记 qa_log
                if attempt + 1 < attempts:
                    log.warning("[rag] 连接失败，重试 %d/%d: %s",
                                attempt + 1, attempts - 1, e)
                    time.sleep(self.connect_retry_delay)
                    continue
                raise RagError(f"无法连接知识库服务: {e}") from e
            except requests.RequestException as e:
                raise RagError(f"请求知识库失败: {e}") from e
        if resp is None:  # 理论不可达
            raise RagError("知识库请求未发出")

        try:
            if resp.status_code != 200:
                detail = ""
                try:
                    detail = (resp.text or "")[:300]
                except Exception:  # noqa: BLE001
                    pass
                raise RagError(f"知识库服务返回 HTTP {resp.status_code}: {detail}")
            return self._consume_sse(resp, on_delta)
        finally:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass

    # ---------- SSE ----------
    def _consume_sse(self, resp, on_delta) -> RagAnswer:
        deltas: list[str] = []
        session_id = self.session_id
        citations: list = []
        event = ""
        data_lines: list[str] = []
        done: dict | None = None

        def dispatch() -> bool:
            """处理一个 SSE 帧；返回 True 表示遇到 done/error，应停止。"""
            nonlocal event, data_lines, session_id, citations, done
            if not data_lines and not event:
                return False
            raw = "\n".join(data_lines).strip()
            ev = event.strip()
            event, data_lines = "", []
            if not raw:
                return False
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as e:
                raise RagError(f"SSE 数据不是合法 JSON: {raw[:200]}") from e

            if ev == "meta":
                session_id = str(payload.get("session_id") or session_id)
                citations = payload.get("citations") or []
            elif ev == "delta":
                piece = str(payload.get("text") or "")
                if piece:
                    deltas.append(piece)
                    if on_delta is not None:
                        try:
                            on_delta(piece)
                        except Exception as e:  # noqa: BLE001
                            log.warning("[rag] on_delta 回调异常: %s", e)
            elif ev == "done":
                done = payload
                return True
            elif ev == "error":
                raise RagError(str(payload.get("detail") or "生成失败"))
            return False

        def feed_line(line: str) -> bool:
            """喂入一行；返回 True 表示应停止读取。"""
            nonlocal event
            if line == "":
                return dispatch()
            if line.startswith(":"):
                return False  # SSE 注释/心跳
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].lstrip(" "))
            return False

        # 自己按字节切行并统一按 UTF-8 解码：requests 的 iter_lines(decode_unicode=True)
        # 会按响应头猜编码，中文 SSE 可能被拆坏/乱码。
        buf = b""
        stopped = False
        try:
            for chunk in resp.iter_content(chunk_size=1024):
                if not chunk:
                    continue
                buf += chunk
                while b"\n" in buf:
                    raw_line, buf = buf.split(b"\n", 1)
                    line = raw_line.rstrip(b"\r").decode("utf-8", errors="replace")
                    if feed_line(line):
                        stopped = True
                        break
                if stopped:
                    break
            if not stopped and buf:
                feed_line(buf.rstrip(b"\r").decode("utf-8", errors="replace"))
        except RagError:
            raise
        except requests.RequestException as e:
            raise RagError(f"知识库响应中断: {e}") from e

        # 容错：最后一帧没有以空行收尾
        if done is None and data_lines:
            dispatch()

        if done is None:
            raise RagError("知识库响应异常结束（未收到 done 事件）")

        answer = str(done.get("answer") or "".join(deltas)).strip()
        if not answer:
            raise RagError("知识库返回了空回答")

        self.session_id = str(done.get("session_id") or session_id)
        log.info("[rag] area=%s session=%s model=%s took_ms=%s citations=%s",
                 self.area_id, self.session_id, done.get("model", ""),
                 done.get("took_ms", ""),
                 [c.get("title") or c.get("doc_name") for c in citations][:5])
        return RagAnswer(
            answer=answer,
            session_id=self.session_id,
            citations=citations,
            model=str(done.get("model") or ""),
            took_ms=int(done.get("took_ms") or 0),
        )


def _cli() -> int:
    """独立调试入口：python -m scripts.rag_client --ask "灵山大佛有多高" """
    import argparse
    import os
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    parser = argparse.ArgumentParser(description="rag_backend 问答客户端")
    parser.add_argument("--base", default=os.environ.get("XJ_RAG_BASE", "http://127.0.0.1:8765"))
    parser.add_argument("--area", default=os.environ.get("XJ_RAG_AREA", "lingshan"))
    parser.add_argument("--session", default="", help="复用会话 id；空=新建")
    parser.add_argument("--ask", action="append", default=[], help="问题，可重复")
    parser.add_argument("--health", action="store_true", help="只探活")
    args = parser.parse_args()

    client = RagClient(args.base, area_id=args.area, session_id=args.session)
    if args.health or not args.ask:
        print("health:", client.health())
        if not args.ask:
            return 0
    for q in args.ask:
        try:
            ans = client.ask(q)
        except RagError as e:
            print(f"Q: {q}\nERROR: {e}")
            return 1
        print(f"Q: {q}\nA({ans.model}, {ans.took_ms}ms): {ans.answer}")
        titles = [c.get("title") or c.get("doc_name") for c in ans.citations]
        print("citations:", titles)
    print("session:", client.session_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
