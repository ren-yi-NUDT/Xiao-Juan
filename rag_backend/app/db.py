# -*- coding: utf-8 -*-
"""SQLite 连接与初始化。

每张表都定义在 schema.sql 里，方便直接作为课程交付的建表 SQL。
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.config import get_config

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path: str | None = None) -> sqlite3.Connection:
    db_path = path or get_config().app.db_path
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """对已有库做增量迁移（幂等）。

    schema.sql 使用 CREATE IF NOT EXISTS，旧库不会自动获得新列，
    因此新增字段必须在这里补 ALTER，保证 `python scripts/seed.py` 升级老库可用。
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(qa_log)")}
    if not columns:
        return
    if "session_id" not in columns:
        conn.execute("ALTER TABLE qa_log ADD COLUMN session_id TEXT DEFAULT ''")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qa_session ON qa_log(session_id, id)")


def init_db(path: str | None = None) -> str:
    """建表 + 迁移（幂等），返回数据库路径。"""
    db_path = path or get_config().app.db_path
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        migrate(conn)
        conn.commit()
    finally:
        conn.close()
    return db_path


@contextmanager
def session(path: str | None = None):
    """一次业务操作一个连接：正常提交，异常回滚。"""
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows(conn: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def row(conn: sqlite3.Connection, sql: str, params=()) -> dict | None:
    found = conn.execute(sql, params).fetchone()
    return dict(found) if found else None
