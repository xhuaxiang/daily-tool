#!/usr/bin/env python3
"""
每日新闻早报 - Daily News Brief
入口文件，直接 python main.py 运行
"""

import logging

from modules.config import load_config
from modules.fetcher import fetch
from modules.parser import parse
from modules.summarizer import summarize_all
from modules.mailer import send_email
from modules.categorizer import sort_by_preference, count_preferred, get_category_tag

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("news")


def main():
    config = load_config()
    sources = config.get("news_sources", [])
    max_articles = config.get("max_articles", 40)
    language = config.get("summary_language", "zh")
    email_cfg = config.get("email", {})
    ai_cfg = config.get("ai", {})
    prefer_categories = config.get("prefer_categories", [])

    if not sources:
        logger.warning("No news sources configured, nothing to do")
        return

    # 多抓一些供偏好筛选
    fetch_limit = max_articles * 3 if prefer_categories else max_articles

    all_articles = []
    for src in sources:
        raw = fetch(src.get("url"), src.get("name", "unknown"), src.get("timeout", 15))
        articles = parse(src, raw, fetch_limit)
        all_articles.extend(articles)

    if not all_articles:
        logger.warning("No articles fetched")
        return

    # 去重
    seen = set()
    unique = []
    for art in all_articles:
        key = art.get("title", "")
        if key and key not in seen:
            seen.add(key)
            unique.append(art)

    # 按偏好类别排序
    if prefer_categories:
        unique = sort_by_preference(unique, prefer_categories)
        preferred_count = count_preferred(unique, prefer_categories)
        logger.info("Preferred articles: %d / %d", preferred_count, len(unique))

    all_articles = unique[:max_articles]

    logger.info("Total unique articles: %d", len(all_articles))

    # 摘要
    all_articles = summarize_all(all_articles, language, ai_cfg)

    # 控制台输出
    print()
    print("=" * 50)
    print(f"[每日新闻早报] -- {len(all_articles)} 条")
    print("=" * 50)
    for i, art in enumerate(all_articles, 1):
        tag = get_category_tag(art)
        print(f"\n#{i} {tag} [{art.get('source','')}] {art.get('title','')}")
        if art.get("summary"):
            print(f"   >> {art['summary']}")
        if art.get("link"):
            print(f"   -> {art['link']}")
    print()
    print("=" * 50)

    # 发送邮件
    send_email(email_cfg, all_articles)


if __name__ == "__main__":
    main()
