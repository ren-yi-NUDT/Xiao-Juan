# -*- coding: utf-8 -*-
"""管理端 / 公开 API 的端到端测试（临时库）。"""
from fastapi.testclient import TestClient

from app.main import app


def _headers(client: TestClient) -> dict:
    response = client.post(
        "/api/admin/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["token"]}


def test_login_rejects_wrong_password():
    with TestClient(app) as client:
        response = client.post(
            "/api/admin/login", json={"username": "admin", "password": "bad"})
        assert response.status_code == 401
        assert client.get("/api/admin/areas").status_code == 401


def test_admin_upload_review_search_delete_flow():
    with TestClient(app) as client:
        headers = _headers(client)

        area = client.post(
            "/api/admin/areas", headers=headers,
            json={"name": "接口测试景区", "tag": "pytest"}).json()
        area_id = area["id"]

        content = ("景区开放时间为 8:30 到 17:30。\n\n"
                   "门票价格为 80 元，儿童半价。")
        response = client.post(
            "/api/admin/docs", headers=headers,
            data={"area_id": area_id, "name": "接口测试.txt", "doc_type": "long_doc"},
            files={"file": ("接口测试.txt", content.encode("utf-8"), "text/plain")})
        assert response.status_code == 201
        doc = response.json()
        assert doc["status"] == "pending"
        assert doc["chunk_count"] >= 2

        chunks = client.get(
            f"/api/admin/docs/{doc['id']}/chunks", headers=headers).json()
        assert chunks and all(chunk["status"] == "pending" for chunk in chunks)

        # 待审核的知识块不会出现在游客端检索里
        before = client.post(
            "/api/public/search", json={"area_id": area_id, "q": "门票多少钱"}).json()
        assert before["hits"] == []

        for chunk in chunks:
            response = client.patch(
                f"/api/admin/chunks/{chunk['id']}", headers=headers,
                json={"status": "approved"})
            assert response.status_code == 200

        doc_after = client.get(
            "/api/admin/docs", headers=headers, params={"area_id": area_id}).json()
        assert doc_after[0]["status"] == "approved"

        search = client.post(
            "/api/public/search", json={"area_id": area_id, "q": "门票多少钱"}).json()
        assert search["hits"]
        assert any("80" in hit["content"] for hit in search["hits"])

        ask = client.post(
            "/api/public/ask", json={"area_id": area_id, "q": "门票多少钱"}).json()
        assert ask["answer"] and ask["citations"]

        # 游客端“有帮助 / 有误纠错”两条反馈路径
        qa_id = ask["qa_id"]
        response = client.patch(
            f"/api/public/qa/{qa_id}", json={"satisfied": True})
        assert response.status_code == 200 and response.json()["satisfied"] is True
        response = client.post(
            "/api/public/feedback",
            json={"qa_id": qa_id, "content": "用户对这条回答点击了有误"})
        assert response.status_code == 201 and response.json()["status"] == "pending"

        hot = client.get(
            "/api/admin/stats/hot", headers=headers, params={"area_id": area_id}).json()
        assert hot["total"] >= 2
        assert any(row["q"] == "门票多少钱" for row in hot["rows"])

        # 编辑知识块 -> 重新向量化
        chunk_id = search["hits"][0]["chunk_id"]
        response = client.patch(
            f"/api/admin/chunks/{chunk_id}", headers=headers,
            json={"content": "门票价格为 100 元，儿童免费。"})
        assert response.status_code == 200
        assert "100" in response.json()["content"]

        # 删除景区：文档、知识块、问答日志一并清理
        assert client.delete(
            f"/api/admin/areas/{area_id}", headers=headers).status_code == 200
        assert client.get(
            "/api/admin/docs", headers=headers, params={"area_id": area_id}).json() == []
        assert client.post(
            "/api/public/search", json={"area_id": area_id, "q": "门票"}).status_code == 404


def test_upload_rejects_duplicate_name():
    with TestClient(app) as client:
        headers = _headers(client)
        area = client.post(
            "/api/admin/areas", headers=headers,
            json={"name": "重复文档景区"}).json()
        payload = {"area_id": area["id"], "name": "同名.txt", "doc_type": "long_doc"}
        files = {"file": ("同名.txt", "内容。".encode("utf-8"), "text/plain")}
        assert client.post("/api/admin/docs", headers=headers,
                           data=payload, files=files).status_code == 201
        assert client.post("/api/admin/docs", headers=headers,
                           data=payload, files=files).status_code == 409
