# -*- coding: utf-8 -*-
"""pytest 环境：使用临时配置与临时数据库，不碰 data/xiaojuan.db。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="xj_test_"))
os.environ["XJ_CONFIG"] = str(_TMP / "config.yaml")
(_TMP / "config.yaml").write_text(f"""
app:
  host: "127.0.0.1"
  port: 0
  secret: "test-secret"
  admin_user: "admin"
  admin_password: "admin"
  db_path: "{( _TMP / 'test.db').as_posix()}"
  upload_dir: "{( _TMP / 'uploads').as_posix()}"
  token_hours: 1
embedding:
  provider: "hash"
  dim: 256
  bge_model_path: ""
  device: "cpu"
llm:
  api_base: ""
  api_key: ""
  model: ""
  timeout_sec: 5
retrieval:
  top_k: 5
  min_score: 0.05
chunking:
  max_chars: 500
  pair_sentences: true
seed:
  package_dir: ""
""", encoding="utf-8")

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _database():
    from app.config import get_config
    get_config.cache_clear()
    from app.db import init_db
    init_db()
    yield
