"""R0 embedding 封装：OpenAI 兼容 API、SQLite 缓存、离线 hash 调试。

真实使用需要 EMBEDDING_API_KEY；hash provider 只用于离线跑通流程，
不具备语义检索能力。
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import random
import sqlite3
import time
from array import array
from datetime import datetime, timezone
from pathlib import Path

import requests

logger = logging.getLogger("news")

DEFAULT_PROVIDER = "openai-compatible"
DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_MODEL = "BAAI/bge-m3"
DEFAULT_BATCH_SIZE = 32
DEFAULT_TIMEOUT = 30.0
_RETRY_STATUS = {429, 500, 502, 503, 504}
_HASH_DIM = 256
_warned_hash = False


class EmbeddingError(RuntimeError):
    """embedding 调用或配置失败。"""


def embedding_settings(config: dict | None = None) -> dict:
    """从 config.json / 环境变量解析 embedding 配置。"""
    config = config or {}
    rag = config.get("rag", config)
    if not isinstance(rag, dict):
        rag = {}
    embedding = rag.get("embedding", rag)
    if not isinstance(embedding, dict):
        embedding = {}

    provider = (
        os.environ.get("EMBEDDING_PROVIDER")
        or embedding.get("provider", DEFAULT_PROVIDER)
    )
    base_url = (
        os.environ.get("EMBEDDING_BASE_URL")
        or embedding.get("base_url", DEFAULT_BASE_URL)
    ).rstrip("/")
    model = os.environ.get("EMBEDDING_MODEL") or embedding.get("model", DEFAULT_MODEL)
    return {
        "provider": str(provider),
        "base_url": base_url,
        "model": str(model),
        "batch_size": max(1, int(embedding.get("batch_size", DEFAULT_BATCH_SIZE))),
        "timeout": float(embedding.get("timeout", DEFAULT_TIMEOUT)),
    }


def model_key(settings: dict | None = None) -> str:
    """缓存/索引使用的模型标识，包含 base_url，避免不同服务同名模型串用。"""
    settings = settings or embedding_settings()
    if settings["provider"] == "hash":
        return f"hash:{_HASH_DIM}"
    return f"{settings['base_url']}|{settings['model']}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class EmbeddingCache:
    """按 (model, text) 缓存向量，存 SQLite BLOB。"""

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS embedding_cache (
                text_hash TEXT PRIMARY KEY,
                model TEXT NOT NULL,
                dim INTEGER NOT NULL,
                vector BLOB NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    @staticmethod
    def _hash(text: str, model: str) -> str:
        return hashlib.sha256(f"{model}\0{text}".encode("utf-8")).hexdigest()

    def get(self, text: str, model: str) -> list[float] | None:
        row = self.conn.execute(
            "SELECT vector, dim FROM embedding_cache WHERE text_hash = ?",
            (self._hash(text, model),),
        ).fetchone()
        if not row:
            return None
        values = array("f")
        values.frombytes(row[0])
        if len(values) != row[1]:
            logger.warning("Embedding cache dimension mismatch, ignoring entry")
            return None
        return values.tolist()

    def put(self, text: str, model: str, vector: list[float]) -> None:
        self.put_many([(text, model, vector)])

    def put_many(self, items: list[tuple[str, str, list[float]]]) -> None:
        rows = []
        for text, model, vector in items:
            values = array("f", vector)
            rows.append((
                self._hash(text, model),
                model,
                len(values),
                values.tobytes(),
                _now(),
            ))
        if not rows:
            return
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO embedding_cache
            (text_hash, model, dim, vector, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.conn.commit()

    def count(self, model: str | None = None) -> int:
        if model:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM embedding_cache WHERE model = ?", (model,)
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()
        return int(row[0])

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "EmbeddingCache":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def _hash_vector(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    values = [rng.uniform(-1.0, 1.0) for _ in range(_HASH_DIM)]
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [value / norm for value in values]


def _request_embeddings(texts: list[str], settings: dict) -> list[list[float]]:
    api_key = os.environ.get("EMBEDDING_API_KEY", "").strip()
    if not api_key:
        raise EmbeddingError(
            "EMBEDDING_API_KEY 未设置；设置后重试，"
            "或临时使用 provider=hash 跑通流程"
        )

    url = f"{settings['base_url']}/embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": settings["model"], "input": texts}

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=settings["timeout"],
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5 * (2 ** attempt))
                continue
            break

        if response.status_code in _RETRY_STATUS:
            last_error = EmbeddingError(
                f"embedding API HTTP {response.status_code}: {response.text[:200]}"
            )
            if attempt < 2:
                time.sleep(0.5 * (2 ** attempt))
                continue
            break

        if response.status_code >= 400:
            raise EmbeddingError(
                f"embedding API HTTP {response.status_code}: {response.text[:200]}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise EmbeddingError("embedding API 返回非 JSON") from exc

        items = data.get("data")
        if not isinstance(items, list) or len(items) != len(texts):
            raise EmbeddingError(
                f"embedding API 返回数量不匹配：期望 {len(texts)}，"
                f"实际 {len(items) if isinstance(items, list) else '非列表'}"
            )

        if all(isinstance(item, dict) and "index" in item for item in items):
            items = sorted(items, key=lambda item: item["index"])

        vectors = []
        for item in items:
            vector = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(vector, list) or not vector:
                raise EmbeddingError("embedding API 返回空向量")
            vectors.append([float(value) for value in vector])

        dim = len(vectors[0])
        if any(len(vector) != dim for vector in vectors):
            raise EmbeddingError("embedding API 返回向量维度不一致")
        return vectors

    raise EmbeddingError(f"embedding API 调用失败: {last_error}")


def embed_texts(
    texts: list[str],
    *,
    config: dict | None = None,
    cache: EmbeddingCache | None = None,
) -> list[list[float]]:
    """批量生成 embedding；有 cache 时优先读缓存。"""
    global _warned_hash
    if not texts:
        return []

    settings = embedding_settings(config)
    if settings["provider"] == "hash":
        if not _warned_hash:
            logger.warning(
                "Using hash embeddings for offline debugging; "
                "they carry no semantic meaning"
            )
            _warned_hash = True
        return [_hash_vector(str(text)) for text in texts]

    if settings["provider"] != "openai-compatible":
        raise EmbeddingError(
            f"不支持的 embedding provider: {settings['provider']}；"
            "当前支持 openai-compatible / hash"
        )

    model = model_key(settings)
    vectors: list[list[float] | None] = [None] * len(texts)
    pending: list[int] = []
    for index, text in enumerate(texts):
        text = str(text or "").strip()
        if not text:
            raise EmbeddingError("embedding 文本为空")
        cached = cache.get(text, model) if cache else None
        if cached is None:
            pending.append(index)
        else:
            vectors[index] = cached

    batch_size = settings["batch_size"]
    for start in range(0, len(pending), batch_size):
        indices = pending[start:start + batch_size]
        batch = [str(texts[index]).strip() for index in indices]
        batch_vectors = _request_embeddings(batch, settings)
        for index, vector in zip(indices, batch_vectors):
            vectors[index] = vector
        if cache:
            cache.put_many([
                (str(texts[index]).strip(), model, vectors[index])
                for index in indices
            ])

    if any(vector is None for vector in vectors):
        raise EmbeddingError("embedding 结果缺失")
    logger.info(
        "Embedded %d texts (%d cached, model=%s)",
        len(texts), len(texts) - len(pending), model,
    )
    return [list(vector) for vector in vectors]
