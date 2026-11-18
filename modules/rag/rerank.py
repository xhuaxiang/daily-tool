"""R2 重排：用 bge-reranker 对候选块按“问题-原文”相关性重新打分。

向量检索快但粗，rerank 慢但准，所以只对召回的前 N 条做。
接口失败时退回原顺序，问答不因此中断。
"""

from __future__ import annotations

import logging
import os
import time

import requests

logger = logging.getLogger("news")

DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"
DEFAULT_TIMEOUT = 20.0
MAX_DOC_CHARS = 2000
_RETRY_STATUS = {429, 500, 502, 503, 504}


class RerankError(RuntimeError):
    """重排接口失败。"""


def rerank_settings(config: dict | None = None) -> dict:
    config = config or {}
    rag = config.get("rag", config)
    if not isinstance(rag, dict):
        rag = {}
    rerank = rag.get("rerank", {})
    if not isinstance(rerank, dict):
        rerank = {}
    return {
        "enabled": bool(rerank.get("enabled", True)),
        "base_url": (
            os.environ.get("RERANK_BASE_URL")
            or rerank.get("base_url", DEFAULT_BASE_URL)
        ).rstrip("/"),
        "model": os.environ.get("RERANK_MODEL") or rerank.get("model", DEFAULT_MODEL),
        "timeout": float(rerank.get("timeout", DEFAULT_TIMEOUT)),
    }


def _api_key() -> str:
    # 同一家服务商的 key 通常共用，没有单独的 RERANK_API_KEY 就复用 embedding 的
    return os.environ.get("RERANK_API_KEY", "").strip() or os.environ.get(
        "EMBEDDING_API_KEY", ""
    ).strip()


def _doc_text(chunk: dict) -> str:
    """把中文标题带上：问题多是中文，英文正文单独不足以让重排模型判断。"""
    parts = (chunk.get("title_zh"), chunk.get("title"), chunk.get("text"))
    return " ".join(" ".join(part.split()) for part in parts if part)


def rerank_chunks(
    question: str,
    chunks: list[dict],
    *,
    top_n: int | None = None,
    config: dict | None = None,
) -> list[dict]:
    """返回按相关性降序的块；任何异常都退回原顺序。"""
    if not chunks:
        return []
    settings = rerank_settings(config)
    if not settings["enabled"]:
        return chunks[:top_n] if top_n else chunks

    api_key = _api_key()
    if not api_key:
        logger.warning("RERANK_API_KEY / EMBEDDING_API_KEY 未设置，跳过重排")
        return chunks[:top_n] if top_n else chunks

    documents = [
        _doc_text(chunk)[:MAX_DOC_CHARS] for chunk in chunks
    ]
    payload = {
        "model": settings["model"],
        "query": question,
        "documents": documents,
        "top_n": top_n or len(chunks),
        "return_documents": False,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = f"{settings['base_url']}/rerank"

    data = None
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.post(
                url, headers=headers, json=payload, timeout=settings["timeout"]
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5 * (2 ** attempt))
                continue
            break

        if response.status_code in _RETRY_STATUS:
            last_error = RerankError(
                f"rerank API HTTP {response.status_code}: {response.text[:200]}"
            )
            if attempt < 2:
                time.sleep(0.5 * (2 ** attempt))
                continue
            break

        if response.status_code >= 400:
            logger.warning(
                "rerank API HTTP %s，退回原顺序：%s",
                response.status_code, response.text[:200],
            )
            return chunks[:top_n] if top_n else chunks

        try:
            data = response.json()
        except ValueError:
            logger.warning("rerank API 返回非 JSON，退回原顺序")
            return chunks[:top_n] if top_n else chunks
        break

    if not isinstance(data, dict):
        logger.warning("rerank 调用失败，退回原顺序：%s", last_error)
        return chunks[:top_n] if top_n else chunks

    results = data.get("results")
    if not isinstance(results, list):
        logger.warning("rerank 返回缺少 results，退回原顺序")
        return chunks[:top_n] if top_n else chunks

    ranked = []
    for item in results:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int) or not 0 <= index < len(chunks):
            continue
        chunk = dict(chunks[index])
        chunk["score"] = round(float(item.get("relevance_score", 0.0)), 4)
        chunk["reranked"] = True
        ranked.append(chunk)
    if not ranked:
        return chunks[:top_n] if top_n else chunks
    return ranked[:top_n] if top_n else ranked
