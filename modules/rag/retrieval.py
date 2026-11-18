"""R2 检索入口：向量 / 关键词 / 混合，可选 rerank。

tools/ask.py 和 tools/eval_retrieval.py 都走这里，保证评测和线上同一套逻辑。
"""

from __future__ import annotations

from modules.rag.hybrid import rrf_fuse
from modules.rag.keyword import BM25Index
from modules.rag.rerank import rerank_chunks
from modules.rag.store import IndexStore

MODES = ("vector", "keyword", "hybrid")
DEFAULT_MODE = "hybrid"
DEFAULT_CANDIDATES = 20


class Retriever:
    """包一层 IndexStore；关键词索引首次使用时才建，建完复用。"""

    def __init__(self, store: IndexStore, *, config: dict | None = None):
        self.store = store
        self.config = config or {}
        self.model = store.latest_model()
        self._keyword: BM25Index | None = None

    @property
    def keyword_index(self) -> BM25Index:
        if self._keyword is None:
            self._keyword = BM25Index(self.store.all_chunks(self.model))
        return self._keyword

    def search(
        self,
        question: str,
        query_vector: list[float],
        *,
        top_k: int = 5,
        mode: str = DEFAULT_MODE,
        candidates: int = DEFAULT_CANDIDATES,
        rerank: bool = False,
    ) -> list[dict]:
        if mode not in MODES:
            raise ValueError(f"unknown retrieval mode: {mode}")
        if top_k <= 0:
            return []
        pool = max(top_k, candidates) if rerank else top_k

        vector_hits: list[dict] = []
        keyword_hits: list[dict] = []
        if mode in ("vector", "hybrid"):
            vector_hits = self.store.search(query_vector, top_k=pool, model=self.model)
        if mode in ("keyword", "hybrid"):
            keyword_hits = self.keyword_index.search(question, top_k=pool)

        if mode == "vector":
            results = vector_hits
        elif mode == "keyword":
            results = keyword_hits
        else:
            if vector_hits and keyword_hits:
                results = rrf_fuse([vector_hits, keyword_hits], top_n=pool)
            else:
                results = vector_hits or keyword_hits

        if rerank and results:
            return rerank_chunks(question, results, top_n=top_k, config=self.config)
        return results[:top_k]
