"""R0 SQLite 索引：chunk 元数据 + float32 向量。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    article_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL DEFAULT '',
    title_zh TEXT NOT NULL DEFAULT '',
    link TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    publisher TEXT NOT NULL DEFAULT '',
    published TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    event_id TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_model ON chunks(model);
CREATE INDEX IF NOT EXISTS idx_chunks_article ON chunks(article_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class IndexStore:
    """SQLite 索引；向量用 numpy 做余弦检索，不依赖向量数据库。"""

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def upsert_chunks(self, rows: list[dict]) -> int:
        prepared = []
        now = _now()
        for row in rows:
            vector = np.asarray(row["vector"], dtype=np.float32)
            if vector.ndim != 1 or vector.size == 0:
                raise ValueError(f"invalid vector for chunk {row.get('chunk_id')}")
            prepared.append((
                row["chunk_id"],
                row["article_id"],
                int(row.get("chunk_index", 0)),
                int(row.get("chunk_count", 1)),
                row.get("title", ""),
                row.get("title_zh", ""),
                row.get("link", ""),
                row.get("source", ""),
                row.get("publisher", ""),
                row.get("published", ""),
                row.get("category", ""),
                row.get("event_id", ""),
                row["text"],
                row["model"],
                int(vector.size),
                vector.tobytes(),
                now,
            ))
        if not prepared:
            return 0
        self.conn.executemany(
            """
            INSERT INTO chunks (
                chunk_id, article_id, chunk_index, chunk_count,
                title, title_zh, link, source, publisher, published,
                category, event_id, text, model, dim, vector, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chunk_id) DO UPDATE SET
                article_id = excluded.article_id,
                chunk_index = excluded.chunk_index,
                chunk_count = excluded.chunk_count,
                title = excluded.title,
                title_zh = excluded.title_zh,
                link = excluded.link,
                source = excluded.source,
                publisher = excluded.publisher,
                published = excluded.published,
                category = excluded.category,
                event_id = excluded.event_id,
                text = excluded.text,
                model = excluded.model,
                dim = excluded.dim,
                vector = excluded.vector,
                created_at = excluded.created_at
            """,
            prepared,
        )
        self.conn.commit()
        return len(prepared)

    def count(self, model: str | None = None) -> int:
        if model:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE model = ?", (model,)
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return int(row[0])

    def models(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT model FROM chunks ORDER BY model"
        ).fetchall()
        return [row["model"] for row in rows]

    def latest_model(self) -> str:
        row = self.conn.execute(
            "SELECT model FROM chunks ORDER BY created_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
        return row["model"] if row else ""

    def clear(self) -> None:
        self.conn.execute("DELETE FROM chunks")
        self.conn.commit()

    def search(
        self,
        query_vector: list[float],
        *,
        top_k: int = 5,
        model: str | None = None,
    ) -> list[dict]:
        if top_k <= 0:
            return []
        selected_model = model or self.latest_model()
        if not selected_model:
            return []

        rows = self.conn.execute(
            "SELECT * FROM chunks WHERE model = ?", (selected_model,)
        ).fetchall()
        if not rows:
            return []

        vectors = np.stack([
            np.frombuffer(row["vector"], dtype=np.float32)
            for row in rows
        ])
        query = np.asarray(query_vector, dtype=np.float32).reshape(-1)
        if vectors.shape[1] != query.size:
            raise ValueError(
                f"query dimension {query.size} != index dimension {vectors.shape[1]}"
            )

        query_norm = float(np.linalg.norm(query))
        if query_norm == 0:
            raise ValueError("query vector is zero")
        norms = np.linalg.norm(vectors, axis=1)
        scores = (vectors @ query) / (norms * query_norm + 1e-12)

        order = np.argsort(-scores)[:top_k]
        results = []
        for index in order:
            row = rows[int(index)]
            results.append({
                "chunk_id": row["chunk_id"],
                "article_id": row["article_id"],
                "chunk_index": row["chunk_index"],
                "chunk_count": row["chunk_count"],
                "title": row["title"],
                "title_zh": row["title_zh"],
                "link": row["link"],
                "source": row["source"],
                "publisher": row["publisher"],
                "published": row["published"],
                "category": row["category"],
                "event_id": row["event_id"],
                "text": row["text"],
                "score": float(scores[int(index)]),
            })
        return results

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "IndexStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
