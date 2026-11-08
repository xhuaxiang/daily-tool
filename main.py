#!/usr/bin/env python3
"""
每日新闻早报 - Daily News Brief
入口文件，直接 python main.py 运行
"""

import argparse
import email.utils
import logging
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("news")


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

    for src in sources:
        raw = fetch(src.get("url"), src.get("name", "unknown"), src.get("timeout", 15), src.get("type", "rss"))
        if not raw:
            continue
        # 每个源多抓一些，方便按时间筛选最新的
        articles = parse(src, raw, 30)
        all_articles.extend(articles)

    if not all_articles:
        logger.warning("No articles fetched")
        return

    # 去重：同一站点重复条目 + 不同站点转载的同一篇新闻
    unique = dedupe(
        all_articles,
        threshold=config.get("dedupe_threshold", 0.9),
        source_names=[s.get("name", "") for s in sources],
        date_parser=_parse_datetime,
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

    # 按源分组，每个源只取最新的 N 篇
    source_groups = {}
    for art in today_articles:
        src = art.get("source", "unknown")
        source_groups.setdefault(src, []).append(art)

    # 每源最多保留最新文章数
    fresh_per_source = 5
    fresh_articles = []
    for src, arts in source_groups.items():
        arts_sorted = sorted(arts, key=lambda a: _parse_datetime(a.get("pub_date", "")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        fresh_articles.extend(arts_sorted[:fresh_per_source])

    logger.info("Fresh articles (latest %d per source): %d", fresh_per_source, len(fresh_articles))

    # 取最新文章，按发布时间倒序排列
    all_articles = sorted(fresh_articles, key=lambda a: _parse_datetime(a.get("pub_date", "")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)[:max_articles]

    logger.info("Final articles: %d from %d sources", len(all_articles), len(source_groups))

    if args.limit > 0:
        all_articles = all_articles[:args.limit]
        logger.info("Limited to %d articles for local test", len(all_articles))

    # 抽取正文（失败回退 RSS 摘要），再生成结构化摘要
    all_articles = enrich_articles(all_articles)
    all_articles = summarize_all(all_articles, language, ai_cfg)

    # 按用户偏好排序
    all_articles = sort_by_preference(all_articles, prefer_categories)

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
        preview_path.write_text(build_html(all_articles), encoding="utf-8")
        logger.info("Preview written to %s", preview_path.resolve())
        return

    # 发送邮件
    send_email(email_cfg, all_articles)


if __name__ == "__main__":
    main()
