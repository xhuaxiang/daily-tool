"""P1 两阶段选稿：先粗排候选，抓正文后精排，再应用配额。"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone

from modules.events import cluster_events
from modules.scoring import score_article, score_event

logger = logging.getLogger("news")


def _selection(config: dict) -> dict:
    return config.get("selection", {}) if config else {}


def _publisher(article: dict) -> str:
    return article.get("publisher") or article.get("source") or "unknown"


def _ordered_articles(event: dict, config: dict, now: datetime) -> list[tuple[dict, dict]]:
    scored = [
        (article, score_article(article, event, config, now))
        for article in event.get("articles", [])
    ]
    return sorted(scored, key=lambda item: item[1]["score"], reverse=True)


def preselect(articles: list[dict], config: dict) -> list[dict]:
    """第一轮：不抓正文，按事件和粗略信号取 candidate_pool 篇。"""
    selection = _selection(config)
    pool_size = int(selection.get("candidate_pool", 30))
    per_event_max = int(selection.get("per_event_max", 2))
    now = datetime.now(timezone.utc)

    events = cluster_events(
        articles,
        window_hours=int(selection.get("event_window_hours", 36)),
        threshold=float(selection.get("event_threshold", 0.58)),
        max_cluster=int(selection.get("max_cluster_size", 5)),
    )
    ranked = []
    for event in events:
        best_article, best_score = score_event(event, config, now)
        ranked.append((event, best_article, best_score))
    ranked.sort(key=lambda item: item[2]["score"], reverse=True)

    selected: list[dict] = []
    selected_ids: set[int] = set()
    event_counts: Counter = Counter()

    def add(article: dict, event_id: str) -> None:
        if id(article) in selected_ids or len(selected) >= pool_size:
            return
        selected.append(article)
        selected_ids.add(id(article))
        event_counts[event_id] += 1

    # 先保证事件多样性：每个事件取一篇
    for event, best_article, _ in ranked:
        if len(selected) >= pool_size:
            break
        add(best_article, event["event_id"])

    # 再补每个事件的第 2 篇
    for event, _, _ in ranked:
        if len(selected) >= pool_size:
            break
        for article, _ in _ordered_articles(event, config, now):
            if event_counts[event["event_id"]] >= per_event_max:
                break
            add(article, event["event_id"])

    logger.info(
        "Preselected %d candidates from %d events (pool=%d)",
        len(selected), len(events), pool_size,
    )
    return selected


def _synthetic_event(articles: list[dict]) -> dict:
    first = articles[0]
    if first.get("_event_id"):
        return {
            "event_id": first["_event_id"],
            "articles": articles,
            "coverage": (first.get("_event") or {}).get("coverage", 1),
            "sources": (first.get("_event") or {}).get("sources", []),
        }
    return {
        "event_id": f"single-{id(first)}",
        "articles": articles,
        "coverage": 1,
        "sources": [_publisher(first)],
    }


def final_select(articles: list[dict], config: dict, total: int) -> list[dict]:
    """第二轮：按正文/信息量/来源/类别重新评分，并应用配额。"""
    selection = _selection(config)
    per_source_max = int(selection.get("per_source_max", 4))
    per_publisher_max = int(selection.get("per_publisher_max", 99))
    per_event_max = int(selection.get("per_event_max", 2))
    category_min = selection.get("category_min", {})
    now = datetime.now(timezone.utc)

    groups: dict[str, list[dict]] = {}
    for article in articles:
        event_id = article.get("_event_id") or f"single-{id(article)}"
        groups.setdefault(event_id, []).append(article)

    events = [_synthetic_event(group) for group in groups.values()]
    ranked = []
    for event in events:
        ordered = _ordered_articles(event, config, now)
        if not ordered:
            continue
        best_article, best_score = ordered[0]
        ranked.append((event, best_article, best_score, ordered))
    ranked.sort(key=lambda item: item[2]["score"], reverse=True)

    selected: list[dict] = []
    selected_ids: set[int] = set()
    source_counts: Counter = Counter()
    publisher_counts: Counter = Counter()
    event_counts: Counter = Counter()
    category_counts: Counter = Counter()

    def can_add(
        article: dict,
        event_id: str,
        enforce_source: bool = True,
        enforce_publisher: bool = True,
        enforce_event: bool = True,
    ) -> bool:
        if id(article) in selected_ids or len(selected) >= total:
            return False
        if enforce_event and event_counts[event_id] >= per_event_max:
            return False
        if enforce_source and source_counts[article.get("source", "")] >= per_source_max:
            return False
        if enforce_publisher and publisher_counts[_publisher(article)] >= per_publisher_max:
            return False
        return True

    def add(article: dict, event_id: str, info: dict) -> None:
        selected.append(article)
        selected_ids.add(id(article))
        source_counts[article.get("source", "")] += 1
        publisher_counts[_publisher(article)] += 1
        event_counts[event_id] += 1
        category_counts[info["category"]] += 1
        article["_selection"] = {
            "event_id": event_id,
            "score": info["score"],
            "coverage": (info.get("signals") or {}).get("importance", 0) * 4,
            "category": info["category"],
            "reasons": info["reasons"],
        }

    # 1. 类别保底：尽量让经济/时政/国际各有最低条数
    for category, target in category_min.items():
        while category_counts[category] < int(target):
            added = False
            for event, _, _, ordered in ranked:
                event_id = event["event_id"]
                for article, info in ordered:
                    if info["category"] != category:
                        continue
                    if can_add(article, event_id):
                        add(article, event_id, info)
                        added = True
                        break
                if added or len(selected) >= total:
                    break
            if not added:
                logger.info("Category minimum not met: %s < %s", category, target)
                break

    # 2. 按事件分数填充
    for event, _, _, ordered in ranked:
        if len(selected) >= total:
            break
        event_id = event["event_id"]
        for article, info in ordered:
            if can_add(article, event_id):
                add(article, event_id, info)
            if len(selected) >= total or event_counts[event_id] >= per_event_max:
                break

    # 3. 不够先放宽单栏目配额，但仍限制同一媒体和同一事件
    remaining = sorted(
        (
            (article, info, event["event_id"])
            for event, _, _, ordered in ranked
            for article, info in ordered
        ),
        key=lambda item: item[1]["score"],
        reverse=True,
    )
    if len(selected) < total:
        for article, info, event_id in remaining:
            if can_add(article, event_id, enforce_source=False):
                add(article, event_id, info)
            if len(selected) >= total:
                break

    # 4. 再放宽媒体上限，但仍保留事件上限
    if len(selected) < total:
        for article, info, event_id in remaining:
            if can_add(article, event_id, enforce_source=False, enforce_publisher=False):
                add(article, event_id, info)
            if len(selected) >= total:
                break

    # 5. 最后才放宽事件上限，避免空邮件
    if len(selected) < total:
        for article, info, event_id in remaining:
            if can_add(
                article, event_id,
                enforce_source=False, enforce_publisher=False, enforce_event=False,
            ):
                add(article, event_id, info)
            if len(selected) >= total:
                break

    if len(selected) < total:
        logger.warning("Selected only %d/%d articles", len(selected), total)

    selected.sort(key=lambda art: art.get("_selection", {}).get("score", 0), reverse=True)
    logger.info(
        "Final selection: %d articles from %d events / %d sources / %d publishers",
        len(selected), len(event_counts), len(source_counts), len(publisher_counts),
    )
    return selected
