# -*- coding: utf-8 -*-
import json

import pytest
import requests

from scripts import rag_client
from scripts.rag_client import RagClient, RagError


class FakeResponse:
    def __init__(self, lines, status_code=200, text="", chunk_size=7):
        # 模拟真实网络：把 SSE 按很小的字节块切开，覆盖 UTF-8 多字节跨块的情况
        self._body = ("\n".join(lines) + "\n").encode("utf-8")
        self._chunk_size = chunk_size
        self.status_code = status_code
        self.text = text
        self.closed = False

    def iter_content(self, chunk_size=1024):
        step = self._chunk_size
        for i in range(0, len(self._body), step):
            yield self._body[i:i + step]

    def close(self):
        self.closed = True


def _sse(*frames):
    lines = []
    for event, payload in frames:
        lines.append(f"event: {event}")
        lines.append("data: " + json.dumps(payload, ensure_ascii=False))
        lines.append("")
    return lines


def _patch_post(monkeypatch, resp=None, exc=None, captured=None):
    def fake_post(url, json=None, stream=None, timeout=None):
        if captured is not None:
            captured.append({"url": url, "json": json, "timeout": timeout})
        if exc is not None:
            raise exc
        return resp

    monkeypatch.setattr(rag_client.requests, "post", fake_post)


def test_sse_meta_delta_done_parsed(monkeypatch):
    resp = FakeResponse(_sse(
        ("meta", {"qa_id": 1, "session_id": "s1",
                  "citations": [{"chunk_id": 7, "title": "灵山大佛"}]}),
        ("delta", {"text": "灵山"}),
        ("delta", {"text": "大佛"}),
        ("done", {"qa_id": 1, "session_id": "s1", "answer": "灵山大佛通高八十八米。",
                  "model": "extractive", "took_ms": 12}),
    ))
    _patch_post(monkeypatch, resp=resp)
    deltas = []
    answer = RagClient("http://127.0.0.1:8765", area_id="lingshan").ask(
        "灵山大佛有多高", on_delta=deltas.append)

    assert answer.answer == "灵山大佛通高八十八米。"
    assert answer.session_id == "s1"
    assert answer.citations[0]["title"] == "灵山大佛"
    assert answer.model == "extractive" and answer.took_ms == 12
    assert deltas == ["灵山", "大佛"]
    assert resp.closed is True


def test_error_event_raises_rag_error(monkeypatch):
    resp = FakeResponse(_sse(("error", {"detail": "生成失败，请重试"})))
    _patch_post(monkeypatch, resp=resp)
    with pytest.raises(RagError, match="生成失败"):
        RagClient("http://127.0.0.1:8765").ask("你好")


def test_connection_error_raises_rag_error(monkeypatch):
    _patch_post(monkeypatch, exc=requests.ConnectionError("refused"))
    with pytest.raises(RagError, match="无法连接"):
        RagClient("http://127.0.0.1:8765", connect_retries=0).ask("你好")


def test_connection_error_retried_then_succeeds(monkeypatch):
    calls = []
    resp = FakeResponse(_sse(
        ("done", {"qa_id": 1, "session_id": "s", "answer": "答", "model": "m"}),
    ))

    def fake_post(url, json=None, stream=None, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise requests.ConnectionError("refused")
        return resp

    monkeypatch.setattr(rag_client.requests, "post", fake_post)
    answer = RagClient("http://127.0.0.1:8765", connect_retries=1,
                       connect_retry_delay=0).ask("你好")
    assert answer.answer == "答"
    assert len(calls) == 2


def test_http_error_raises_rag_error(monkeypatch):
    resp = FakeResponse([], status_code=422, text='{"detail":"bad"}')
    _patch_post(monkeypatch, resp=resp)
    with pytest.raises(RagError, match="HTTP 422"):
        RagClient("http://127.0.0.1:8765").ask("你好")


def test_eof_without_done_raises(monkeypatch):
    resp = FakeResponse(_sse(("delta", {"text": "半句"})))
    _patch_post(monkeypatch, resp=resp)
    with pytest.raises(RagError, match="未收到 done"):
        RagClient("http://127.0.0.1:8765").ask("你好")


def test_session_id_reused_across_calls(monkeypatch):
    captured = []
    resp = FakeResponse(_sse(
        ("meta", {"qa_id": 1, "session_id": "fixed", "citations": []}),
        ("done", {"qa_id": 1, "session_id": "fixed", "answer": "答", "model": "m"}),
    ))
    _patch_post(monkeypatch, resp=resp, captured=captured)
    client = RagClient("http://127.0.0.1:8765", session_id="fixed")
    client.ask("问1")
    _patch_post(monkeypatch, resp=FakeResponse(_sse(
        ("done", {"qa_id": 2, "session_id": "fixed", "answer": "答", "model": "m"}),
    )), captured=captured)
    client.ask("问2")

    assert captured[0]["json"]["session_id"] == "fixed"
    assert captured[1]["json"]["session_id"] == "fixed"
    assert captured[0]["json"]["area_id"] == "lingshan"
    assert captured[0]["json"]["q"] == "问1"
    assert captured[0]["url"].endswith("/api/public/ask/stream")


def test_long_question_truncated_to_backend_limit(monkeypatch):
    captured = []
    resp = FakeResponse(_sse(
        ("done", {"qa_id": 1, "session_id": "s", "answer": "答", "model": "m"}),
    ))
    _patch_post(monkeypatch, resp=resp, captured=captured)
    RagClient("http://127.0.0.1:8765").ask("灵" * 800)
    assert len(captured[0]["json"]["q"]) == rag_client.MAX_Q_CHARS


def test_health_returns_none_when_unreachable(monkeypatch):
    def boom(url, timeout=None):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(rag_client.requests, "get", boom)
    assert RagClient("http://127.0.0.1:8765").health() is None


def test_invalid_session_id_sanitized():
    client = RagClient("http://127.0.0.1:8765", session_id=" bad id! ")
    assert client.session_id == "badid"


def test_empty_session_id_generated():
    client = RagClient("http://127.0.0.1:8765", session_id="")
    assert len(client.session_id) == 32
