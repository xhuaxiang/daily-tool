"""R2 混合检索：向量 + 关键词，Reciprocal Rank Fusion 合并。

RRF 只看排名不看分数，省得把余弦相似度和 BM25 分数硬凑到一起。
"""

from __future__ import annotations

DEFAULT_K = 60


def rrf_fuse(result_lists: list[list[dict]], *, k: int = DEFAULT_K,
             top_n: int | None = None) -> list[dict]:
    """多路结果按 1/(k+rank) 累加，k 越大越平滑。"""
    if k <= 0:
        raise ValueError("RRF k must be positive")

    scores: dict[str, float] = {}
    chunks: dict[str, dict] = {}
    for results in result_lists:
        for rank, chunk in enumerate(results, 1):
            chunk_id = chunk.get("chunk_id")
            if not chunk_id:
                continue
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
            chunks.setdefault(chunk_id, chunk)

    order = sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)
    if top_n is not None:
        order = order[:max(0, top_n)]

    fused = []
    for chunk_id in order:
        chunk = dict(chunks[chunk_id])
        chunk["score"] = round(scores[chunk_id], 6)
        fused.append(chunk)
    return fused
