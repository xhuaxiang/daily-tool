#!/usr/bin/env python3
"""
每日新闻早报 - Daily News Brief
入口文件，直接 python main.py 运行
"""

import argparse
import email.utils
import logging
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from modules.config import load_config
from modules.fetcher import fetch
from modules.parser import parse
from modules.fulltext import enrich_articles
from modules.summarizer import summarize_all
from modules.mailer import build_html, send_email
from modules.categorizer import classify, sort_by_preference
from modules.dedup import dedupe
from modules.snapshot import (
    RUN_DIR,
    build_archive,
    build_snapshot,
    write_json,
    write_labels_csv,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("news")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass


def _parse_datetime(pub_date: str) -> datetime | None:
    """将 pubDate 字符串解析为 UTC datetime，解析失败返回 None"""
    if not pub_date:
        return None
    # RFC 2822 (RSS 标准)
    try:
        return email.utils.parsedate_to_datetime(pub_date)
    except (ValueError, TypeError):
        pass
    # ISO 8601 / Atom
    try:
        s = pub_date.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        pass
    return None


# 东八区
_BEIJING_TZ = timezone(timedelta(hours=8))


def _to_beijing_time(pub_date: str) -> str:
    """将 pubDate 转为东八区 YYYY-MM-DD hh:mm:ss，解析失败返回原字符串"""
    dt = _parse_datetime(pub_date)
    if dt is None:
        return pub_date or ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(_BEIJING_TZ)
    return local.strftime("%Y-%m-%d %H:%M:%S")


def _is_today(pub_date: str, max_age_hours: int = 24) -> bool:
    """判断 pub_date 是否在最近 max_age_hours 小时内"""
    dt = _parse_datetime(pub_date)
    if dt is None:
        return True  # 无日期的文章保留，避免误杀
    # 统一转为 UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    age = now - dt
    return age <= timedelta(hours=max_age_hours)


def main():
    parser = argparse.ArgumentParser(description="每日新闻早报")
    parser.add_argument(
        "--preview", nargs="?", const="preview.html", metavar="FILE",
        help="只生成 HTML 预览，不发邮件（默认 preview.html）",
    )
    parser.add_argument("--no-ai", action="store_true", help="跳过 AI，使用本地摘要")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 篇，便于本地测试")
    parser.add_argument("--no-selection", action="store_true", help="关闭 P1 规则选稿，回到按时间选取")
    parser.add_argument("--explain-selection", action="store_true", help="输出每篇文章的选稿评分和原因")
    args = parser.parse_args()

    config = load_config()
    sources = config.get("news_sources", [])
    max_articles = config.get("max_articles", 15)
    language = config.get("summary_language", "zh")
    email_cfg = config.get("email", {})
    ai_cfg = [] if args.no_ai else config.get("ai", {})
    prefer_categories = config.get("prefer_categories", [])

    if not sources:
        logger.warning("No news sources configured, nothing to do")
        return

    all_articles = []
    source_stats = []

    for src in sources:
        raw = fetch(src.get("url"), src.get("name", "unknown"), src.get("timeout", 15), src.get("type", "rss"))
        # 每个源多抓一些，方便按时间筛选最新的
        articles = parse(src, raw, 30) if raw else []
        publisher = src.get("publisher") or src.get("name", "unknown")
        for article in articles:
            article["publisher"] = publisher
        all_articles.extend(articles)
        source_stats.append({
            "name": src.get("name", "unknown"),
            "publisher": publisher,
            "fetch_ok": bool(raw),
            "parsed": len(articles),
        })

    if not all_articles:
        # 退出码非 0，让 Actions 变红；否则"没抓到文章"会显示成绿色成功
        logger.error("No articles fetched")
        raise SystemExit(1)

    # 去重：同一站点重复条目 + 不同站点转载的同一篇新闻
    dedupe_stats: dict = {}
    unique = dedupe(
        all_articles,
        threshold=config.get("dedupe_threshold", 0.9),
        source_names=[s.get("name", "") for s in sources],
        date_parser=_parse_datetime,
        stats=dedupe_stats,
    )

    logger.info("Total unique articles: %d", len(unique))

    # 只保留今天（24h内）的文章
    today_articles = [a for a in unique if _is_today(a.get("pub_date", ""))]
    dropped = len(unique) - len(today_articles)
    if dropped:
        logger.info("Dropped %d old articles (older than 24h), kept %d", dropped, len(today_articles))

    if not today_articles:
        logger.warning("No articles from today, falling back to all unique articles")
        today_articles = unique

    fresh_by_source = Counter(art.get("source", "") for art in today_articles)

    # 按源分组，每个源只取最新的 N 篇
    source_groups = {}
    for art in today_articles:
        src = art.get("source", "unknown")
        source_groups.setdefault(src, []).append(art)

    selection_cfg = config.get("selection", {})
    selection_enabled = selection_cfg.get("enabled", True) and not args.no_selection

    # 每源最多保留最新文章数：选稿模式多留一些候选，交给 P1 排序
    fresh_per_source = 8 if selection_enabled else 5
    fresh_articles = []
    for src, arts in source_groups.items():
        arts_sorted = sorted(arts, key=lambda a: _parse_datetime(a.get("pub_date", "")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        fresh_articles.extend(arts_sorted[:fresh_per_source])

    logger.info("Fresh articles (latest %d per source): %d", fresh_per_source, len(fresh_articles))

    if selection_enabled:
        # P1：先粗排 30 篇候选，只抓这些文章的正文，再精排到 max_articles
        from modules.selection import final_select, preselect

        candidates = preselect(fresh_articles, config)
        candidates = enrich_articles(candidates)
        selection_total = args.limit if args.limit > 0 else max_articles
        all_articles = final_select(candidates, config, selection_total)
    else:
        # 旧逻辑：按发布时间取最新 N 篇
        all_articles = sorted(fresh_articles, key=lambda a: _parse_datetime(a.get("pub_date", "")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)[:max_articles]

        if args.limit > 0:
            all_articles = all_articles[:args.limit]
            logger.info("Limited to %d articles for local test", len(all_articles))

        # 抽取正文（失败回退 RSS 摘要），再生成结构化摘要
        all_articles = enrich_articles(all_articles)
        for article in all_articles:
            article["_selection"] = {
                "category": classify(article)[0],
                "selected": True,
                "reject_reason": "",
                "reasons": [],
                "score": None,
            }
        candidates = all_articles
        selection_total = len(all_articles)

    logger.info("Final articles: %d from %d sources", len(all_articles), len(source_groups))

    all_articles = summarize_all(all_articles, language, ai_cfg)

    # 规则选稿已经按综合分排序；旧逻辑保留偏好排序
    if not selection_enabled:
        all_articles = sort_by_preference(all_articles, prefer_categories)

    # P0：快照覆盖 24h 内全部去重文章；未进入候选池的也记录，便于评估漏选
    snapshot_candidates = list(today_articles)
    for article in snapshot_candidates:
        if article.get("_selection"):
            continue
        article["_selection"] = {
            "event_id": article.get("_event_id", ""),
            "score": None,
            "signals": {},
            "category": classify(article)[0],
            "reasons": [],
            "selected": False,
            "reject_reason": "未进入候选池",
        }

    run_date = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")
    run_dir = RUN_DIR / run_date
    snapshot_payload = build_snapshot(
        snapshot_candidates,
        run_date=run_date,
        source_stats=source_stats,
        dedupe_stats=dedupe_stats,
        fresh_by_source=fresh_by_source,
        parsed_total=dedupe_stats.get("input", 0),
        unique_total=dedupe_stats.get("kept", len(unique)),
        fresh_total=len(today_articles),
        selection_total=selection_total,
    )
    snapshot_path = write_json(run_dir / f"run-{run_date}.json", snapshot_payload)
    archive_path = write_json(
        run_dir / f"articles-{run_date}.json",
        build_archive(today_articles, run_date=run_date),
    )
    labels_path = write_labels_csv(
        snapshot_payload["candidates"],
        run_dir / f"labels-{run_date}.csv",
    )
    totals = snapshot_payload["totals"]
    run_summary = {
        "candidates": totals["candidates"],
        "selected": totals["selected"],
        "fulltext_coverage": totals["fulltext_coverage"],
        "sources": totals["sources"],
        "duplicates_removed": totals["duplicates_removed"],
    }
    logger.info(
        "Run snapshot: %s (candidates=%d, selected=%d, fulltext=%d%%)",
        snapshot_path, totals["candidates"], totals["selected"],
        round(totals["fulltext_coverage"] * 100),
    )

    if args.explain_selection:
        print()
        print("=" * 50)
        print("[选稿明细]")
        for i, art in enumerate(all_articles, 1):
            sel = art.get("_selection") or {}
            print(
                f"#{i} score={sel.get('score', '-')} "
                f"[{sel.get('category', '?')}] [{art.get('source', '')}] "
                f"event={sel.get('event_id', '-')} coverage={sel.get('coverage', '-')}"
            )
            print(f"   {art.get('title', '')}")
            if sel.get("reasons"):
                print(f"   理由: {'; '.join(sel['reasons'])}")
        print("=" * 50)

    # 统一 pub_date 为东八区 YYYY-MM-DD hh:mm:ss
    for art in all_articles:
        art["pub_date"] = _to_beijing_time(art.get("pub_date", ""))

    # 控制台输出
    print()
    print("=" * 50)
    print(f"[每日新闻早报] -- {len(all_articles)} 条")
    print("=" * 50)
    for i, art in enumerate(all_articles, 1):
        cat, _ = classify(art)
        tag = f"[{cat}]" if cat != "其他" else ""
        title = art.get('title', '').replace('\xa0', ' ').strip()
        title_zh = (art.get('title_zh') or '').replace('\xa0', ' ').strip()
        date_str = art.get('pub_date', '')
        print(f"\n#{i} {tag} [{art.get('source','')}] {date_str} {title_zh or title}")
        if title_zh and title_zh != title:
            print(f"   原文: {title}")
        for point in art.get("summary_points") or []:
            print(f"   - {point}")
        if not art.get("summary_points") and art.get("summary"):
            print(f"   >> {art['summary'].replace(chr(10), ' ')}")
        if art.get("link"):
            print(f"   -> {art['link']}")
    print()
    print("=" * 50)

    if args.preview:
        preview_path = Path(args.preview).expanduser()
        preview_path.write_text(
            build_html(all_articles, run_summary), encoding="utf-8"
        )
        logger.info("Preview written to %s", preview_path.resolve())
        return

    # 发送邮件：正文 + 运行快照 + 全文归档 + 空标注表
    sent = send_email(
        email_cfg,
        all_articles,
        attachments=[snapshot_path, archive_path, labels_path],
        run_summary=run_summary,
    )
    if not sent:
        # 发信失败必须让任务失败；否则 Actions 显示成功但你没收到邮件
        logger.error("Email was not sent")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
