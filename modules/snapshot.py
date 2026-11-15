"""运行快照与归档：把每日选稿的观测数据落盘，供邮件附件和离线评估使用。

不引入数据库：快照和归档都是 JSON，标注表是 CSV。
"""

from __future__ import annotations

import csv
import email.utils
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from modules.categorizer import classify
from modules.dedup import normalize_title, normalize_url

ROOT = Path(__file__).resolve().parent.parent
RUN_DIR = ROOT / "reports" / "runs"
_BEIJING_TZ = timezone(timedelta(hours=8))

LABEL_FIELDS = [
    "id", "source", "publisher", "published", "category", "score",
    "selected", "event_id", "text_source", "title", "link", "summary",
    "label", "reason",
]


def article_id(article: dict) -> str:
    """稳定 id：规范化 URL 优先，其次规范化标题。"""
    key = normalize_url(article.get("link", ""))
    if not key:
        key = normalize_title(article.get("title", ""))
    if not key:
        key = "|".join(
            str(article.get(field, ""))
            for field in ("source", "title", "pub_date")
        )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _display_date(pub_date: str) -> str:
    if not pub_date:
        return ""
    dt = None
    try:
        dt = email.utils.parsedate_to_datetime(pub_date)
    except (ValueError, TypeError):
        try:
            dt = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return pub_date
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _text_source(article: dict) -> str:
    source = article.get("text_source")
    if source:
        return source
    return "feed" if (article.get("snippet") or "").strip() else "none"


def candidate_record(article: dict) -> dict:
    selection = article.get("_selection") or {}
    event = article.get("_event") or {}
    category = selection.get("category") or classify(article)[0]
    body = (article.get("full_text") or article.get("snippet") or "").strip()
    coverage = selection.get("coverage")
    if coverage is None:
        coverage = event.get("coverage", 0)
    return {
        "id": article_id(article),
        "title": article.get("title", ""),
        "title_zh": article.get("title_zh", ""),
        "link": article.get("link", ""),
        "source": article.get("source", ""),
        "publisher": article.get("publisher") or article.get("source", ""),
        "pub_date": article.get("pub_date", ""),
        "published": _display_date(article.get("pub_date", "")),
        "category": category,
        "score": selection.get("score"),
        "signals": selection.get("signals", {}),
        "event_id": selection.get("event_id") or article.get("_event_id", ""),
        "coverage": coverage,
        "reasons": list(selection.get("reasons") or []),
        "text_source": _text_source(article),
        "body_len": len(body),
        "snippet": (article.get("snippet") or "").strip()[:300],
        "selected": bool(selection.get("selected", False)),
        "reject_reason": selection.get("reject_reason", ""),
    }


def _share_max(counts: Counter, total: int) -> float:
    if not total:
        return 0.0
    return round(max(counts.values(), default=0) / total, 3)


def build_snapshot(
    candidates: list[dict],
    *,
    run_date: str,
    source_stats: list[dict],
    dedupe_stats: dict,
    fresh_by_source: dict,
    parsed_total: int,
    unique_total: int,
    fresh_total: int,
    selection_total: int,
    window_hours: int = 24,
) -> dict:
    records = [candidate_record(article) for article in candidates]
    records.sort(
        key=lambda row: (
            1 if row["selected"] else 0,
            row["score"] if isinstance(row["score"], (int, float)) else -1,
        ),
        reverse=True,
    )

    selected = [row for row in records if row["selected"]]
    total_selected = len(selected)
    source_counts = Counter(row["source"] for row in selected)
    publisher_counts = Counter(row["publisher"] for row in selected)
    category_counts = Counter(row["category"] for row in selected)
    text_counts = Counter(row["text_source"] or "none" for row in selected)
    event_counts = Counter(row["event_id"] for row in selected if row["event_id"])
    duplicated_events = sum(count for count in event_counts.values() if count > 1)

    candidate_counts = Counter(article.get("source", "") for article in candidates)
    selected_by_source = Counter(
        article.get("source", "")
        for article in candidates
        if (article.get("_selection") or {}).get("selected")
    )
    dup_by_source = dedupe_stats.get("by_source", {})
    sources = []
    for stat in source_stats:
        name = stat.get("name", "")
        sources.append({
            **stat,
            "fresh": fresh_by_source.get(name, 0),
            "duplicates_removed": dup_by_source.get(name, 0),
            "candidates": candidate_counts.get(name, 0),
            "selected": selected_by_source.get(name, 0),
        })

    return {
        "schema_version": 1,
        "run_date": run_date,
        "generated_at": datetime.now(_BEIJING_TZ).isoformat(timespec="seconds"),
        "window_hours": window_hours,
        "selection_total": selection_total,
        "sources": sources,
        "totals": {
            "parsed": parsed_total,
            "unique": unique_total,
            "duplicates_removed": dedupe_stats.get("duplicates_removed", 0),
            "fresh": fresh_total,
            "candidates": len(records),
            "selected": total_selected,
            "sources": len(source_counts),
            "publishers": len(publisher_counts),
            "category": dict(category_counts.most_common()),
            "text_source": dict(text_counts),
            "fulltext_coverage": round(text_counts.get("page", 0) / total_selected, 3)
            if total_selected else 0.0,
            "source_share_max": _share_max(source_counts, total_selected),
            "publisher_share_max": _share_max(publisher_counts, total_selected),
            "event_duplicate_rate": round(duplicated_events / total_selected, 3)
            if total_selected else 0.0,
            "body_avg_chars": int(
                sum(row["body_len"] for row in selected) / total_selected
            ) if total_selected else 0,
        },
        "candidates": records,
    }


def build_archive(articles: list[dict], *, run_date: str) -> dict:
    records = []
    for article in articles:
        text = (article.get("full_text") or article.get("snippet") or "").strip()
        records.append({
            "id": article_id(article),
            "title": article.get("title", ""),
            "title_zh": article.get("title_zh", ""),
            "link": article.get("link", ""),
            "source": article.get("source", ""),
            "publisher": article.get("publisher") or article.get("source", ""),
            "pub_date": article.get("pub_date", ""),
            "published": _display_date(article.get("pub_date", "")),
            "category": classify(article)[0],
            "event_id": article.get("_event_id", ""),
            "text": text,
            "text_source": _text_source(article),
            "body_len": len(text),
            "selected": bool((article.get("_selection") or {}).get("selected")),
        })
    return {
        "schema_version": 1,
        "run_date": run_date,
        "generated_at": datetime.now(_BEIJING_TZ).isoformat(timespec="seconds"),
        "count": len(records),
        "articles": records,
    }


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _label_row(item: dict, index: int) -> dict:
    if "selected" in item and "id" in item:
        return {
            "id": item.get("id") or str(index),
            "source": item.get("source", ""),
            "publisher": item.get("publisher", ""),
            "published": item.get("published") or _display_date(item.get("pub_date", "")),
            "category": item.get("category", "其他"),
            "score": item.get("score", ""),
            "selected": "1" if item.get("selected") else "0",
            "event_id": item.get("event_id", ""),
            "text_source": item.get("text_source", ""),
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "summary": (item.get("snippet") or "").strip()[:300],
            "label": "",
            "reason": "",
        }

    category, category_score = classify(item)
    selection = item.get("_selection") or {}
    return {
        "id": item.get("id") or article_id(item) or str(index),
        "source": item.get("source", ""),
        "publisher": item.get("publisher") or item.get("source", ""),
        "published": _display_date(item.get("pub_date", "")),
        "category": selection.get("category") or category,
        "score": selection.get("score", category_score),
        "selected": "1" if selection.get("selected") else "",
        "event_id": selection.get("event_id") or item.get("_event_id", ""),
        "text_source": _text_source(item),
        "title": item.get("title", ""),
        "link": item.get("link", ""),
        "summary": (item.get("snippet") or "").strip()[:300],
        "label": "",
        "reason": "",
    }


def write_labels_csv(candidates: list[dict], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_FIELDS)
        writer.writeheader()
        for index, item in enumerate(candidates, 1):
            writer.writerow(_label_row(item, index))
    return output


def find_latest_snapshot() -> Path | None:
    paths = list(RUN_DIR.glob("*/run-*.json"))
    if not paths:
        return None
    return max(paths, key=lambda path: path.stat().st_mtime)
