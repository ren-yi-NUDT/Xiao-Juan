# -*- coding: utf-8 -*-
"""可插拔向量化。

- provider = hash：内置字/词哈希向量，纯 numpy，无需模型，开箱即跑。
- provider = bge：配置 bge_model_path 后启用 sentence-transformers 真语义向量；
  依赖缺失时自动降级回 hash，并在 /api/meta 里说明。

两种提供方输出统一为 L2 归一化的 float32 向量，存进 knowledge_chunk.vector。
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

import numpy as np

from app.config import get_config

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-zA-Z0-9]+")
_CJK_RE = re.compile(r"[一-鿿]")


class HashEmbedding:
    """字符 uni/bi-gram + 英文数字词的哈希向量（feature hashing）。

    对中文口语问句与资料原文的用词重合敏感，适合作课程演示的零依赖基线。
    """

    def __init__(self, dim: int = 512):
        self.dim = int(dim)
        self.name = f"hash-{self.dim}"

    def _features(self, text: str) -> dict[str, float]:
        text = (text or "").lower()
        chars = _CJK_RE.findall(text)
        feats: dict[str, float] = {}
        for i, ch in enumerate(chars):
            feats[f"u:{ch}"] = feats.get(f"u:{ch}", 0.0) + 0.5
            if i + 1 < len(chars):
                bigram = chars[i] + chars[i + 1]
                feats[f"b:{bigram}"] = feats.get(f"b:{bigram}", 0.0) + 1.0
        for word in _WORD_RE.findall(text):
            feats[f"w:{word}"] = feats.get(f"w:{word}", 0.0) + 1.0
        return feats

    def encode(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dim, dtype=np.float32)
        for token, weight in self._features(text).items():
            digest = hashlib.md5(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "little") % self.dim
            vector[index] += weight
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector /= norm
        return vector

    def encode_many(self, texts: list[str]) -> list[np.ndarray]:
        return [self.encode(t) for t in texts]


class BGEEmbedding:
    """真实语义向量（BAAI/bge 系列），接口与 HashEmbedding 一致。"""

    def __init__(self, model_path: str, device: str = "cpu"):
        from sentence_transformers import SentenceTransformer  # 可选依赖

        self.model = SentenceTransformer(model_path, device=device)
        self.name = f"bge:{Path(model_path).name}"
        self.dim = int(self.model.get_sentence_embedding_dimension())

    def encode(self, text: str) -> np.ndarray:
        vector = self.model.encode(
            [text or ""], normalize_embeddings=True, convert_to_numpy=True)[0]
        return np.asarray(vector, dtype=np.float32)

    def encode_many(self, texts: list[str]) -> list[np.ndarray]:
        vectors = self.model.encode(
            texts or [""], normalize_embeddings=True, convert_to_numpy=True)
        return [np.asarray(v, dtype=np.float32) for v in vectors]


_embedder = None
_status = {"provider": "hash", "model": "hash-512", "dim": 512, "message": ""}


def _build_embedder():
    global _status
    cfg = get_config().embedding
    provider = str(getattr(cfg, "provider", "hash")).lower()
    if provider == "bge":
        model_path = getattr(cfg, "bge_model_path", "")
        if not model_path or not Path(model_path).exists():
            _status = {"provider": "hash", "model": "hash-512", "dim": 512,
                       "message": "bge 模型路径不存在，已降级为 hash 轻量向量"}
            logger.warning(_status["message"])
            return HashEmbedding(512)
        try:
            embedder = BGEEmbedding(model_path, getattr(cfg, "device", "cpu"))
            _status = {"provider": "bge", "model": embedder.name,
                       "dim": embedder.dim, "message": "真语义向量已启用"}
            return embedder
        except Exception as exc:  # 依赖缺失 / 模型加载失败
            _status = {"provider": "hash", "model": "hash-512", "dim": 512,
                       "message": f"bge 加载失败，已降级为 hash：{exc}"}
            logger.warning(_status["message"])
            return HashEmbedding(512)

    dim = int(getattr(cfg, "dim", 512) or 512)
    _status = {"provider": "hash", "model": f"hash-{dim}", "dim": dim,
               "message": "内置轻量向量（无需模型）"}
    return HashEmbedding(dim)


def get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = _build_embedder()
    return _embedder


def embedding_info() -> dict:
    embedder = get_embedder()
    return {**_status, "model": embedder.name, "dim": embedder.dim}


def to_blob(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def cosine(query: np.ndarray, vector: np.ndarray) -> float:
    if query.shape != vector.shape:
        return 0.0
    # 双方都已归一化，点积即余弦
    return float(np.dot(query, vector))
