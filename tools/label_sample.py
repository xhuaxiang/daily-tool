#!/usr/bin/env python3
"""P0 人工标注样本：从当前选稿逻辑里抽 N 篇，生成 CSV 供人工打分。

不调用 AI、不发邮件。生成后填写 label / reason 两列：
- label: 4=必读, 3=有用, 2=一般, 1=噪音
- reason: 重要 / 可学习 / 重复 / 标题党 / 源太弱 / 其他
"""

from __future__ import annotations

import argparse
import csv
import email.utils
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.categorizer import classify
from modules.config import load_config
from modules.dedup import dedupe
from modules.fetcher import fetch
from modules.parser import parse

logger = logging.getLogger("news")

_FIELDS = [
    "id", "source", "published", "category", "score",
    "title", "link", "summary", "label", "reason",
]
_BEIJING_TZ = timezone(timedelta(hours=8))


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


def _within_hours(pub_date: str, hours: int) -> bool:
    dt = _parse_datetime(pub_date)
    if dt is None:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - dt <= timedelta(hours=hours)


def _display_date(pub_date: str) -> str:
    dt = _parse_datetime(pub_date)
    if dt is None:
        return pub_date or ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


def select_current(
    config: dict,
    pool_size: int,
    per_source: int,
    hours: int,
) -> list[dict]:
    """复刻当前 main.py 的选稿逻辑：每源最新 N 篇，再按时间取全局前 pool_size。"""
    sources = config.get("news_sources", [])
    all_articles: list[dict] = []
    for src in sources:
        raw = fetch(src.get("url"), src.get("name", "unknown"), src.get("timeout", 15), src.get("type", "rss"))
        if not raw:
            continue
        all_articles.extend(parse(src, raw, 30))

    unique = dedupe(
        all_articles,
        threshold=config.get("dedupe_threshold", 0.9),
        source_names=[s.get("name", "") for s in sources],
        date_parser=_parse_datetime,
    )
    fresh = [art for art in unique if _within_hours(art.get("pub_date", ""), hours)]
    if not fresh:
        fresh = unique

    groups: dict[str, list[dict]] = {}
    for art in fresh:
        groups.setdefault(art.get("source", "unknown"), []).append(art)

    picked: list[dict] = []
    for arts in groups.values():
        arts.sort(
            key=lambda a: _parse_datetime(a.get("pub_date", ""))
            or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        picked.extend(arts[:per_source])

    picked.sort(
        key=lambda a: _parse_datetime(a.get("pub_date", ""))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return picked[:pool_size]


def _write_labels(sample: list[dict], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDS)
        writer.writeheader()
        for i, art in enumerate(sample, 1):
            category, score = classify(art)
            writer.writerow({
                "id": i,
                "source": art.get("source", ""),
                "published": _display_date(art.get("pub_date", "")),
                "category": category,
                "score": score,
                "title": art.get("title", ""),
                "link": art.get("link", ""),
                "summary": (art.get("snippet") or "").replace("\n", " ")[:300],
                "label": "",
                "reason": "",
            })


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="P0 生成人工标注 CSV")
    parser.add_argument("--n", type=int, default=20, help="抽取条数（默认 20）")
    parser.add_argument("--per-source", type=int, default=5, help="每源最多保留条数（默认 5）")
    parser.add_argument(
        "--hours", type=int, default=48,
        help="时间窗口小时数（默认 48，便于凑够 20 篇；日常邮件选稿是 24h）",
    )
    parser.add_argument("--output", default="data/labels.csv", help="输出 CSV（默认 data/labels.csv）")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的 CSV")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    output = Path(args.output)
    if output.exists() and not args.force:
        raise SystemExit(f"{output} 已存在；确认要覆盖请加 --force")

    config = load_config()
    pool_size = max(args.n, config.get("max_articles", 15))
    sample = select_current(config, pool_size, args.per_source, args.hours)
    if not sample:
        raise SystemExit("没有抓到可标注的文章")

    _write_labels(sample, output)
    print()
    print(f"已生成 {len(sample)} 篇待标注样本：{output.resolve()}")
    print("填写 label（4=必读 / 3=有用 / 2=一般 / 1=噪音）和 reason 两列。")
    print("提示：用 Excel 打开时选 UTF-8，或直接用编辑器编辑 CSV。")


if __name__ == "__main__":
    main()
