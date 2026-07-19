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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("news")


def main():
    config = load_config()
    sources = config.get("news_sources", [])
    max_articles = config.get("max_articles", 15)
    language = config.get("summary_language", "zh")
    email_cfg = config.get("email", {})

    if not sources:
        logger.warning("No news sources configured, nothing to do")
        return

    all_articles = []

    for src in sources:
        raw = fetch(src.get("url"), src.get("name", "unknown"), src.get("timeout", 15))
        articles = parse(src, raw, max_articles)
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
    all_articles = unique[:max_articles]

    logger.info("Total unique articles: %d", len(all_articles))

    # 摘要
    all_articles = summarize_all(all_articles, language)

    # 控制台输出
    print()
    print("=" * 50)
    print(f"[每日新闻早报] -- {len(all_articles)} 条")
    print("=" * 50)
    for i, art in enumerate(all_articles, 1):
        print(f"\n#{i} [{art.get('source','')}] {art.get('title','')}")
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
