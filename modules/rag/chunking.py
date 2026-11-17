"""R0 文本切块：把归档文章切成可嵌入、可引用的片段。"""

from __future__ import annotations

import re

from modules.snapshot import article_id

_SENTENCE_RE = re.compile(r"(?<=[。！？!?；;])|(?<=[.!?])\s+")
_PUNCT_END = "。！？!?；;"


def _join(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    if left[-1] in _PUNCT_END:
        return left + right
    return f"{left} {right}"


def _hard_split(text: str, max_chars: int, overlap: int) -> list[str]:
    """没有句子边界时按字符硬切，保留少量重叠。"""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def chunk_text(text: str, max_chars: int = 800, overlap: int = 100) -> list[str]:
    """按段落/句子切块，单块不超过 max_chars，块间保留少量重叠。"""
    max_chars = max(100, int(max_chars))
    overlap = max(0, min(int(overlap), max_chars // 2))

    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    for paragraph in re.split(r"\n+", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        for sentence in _SENTENCE_RE.split(paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) > max_chars:
                pieces.extend(_hard_split(sentence, max_chars, overlap))
            else:
                pieces.append(sentence)

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = _join(current, piece)
        if len(candidate) <= max_chars:
            current = candidate
            continue

        chunks.append(current)
        tail = current[-overlap:].lstrip() if overlap else ""
        if tail and len(_join(tail, piece)) <= max_chars:
            current = _join(tail, piece)
        else:
            current = piece

    if current.strip():
        chunks.append(current.strip())
    return [chunk for chunk in chunks if chunk]


def article_chunks(
    article: dict,
    *,
    max_chars: int = 800,
    overlap: int = 100,
) -> list[dict]:
    """把一篇文章切成带元数据的 chunk 列表。"""
    text = (
        article.get("text")
        or article.get("full_text")
        or article.get("snippet")
        or ""
    ).strip()
    if not text:
        return []

    article_key = article.get("id") or article_id(article)
    pieces = chunk_text(text, max_chars=max_chars, overlap=overlap)
    total = len(pieces)
    rows = []
    for index, piece in enumerate(pieces):
        rows.append({
            "chunk_id": f"{article_key}#{index}",
            "article_id": article_key,
            "chunk_index": index,
            "chunk_count": total,
            "title": article.get("title", ""),
            "title_zh": article.get("title_zh", ""),
            "link": article.get("link", ""),
            "source": article.get("source", ""),
            "publisher": article.get("publisher", ""),
            "published": article.get("published") or article.get("pub_date", ""),
            "category": article.get("category", ""),
            "event_id": article.get("event_id", ""),
            "text": piece,
        })
    return rows


def chunks_for_articles(
    articles: list[dict],
    *,
    max_chars: int = 800,
    overlap: int = 100,
) -> list[dict]:
    chunks: list[dict] = []
    for article in articles:
        chunks.extend(
            article_chunks(article, max_chars=max_chars, overlap=overlap)
        )
    return chunks
