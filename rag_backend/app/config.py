# -*- coding: utf-8 -*-
"""config.yaml 加载。

沿用 lmam 分支约定：yaml 顶层分组 -> 同名属性，配置集中、代码里不写死路径。
相对路径以 rag_backend/ 为基准解析。
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent  # rag_backend/
DEFAULT_CONFIG_PATH = BASE_DIR / "config.yaml"

REQUIRED_GROUPS = ("app", "embedding", "retrieval", "llm", "chunking")


class Section:
    """一段配置，键 -> 属性。"""

    def __init__(self, data: dict):
        for key, value in (data or {}).items():
            setattr(self, key, value)

    def get(self, key, default=None):
        return getattr(self, key, default)


class Config:
    def __init__(self, data: dict):
        self.raw = dict(data)
        for key, value in self.raw.items():
            if isinstance(value, dict):
                setattr(self, key, Section(value))
            else:
                setattr(self, key, value)
        self._resolve_paths()

    def _resolve_paths(self):
        def resolve(relative: str) -> str:
            if not relative:
                return ""
            path = Path(relative)
            return str(path if path.is_absolute() else (BASE_DIR / path).resolve())

        if hasattr(self, "app"):
            self.app.db_path = resolve(getattr(self.app, "db_path", "data/xiaojuan.db"))
            self.app.upload_dir = resolve(getattr(self.app, "upload_dir", "data/uploads"))
        if hasattr(self, "embedding"):
            self.embedding.bge_model_path = resolve(
                getattr(self.embedding, "bge_model_path", ""))
        seed = getattr(self, "seed", None)
        if seed is not None:
            seed.package_dir = resolve(getattr(seed, "package_dir", ""))

    def get(self, key, default=None):
        return self.raw.get(key, default)


def load_config(path: str | os.PathLike | None = None) -> Config:
    config_path = Path(path or os.environ.get("XJ_CONFIG") or DEFAULT_CONFIG_PATH)
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or not data:
        raise ValueError(f"配置文件为空或格式不对: {config_path}")
    missing = [key for key in REQUIRED_GROUPS if key not in data]
    if missing:
        raise KeyError(f"config.yaml 缺少必填分组: {missing}")
    return Config(data)


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config()
