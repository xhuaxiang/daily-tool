"""事件聚类 v0：不依赖 embedding，把同一事件的多源报道合并。

核心是保守匹配：标题词重叠 + 序列相似度，再用数字/日期做守卫。
宁可漏合并，也不要把不同事件误合并。
"""

from __future__ import annotations

import email.utils
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'%.-]*")
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?%?\b")
_DATE_WORD_RE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
    r"monday|mon|tuesday|tue|wednesday|wed|thursday|thu|"
    r"friday|fri|saturday|sat|sunday|sun)\b",
    re.I,
)
_DATE_CANON = {
    "jan": "january", "feb": "february", "mar": "march", "apr": "april",
    "jun": "june", "jul": "july", "aug": "august", "sep": "september",
    "sept": "september", "oct": "october", "nov": "november", "dec": "december",
    "mon": "monday", "tue": "tuesday", "wed": "wednesday", "thu": "thursday",
    "fri": "friday", "sat": "saturday", "sun": "sunday",
}

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "by", "from", "at", "as", "is", "are", "was", "were", "be", "been",
    "being", "this", "that", "these", "those", "it", "its", "he", "she",
    "they", "we", "you", "i", "his", "her", "their", "our", "your", "not",
    "no", "but", "if", "then", "than", "so", "up", "down", "out", "over",
    "under", "after", "before", "about", "into", "onto", "off", "again",
    "more", "most", "less", "least", "new", "says", "said", "say", "will",
    "would", "could", "should", "may", "might", "can", "has", "have", "had",
    "do", "does", "did", "who", "what", "when", "where", "why", "how", "amp",
}

_ALIASES = [
    (re.compile(r"\bfed\b"), "federal reserve"),
    (re.compile(r"\bfomc\b"), "federal reserve"),
    (re.compile(r"\bbps\b"), "basis points"),
    (re.compile(r"\becb\b"), "european central bank"),
    (re.compile(r"\bboe\b"), "bank of england"),
    (re.compile(r"\bboj\b"), "bank of japan"),
]


def _parse_datetime(pub_date: str) -> datetime | None:
    if not pub_date:
        return None
    try:
        return email.utils.parsedate_to_datetime(pub_date)
    except (ValueError, TypeError):
        pass
    try:
        return datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _normalize_title(title: str) -> str:
    text = (title or "").casefold()
    for pattern, replacement in _ALIASES:
        text = pattern.sub(replacement, text)
    text = re.sub(r"[^a-z0-9%\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(title: str) -> set[str]:
    return {
        token for token in _TOKEN_RE.findall(_normalize_title(title))
        if len(token) > 1 and token not in _STOPWORDS
    }


def _numbers(title: str) -> set[str]:
    return {
        number.rstrip("%")
        for number in _NUMBER_RE.findall((title or "").casefold())
    }


def _date_tokens(title: str) -> set[str]:
    return {
        _DATE_CANON.get(word.casefold(), word.casefold())
        for word in _DATE_WORD_RE.findall(title or "")
    }


def _compatible(a: dict, b: dict) -> bool:
    """数字/日期不一致时禁止合并，避免把不同数据或不同日期的事件串起来。"""
    nums_a, nums_b = _numbers(a.get("title", "")), _numbers(b.get("title", ""))
    if nums_a and nums_b and nums_a != nums_b:
        return False
    dates_a, dates_b = _date_tokens(a.get("title", "")), _date_tokens(b.get("title", ""))
    if dates_a and dates_b and dates_a != dates_b:
        return False
    return True


def _similarity(a: dict, b: dict) -> float:
    if not _compatible(a, b):
        return 0.0
    tokens_a, tokens_b = _tokens(a.get("title", "")), _tokens(b.get("title", ""))
    if not tokens_a or not tokens_b:
        return 0.0
    shared = tokens_a & tokens_b
    jaccard = len(shared) / len(tokens_a | tokens_b)
    sequence = SequenceMatcher(
        None, _normalize_title(a.get("title", "")), _normalize_title(b.get("title", ""))
    ).ratio()
    score = max(jaccard, sequence * 0.9)

    # 同一数字 + 至少 3 个共同实词，基本是同一事件的改写标题。
    # 典型：Anthropic $1.4 trillion IPO vs Anthropic $1.4 trillion valuation IPO
    numbers_a, numbers_b = _numbers(a.get("title", "")), _numbers(b.get("title", ""))
    if (
        numbers_a and numbers_a == numbers_b
        and len(shared) >= 3
        and any(len(token) >= 5 for token in shared)
    ):
        score = max(score, 0.62)
    return score


def _article_time(article: dict) -> datetime | None:
    return _aware(_parse_datetime(article.get("pub_date", "")))


def _within_window(article: dict, event: dict, window_hours: int) -> bool:
    article_time = _article_time(article)
    event_time = _article_time(event["representative"])
    if article_time is None or event_time is None:
        return True
    return abs(article_time - event_time) <= timedelta(hours=window_hours)


def cluster_events(
    articles: list[dict],
    window_hours: int = 36,
    threshold: float = 0.58,
    max_cluster: int = 5,
) -> list[dict]:
    """把文章聚成事件，原地写入 `_event_id` / `_event`，返回事件列表。"""
    ordered = sorted(
        articles,
        key=lambda art: _article_time(art) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    events: list[dict] = []

    for article in ordered:
        best_event = None
        best_score = 0.0
        for event in events:
            if len(event["articles"]) >= max_cluster:
                continue
            if not _within_window(article, event, window_hours):
                continue
            score = _similarity(article, event["representative"])
            if score > best_score:
                best_event, best_score = event, score

        if best_event is not None and best_score >= threshold:
            best_event["articles"].append(article)
        else:
            # 代表文章固定为事件中最新的一篇，避免窗口随合并漂移
            events.append({"articles": [article], "representative": article})

    for index, event in enumerate(events, 1):
        event["event_id"] = f"e{index}"
        event["sources"] = sorted({
            art.get("publisher") or art.get("source") or "unknown"
            for art in event["articles"]
        })
        event["coverage"] = len(event["sources"])
        times = [t for t in (_article_time(art) for art in event["articles"]) if t]
        event["latest"] = max(times) if times else None
        for article in event["articles"]:
            article["_event_id"] = event["event_id"]
            article["_event"] = {
                "event_id": event["event_id"],
                "coverage": event["coverage"],
                "sources": event["sources"],
            }

    return events
