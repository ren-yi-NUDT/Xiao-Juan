# -*- coding: utf-8 -*-
"""景区智搜后台入口。

    uvicorn app.main:app --reload --port 8765
    管理端：http://127.0.0.1:8765/admin
    接口文档：http://127.0.0.1:8765/docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR, get_config
from app.db import init_db
from app.routers import admin, public
from app.services.embedding import embedding_info

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("xiaojuan")

WEB_DIR = BASE_DIR / "web"


@asynccontextmanager
async def lifespan(_: FastAPI):
    db_path = init_db()
    logger.info("数据库就绪：%s", db_path)
    logger.info("向量化：%s", embedding_info())
    yield


app = FastAPI(
    title="景区智搜 · 后台 API",
    description="景区知识 RAG 数据库：景区 / 景点 / 文档 / 知识块 / 问答日志。",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin.router)
app.include_router(public.router)


@app.get("/health")
def health():
    return {"ok": True, "service": "景区智搜后台", "embedding": embedding_info()}


@app.get("/")
def root():
    return RedirectResponse(url="/admin")


@app.get("/admin")
def admin_page():
    return FileResponse(WEB_DIR / "admin.html")


@app.get("/visitor")
def visitor_page():
    return FileResponse(WEB_DIR / "visitor.html")


if WEB_DIR.exists():
    app.mount("/web", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
