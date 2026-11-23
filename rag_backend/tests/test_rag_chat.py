# -*- coding: utf-8 -*-
"""多轮会话、流式回答与大模型降级的测试（临时库，不访问网络）。"""
from __future__ import annotations

import json
import uuid

from fastapi.testclient import TestClient

import app.routers.public as public
import app.services.llm as llm
from app.main import app

DOC_TEXT = ("灵山胜境开放时间为 8:30 到 17:30。\n\n"
            "门票价格为 210 元，儿童半价。")


def _login(client: TestClient) -> dict:
    response = client.post(
        "/api/admin/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["token"]}


def _approved_area(client: TestClient) -> str:
    headers = _login(client)
    area = client.post(
        "/api/admin/areas", headers=headers,
        json={"name": f"会话测试景区-{uuid.uuid4().hex[:8]}", "tag": "pytest"}).json()
    area_id = area["id"]
    doc = client.post(
        "/api/admin/docs", headers=headers,
        data={"area_id": area_id, "name": "会话测试.txt", "doc_type": "long_doc"},
        files={"file": ("会话测试.txt", DOC_TEXT.encode("utf-8"), "text/plain")}).json()
    chunks = client.get(
        f"/api/admin/docs/{doc['id']}/chunks", headers=headers).json()
    for chunk in chunks:
        response = client.patch(
            f"/api/admin/chunks/{chunk['id']}", headers=headers,
            json={"status": "approved"})
        assert response.status_code == 200
    return area_id


def test_ask_keeps_session_and_reuses_history(monkeypatch):
    captured: list[list[dict]] = []

    def fake_answer(question, hits, history=None):
        captured.append(list(history or []))
        return f"回答{len(captured)}", "fake-model"

    monkeypatch.setattr(public, "generate_answer", fake_answer)

    with TestClient(app) as client:
        area_id = _approved_area(client)
        first = client.post(
            "/api/public/ask",
            json={"area_id": area_id, "q": "门票多少钱"}).json()
        assert first["session_id"] and first["model"] == "fake-model"

        second = client.post(
            "/api/public/ask",
            json={"area_id": area_id, "q": "开放到几点",
                  "session_id": first["session_id"]}).json()
        assert second["session_id"] == first["session_id"]

        third = client.post(
            "/api/public/ask",
            json={"area_id": area_id, "q": "儿童票呢"}).json()
        assert third["session_id"] != first["session_id"]

    assert captured[0] == []
    assert {"role": "user", "content": "门票多少钱"} in captured[1]
    assert any(item["role"] == "assistant" and item["content"] == "回答1"
               for item in captured[1])


def test_invalid_session_id_is_rejected():
    with TestClient(app) as client:
        area_id = _approved_area(client)
        response = client.post(
            "/api/public/ask",
            json={"area_id": area_id, "q": "门票", "session_id": "bad id!"})
        assert response.status_code == 422


def test_stream_ask_sends_sse_and_logs_answer():
    with TestClient(app) as client:
        area_id = _approved_area(client)
        with client.stream(
                "POST", "/api/public/ask/stream",
                json={"area_id": area_id, "q": "门票多少钱"}) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            body = "".join(response.iter_text())

    events: list[tuple[str, dict]] = []
    for block in body.strip().split("\n\n"):
        name = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: "):].strip()
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if name:
            events.append((name, data or {}))

    names = [name for name, _ in events]
    assert names[0] == "meta"
    assert "delta" in names
    assert names[-1] == "done"
    done = events[-1][1]
    assert done["session_id"]
    assert "210" in done["answer"]


def test_generate_answer_falls_back_when_llm_fails(monkeypatch):
    monkeypatch.setattr(llm, "is_configured", lambda: True)
    monkeypatch.setattr(llm, "_settings", lambda: {
        "api_base": "https://example.invalid/v1", "api_key": "k",
        "model": "fake-model", "timeout": 1, "temperature": 0.0,
        "max_tokens": 16,
    })

    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(llm, "_chat", boom)
    answer, model = llm.generate_answer(
        "门票多少钱", [{"title": "票务", "content": "门票 210 元"}])
    assert model == "extractive"
    assert "210" in answer


def test_stream_answer_yields_deltas_and_done(monkeypatch):
    monkeypatch.setattr(llm, "is_configured", lambda: True)
    monkeypatch.setattr(llm, "_settings", lambda: {
        "api_base": "https://example.invalid/v1", "api_key": "k",
        "model": "fake-model", "timeout": 1, "temperature": 0.0,
        "max_tokens": 16,
    })
    monkeypatch.setattr(
        llm, "_stream_chat", lambda settings, messages: iter(["门票", "210 元"]))

    events = list(llm.stream_answer(
        "门票多少钱", [{"title": "票务", "content": "门票 210 元"}]))
    assert ("delta", "门票") in events
    assert events[-1] == ("done", "fake-model")
