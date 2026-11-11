#!/usr/bin/env python3
"""P0 新闻源体检：抓取、解析、正文、重复、分类分布。

只读诊断，不调用 AI、不发邮件。输出 Markdown + JSON 到 reports/。
"""

from __future__ import annotations

import argparse
import email.utils
import json
import logging
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.categorizer import classify
from modules.config import load_config
from modules.dedup import dedupe
from modules.fetcher import fetch
from modules.fulltext import fetch_full_text
from modules.parser import parse

logger = logging.getLogger("news")

PAGE_MIN_CHARS = 400
_BEIJING_TZ = timezone(timedelta(hours=8))


def _parse_datetime(pub_date: str) -> datetime | None:
    """将 pubDate 字符串解析为 UTC datetime，解析失败返回 None。"""
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


def _within_days(pub_date: str, days: int) -> bool:
    dt = _parse_datetime(pub_date)
    if dt is None:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - dt <= timedelta(days=days)


def _latest_datetime(articles: list[dict]) -> datetime | None:
    dates = []
    for art in articles:
        dt = _parse_datetime(art.get("pub_date", ""))
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dates.append(dt)
    return max(dates) if dates else None


def _format_latest(dt: datetime | None) -> str:
    if dt is None:
        return "-"
    return dt.astimezone(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M")


def _age_hours(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    return round((datetime.now(timezone.utc) - dt).total_seconds() / 3600, 1)


def _probe_fulltext(
    articles: list[dict],
    timeout: int,
    max_workers: int = 4,
) -> dict:
    """抽样抓正文，返回成功数、正文均长、RSS 均长。"""
    if not articles:
        return {"sample": 0, "page_ok": 0, "avg_page_chars": 0, "avg_feed_chars": 0}

    results: list[tuple[dict, str]] = []

    def _work(art: dict) -> tuple[dict, str]:
        return art, fetch_full_text(art.get("link", ""), timeout)

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        futures = [pool.submit(_work, art) for art in articles]
        for future in as_completed(futures):
            results.append(future.result())

    page_chars = [len(text) for _, text in results if len(text) >= PAGE_MIN_CHARS]
    feed_chars = [len(art.get("snippet", "")) for art, _ in results]
    return {
        "sample": len(articles),
        "page_ok": len(page_chars),
        "avg_page_chars": int(statistics.mean(page_chars)) if page_chars else 0,
        "avg_feed_chars": int(statistics.mean(feed_chars)) if feed_chars else 0,
    }


def _category_mix(articles: list[dict]) -> dict[str, int]:
    return dict(Counter(classify(art)[0] for art in articles).most_common())


def _fmt_category_mix(mix: dict[str, int]) -> str:
    if not mix:
        return "-"
    return ", ".join(f"{name} {count}" for name, count in mix.items())


def _esc_cell(value: object) -> str:
    return str(value).replace("|", "\\|")


def _build_source_report(run: dict, dup_removed: int) -> dict:
    source = run["source"]
    fresh = run["fresh"]
    probe = run["probe"]
    sample = probe["sample"]
    page_rate = (probe["page_ok"] / sample) if sample else 0.0
    latest = _latest_datetime(run["articles"])
    return {
        "name": source.get("name", "unknown"),
        "url": source.get("url", ""),
        "fetch_ok": run["fetch_ok"],
        "parsed": len(run["articles"]),
        "fresh": len(fresh),
        "latest_pub": _format_latest(latest),
        "latest_age_hours": _age_hours(latest),
        "sample": sample,
        "page_ok": probe["page_ok"],
        "page_rate": round(page_rate, 3),
        "avg_page_chars": probe["avg_page_chars"],
        "avg_feed_chars": probe["avg_feed_chars"],
        "duplicates_removed": dup_removed,
        "categories": _category_mix(fresh),
        "elapsed_seconds": round(run["elapsed"], 2),
    }


def _render_markdown(
    reports: list[dict],
    dedupe_stats: dict,
    totals: dict,
    days: int,
    max_articles: int,
    sample_per_source: int,
    fulltext: bool,
) -> str:
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = [
        "# 新闻源体检报告",
        "",
        f"- 生成时间：{now}",
        f"- 时间窗口：最近 {days} 天",
        f"- 每源解析上限：{max_articles} 条",
        f"- 正文抽样：每源 {sample_per_source} 篇" + ("" if fulltext else "（已关闭正文探测）"),
        f"- 正文判定：抓取文本 >= {PAGE_MIN_CHARS} 字符",
        "",
        "| 来源 | 抓取 | 解析 | 窗口内 | 最新文章 | 滞后 | 正文成功 | 正文均长 | RSS 均长 | 重复移除 | 类别分布 | 耗时 |",
        "|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---|---:|",
    ]

    for row in reports:
        if not fulltext:
            page_cell = "n/a"
        elif row["sample"]:
            page_cell = f'{row["page_ok"]}/{row["sample"]} ({row["page_rate"]:.0%})'
        else:
            page_cell = "-"
        age = row["latest_age_hours"]
        age_cell = f"{age:.0f}h" if age is not None else "-"
        lines.append(
            "| {name} | {fetch} | {parsed} | {fresh} | {latest} | {age} | {page} | "
            "{page_chars} | {feed_chars} | {dup} | {cats} | {elapsed}s |".format(
                name=_esc_cell(row["name"]),
                fetch="OK" if row["fetch_ok"] else "FAIL",
                parsed=row["parsed"],
                fresh=row["fresh"],
                latest=_esc_cell(row["latest_pub"]),
                age=age_cell,
                page=page_cell,
                page_chars=row["avg_page_chars"] if fulltext else "-",
                feed_chars=row["avg_feed_chars"],
                dup=row["duplicates_removed"],
                cats=_esc_cell(_fmt_category_mix(row["categories"])),
                elapsed=row["elapsed_seconds"],
            )
        )

    dup_by_source = dedupe_stats.get("by_source", {})
    dup_text = ", ".join(f"{k} {v}" for k, v in sorted(dup_by_source.items())) or "-"
    lines += [
        "",
        "## 汇总",
        "",
        f"- 解析总数：{totals['parsed']}",
        f"- 去重后：{dedupe_stats.get('kept', 0)}",
        f"- 重复移除：{dedupe_stats.get('duplicates_removed', 0)}（{dup_text}）",
        f"- 窗口内：{totals['fresh']}",
        f"- 类别分布：{_fmt_category_mix(totals['categories'])}",
        f"- 正文抽样：{totals['page_ok']}/{totals['sample']}"
        + (
            f"（{totals['page_rate']:.0%}）"
            if totals.get("page_rate") is not None
            else "（未探测）"
        ),
        "",
        "## 怎么读",
        "",
        "- `正文成功` 低：这个源可能反爬、付费墙，或抽取器不适配，优先考虑换源。",
        "- `RSS 均长` 很短：即使正文抓不到，邮件里也不会有多少内容。",
        "- `重复移除` 高：同源重复或跨源转载多，选稿层需要事件合并。",
        "- `类别分布` 过窄：邮件覆盖面会偏科，P1 需要类别配额。",
    ]
    return "\n".join(lines) + "\n"


def run(
    days: int,
    max_articles: int,
    sample_per_source: int,
    timeout: int,
    fulltext: bool,
    output_dir: Path,
) -> tuple[list[dict], dict, dict]:
    config = load_config()
    sources = config.get("news_sources", [])
    if not sources:
        raise SystemExit("config.json 里没有 news_sources")

    runs: list[dict] = []
    all_articles: list[dict] = []

    for src in sources:
        name = src.get("name", "unknown")
        started = time.perf_counter()
        raw = fetch(src.get("url"), name, src.get("timeout", 15), src.get("type", "rss"))
        articles = parse(src, raw, max_articles) if raw else []
        fresh = [art for art in articles if _within_days(art.get("pub_date", ""), days)]
        sample_pool = fresh if fresh else articles
        sample = sample_pool[:max(0, sample_per_source)]
        probe = (
            _probe_fulltext(sample, timeout)
            if fulltext
            else {"sample": len(sample), "page_ok": 0, "avg_page_chars": 0, "avg_feed_chars": 0}
        )
        elapsed = time.perf_counter() - started
        runs.append({
            "source": src,
            "fetch_ok": bool(raw),
            "articles": articles,
            "fresh": fresh,
            "probe": probe,
            "elapsed": elapsed,
        })
        all_articles.extend(articles)

    dedupe_stats: dict = {}
    unique = dedupe(
        all_articles,
        threshold=config.get("dedupe_threshold", 0.9),
        source_names=[s.get("name", "") for s in sources],
        date_parser=_parse_datetime,
        stats=dedupe_stats,
    )

    dup_by_source = dedupe_stats.get("by_source", {})
    reports = [
        _build_source_report(run, dup_by_source.get(run["source"].get("name", "unknown"), 0))
        for run in runs
    ]

    fresh_unique = [art for art in unique if _within_days(art.get("pub_date", ""), days)]
    total_sample = sum(row["sample"] for row in reports)
    total_page_ok = sum(row["page_ok"] for row in reports)
    totals = {
        "parsed": len(all_articles),
        "unique": len(unique),
        "fresh": len(fresh_unique),
        "categories": _category_mix(fresh_unique),
        "sample": total_sample,
        "page_ok": total_page_ok,
        "page_rate": round(total_page_ok / total_sample, 3) if fulltext and total_sample else None,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    markdown = _render_markdown(
        reports, dedupe_stats, totals, days, max_articles, sample_per_source, fulltext
    )
    (output_dir / "source_scorecard.md").write_text(markdown, encoding="utf-8")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "max_articles_per_source": max_articles,
        "sample_per_source": sample_per_source,
        "fulltext_probe": fulltext,
        "reports": reports,
        "dedupe": dedupe_stats,
        "totals": totals,
    }
    (output_dir / "source_scorecard.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return reports, dedupe_stats, totals


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="P0 新闻源体检（只读，不发邮件）")
    parser.add_argument("--days", type=int, default=2, help="时间窗口天数（默认 2）")
    parser.add_argument("--max-articles", type=int, default=30, help="每源最多解析条数（默认 30）")
    parser.add_argument("--sample-per-source", type=int, default=5, help="每源正文抽样条数（默认 5）")
    parser.add_argument("--timeout", type=int, default=10, help="正文请求超时秒数（默认 10）")
    parser.add_argument("--no-fulltext", action="store_true", help="跳过正文探测，只统计抓取/解析/重复")
    parser.add_argument("--output-dir", default="reports", help="报告输出目录（默认 reports）")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    reports, dedupe_stats, totals = run(
        days=args.days,
        max_articles=args.max_articles,
        sample_per_source=args.sample_per_source,
        timeout=args.timeout,
        fulltext=not args.no_fulltext,
        output_dir=Path(args.output_dir),
    )

    print()
    print("=" * 72)
    print(f"[P0 新闻源体检] 解析 {totals['parsed']} 条，去重后 {totals['unique']} 条，"
          f"窗口内 {totals['fresh']} 条")
    print("=" * 72)
    for row in reports:
        if args.no_fulltext:
            page = "n/a"
        elif row["sample"]:
            page = f'{row["page_ok"]}/{row["sample"]}'
        else:
            page = "-"
        age = row["latest_age_hours"]
        age_text = f"{age:.0f}h" if age is not None else "-"
        print(
            f"{row['name']:<24} 抓取={'OK' if row['fetch_ok'] else 'FAIL':<4} "
            f"解析={row['parsed']:<3} 窗口={row['fresh']:<3} 最新={row['latest_pub']} "
            f"({age_text:>6}) 正文={page:<5} 重复移除={row['duplicates_removed']:<3} "
            f"耗时={row['elapsed_seconds']}s"
        )
    print()
    print(f"报告：{Path(args.output_dir).resolve() / 'source_scorecard.md'}")
    print(f"JSON：{Path(args.output_dir).resolve() / 'source_scorecard.json'}")


if __name__ == "__main__":
    main()
