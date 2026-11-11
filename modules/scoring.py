"""P1 选稿评分：把“重要性/信息量/来源/时效/噪音”拆成可解释信号。

第一版不调用 LLM，全部是规则和统计量；P2 再叠加 LLM 编辑评分。
"""

from __future__ import annotations

import email.utils
import re
from datetime import datetime, timezone

from modules.categorizer import classify

DEFAULT_WEIGHTS = {
    "importance": 0.30,
    "info_density": 0.20,
    "source_weight": 0.20,
    "recency": 0.15,
    "category_fit": 0.10,
    "fulltext": 0.05,
}

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?%?")
_ENTITY_RE = re.compile(r"\b[A-Z][a-z]{2,}\b")


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


def _age_hours(article: dict, now: datetime) -> float | None:
    dt = _aware(_parse_datetime(article.get("pub_date", "")))
    if dt is None:
        return None
    return max(0.0, (now - dt).total_seconds() / 3600)


def _selection(config: dict) -> dict:
    return config.get("selection", {}) if config else {}


def _body(article: dict) -> str:
    return (article.get("full_text") or article.get("snippet") or "").strip()


def info_density(article: dict) -> float:
    """数字密度 + 标题专有名词 + 引述，归一到 0-1。"""
    title = article.get("title", "") or ""
    text = f"{title} {_body(article)}"
    chars = max(len(text), 1)
    numbers = len(_NUMBER_RE.findall(text))
    number_score = min(1.0, (numbers * 1000 / chars) / 20)
    entities = len(set(_ENTITY_RE.findall(title)))
    entity_score = min(1.0, entities / 6)
    quotes = text.count('"') // 2 + text.count("“")
    quote_score = min(1.0, quotes / 2)
    return round(0.5 * number_score + 0.3 * entity_score + 0.2 * quote_score, 3)


def noise_score(article: dict, patterns: list[str]) -> tuple[float, list[str]]:
    title = (article.get("title") or "").casefold()
    hits = [pattern for pattern in patterns if pattern.casefold() in title]
    return min(1.0, len(hits) * 0.5), hits


def source_weight(article: dict, config: dict) -> float:
    selection = _selection(config)
    weights = selection.get("source_weights", {})
    default = selection.get("default_source_weight", 0.75)
    value = weights.get(article.get("source", ""), default)
    return max(0.0, min(1.0, float(value)))


def category_fit(article: dict, config: dict) -> tuple[str, float]:
    category, _ = classify(article)
    preferred = config.get("prefer_categories", []) if config else []
    if category == "其他":
        return category, 0.2
    return category, 1.0 if category in preferred else 0.35


def recency_score(article: dict, config: dict, now: datetime) -> float:
    age = _age_hours(article, now)
    if age is None:
        return 0.5
    horizon = float(_selection(config).get("recency_hours", 36))
    return max(0.0, min(1.0, 1.0 - age / horizon)) if horizon > 0 else 0.5


def fulltext_score(article: dict) -> float:
    text_source = article.get("text_source")
    body_len = len(_body(article))
    if text_source == "page":
        return 1.0 if body_len >= 400 else 0.5
    if text_source == "feed":
        return 0.6 if body_len >= 800 else 0.35
    # 粗排阶段还没有 text_source，用 RSS 摘要长度做弱信号
    return min(0.5, 0.5 * body_len / 1000)


def importance_score(article: dict, event: dict | None) -> float:
    coverage = (event or article.get("_event") or {}).get("coverage", 1)
    return min(1.0, max(0, coverage) / 4)


def score_article(
    article: dict,
    event: dict | None = None,
    config: dict | None = None,
    now: datetime | None = None,
) -> dict:
    config = config or {}
    now = now or datetime.now(timezone.utc)
    selection = _selection(config)
    weights = {**DEFAULT_WEIGHTS, **selection.get("weights", {})}
    noise_penalty = float(selection.get("noise_penalty", 0.25))
    patterns = selection.get("noise_title_patterns", [])

    category, cat_fit = category_fit(article, config)
    noise, noise_hits = noise_score(article, patterns)
    signals = {
        "importance": importance_score(article, event),
        "info_density": info_density(article),
        "source_weight": source_weight(article, config),
        "recency": recency_score(article, config, now),
        "category_fit": cat_fit,
        "fulltext": fulltext_score(article),
    }
    raw = sum(weights.get(name, 0.0) * value for name, value in signals.items())
    score = max(0.0, raw - noise_penalty * noise)

    coverage = (event or article.get("_event") or {}).get("coverage", 1)
    reasons = []
    if coverage > 1:
        reasons.append(f"{coverage} 个来源覆盖")
    if article.get("text_source") == "page":
        reasons.append(f"正文 {len(_body(article))} 字")
    if category != "其他":
        reasons.append(f"{category}类")
    if noise_hits:
        reasons.append("噪音：" + "、".join(noise_hits))
    if signals["recency"] >= 0.8:
        reasons.append("最新")

    return {
        "score": round(score, 3),
        "category": category,
        "signals": signals,
        "noise": noise,
        "noise_hits": noise_hits,
        "reasons": reasons,
    }


def score_event(event: dict, config: dict, now: datetime | None = None) -> tuple[dict, dict]:
    """返回 (事件内最佳文章, 该文章的评分)。"""
    now = now or datetime.now(timezone.utc)
    scored = [
        (article, score_article(article, event, config, now))
        for article in event.get("articles", [])
    ]
    if not scored:
        raise ValueError("event has no articles")
    return max(scored, key=lambda item: item[1]["score"])
