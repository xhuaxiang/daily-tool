"""R0 建索引：归档 JSON → 切块 → embedding → SQLite。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from modules.rag.chunking import chunks_for_articles
from modules.rag.embedding import (
    EmbeddingCache,
    embed_texts,
    embedding_settings,
    model_key,
)
from modules.rag.store import IndexStore

logger = logging.getLogger("news")


def find_archive_files(inputs: list[str | Path]) -> list[Path]:
    """把文件/目录输入展开成 articles-*.json 列表。"""
    paths: list[Path] = []
    for item in inputs:
        path = Path(item)
        if path.is_dir():
            paths.extend(sorted(path.rglob("articles-*.json")))
        elif path.is_file():
            paths.append(path)
        else:
            raise FileNotFoundError(f"找不到输入路径：{path}")
    return list(dict.fromkeys(paths))


def load_articles(paths: list[Path]) -> list[dict]:
    """读取全文归档；同一 id 只保留最后一次出现的版本。"""
    by_id: dict[str, dict] = {}
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        articles = data.get("articles") if isinstance(data, dict) else None
        if not isinstance(articles, list):
            raise ValueError(f"{path} 不是 articles-*.json 归档格式")
        for article in articles:
            if not isinstance(article, dict):
                continue
            key = (
                article.get("id")
                or article.get("link")
                or article.get("title")
                or str(len(by_id))
            )
            by_id[str(key)] = article
    return list(by_id.values())


def build_index(
    articles: list[dict],
    *,
    db_path: str | Path,
    config: dict | None = None,
    chunk_size: int | None = None,
    overlap: int | None = None,
    rebuild: bool = False,
    limit: int = 0,
) -> dict:
    """切块、embedding 并写入 SQLite；返回统计信息。"""
    rag = (config or {}).get("rag", {})
    if not isinstance(rag, dict):
        rag = {}
    chunk_size = int(
        chunk_size if chunk_size is not None else rag.get("chunk_size", 800)
    )
    overlap = int(
        overlap if overlap is not None else rag.get("chunk_overlap", 100)
    )
    if limit > 0:
        articles = articles[:limit]

    chunks = chunks_for_articles(
        articles, max_chars=chunk_size, overlap=overlap
    )
    settings = embedding_settings(config)
    model = model_key(settings)
    stats = {
        "articles": len(articles),
        "chunks": len(chunks),
        "model": model,
        "dim": 0,
        "db": str(db_path),
        "rebuilt": rebuild,
    }

    store = IndexStore(db_path)
    cache = EmbeddingCache(db_path)
    try:
        if rebuild:
            store.clear()
        if not chunks:
            return stats

        vectors = embed_texts(
            [chunk["text"] for chunk in chunks],
            config=config,
            cache=cache,
        )
        if vectors and vectors[0]:
            stats["dim"] = len(vectors[0])
        rows = [
            {**chunk, "model": model, "vector": vector}
            for chunk, vector in zip(chunks, vectors)
        ]
        stored = store.upsert_chunks(rows)
        stats["stored"] = stored
        stats["total_in_db"] = store.count()
    finally:
        cache.close()
        store.close()

    logger.info(
        "RAG index: %d articles, %d chunks, %d dims, db=%s",
        stats["articles"], stats["chunks"], stats["dim"], db_path,
    )
    return stats
