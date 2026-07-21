#!/usr/bin/env python3
"""
每日新闻早报 - Daily News Brief
入口文件，直接 python main.py 运行
"""

import logging
import random

from modules.config import load_config
from modules.fetcher import fetch
from modules.parser import parse
from modules.summarizer import summarize_all
from modules.mailer import send_email
from modules.categorizer import classify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("news")


def _parse_date(pub_date: str) -> str:
    """提取日期用于排序，无日期则返空"""
    if not pub_date:
        return ""
    # 取前10~25字符作为粗略时间
    return pub_date[:25]


def main():
    config = load_config()
    sources = config.get("news_sources", [])
    max_articles = config.get("max_articles", 30)
    language = config.get("summary_language", "zh")
    email_cfg = config.get("email", {})
    ai_cfg = config.get("ai", {})
    prefer_categories = config.get("prefer_categories", [])

    if not sources:
        logger.warning("No news sources configured, nothing to do")
        return

    all_articles = []

    for src in sources:
        raw = fetch(src.get("url"), src.get("name", "unknown"), src.get("timeout", 15))
        if not raw:
            continue
        # 每个源抓取稍多一些，供随机挑选
        articles = parse(src, raw, 10)
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

    logger.info("Total unique articles: %d", len(unique))

    # 按源分组，每个源随机挑几篇，保证覆盖面
    random.seed()
    source_groups = {}
    for art in unique:
        src = art.get("source", "unknown")
        source_groups.setdefault(src, []).append(art)

    selected = []
    # 每源至少贡献的文章数
    base_per_source = max(1, max_articles // len(source_groups))
    remaining = max_articles

    # 先每个源按时间取最新的 base_per_source 篇
    for src, arts in source_groups.items():
        # 有日期的按日期降序排，没日期的放后面
        arts_sorted = sorted(arts, key=lambda a: _parse_date(a.get("pub_date", "")), reverse=True)
        take = min(base_per_source, len(arts_sorted))
        selected.extend(arts_sorted[:take])
        remaining -= take

    # 还有剩余名额，从所有剩余文章中随机挑选
    if remaining > 0:
        pool = [a for a in unique if a not in selected]
        random.shuffle(pool)
        selected.extend(pool[:remaining])

    # 打乱最终顺序，混合各源内容
    random.shuffle(selected)

    all_articles = selected[:max_articles]
    logger.info("Final articles: %d from %d sources", len(all_articles), len(source_groups))

    # 摘要
    all_articles = summarize_all(all_articles, language, ai_cfg)

    # 控制台输出
    print()
    print("=" * 50)
    print(f"[每日新闻早报] -- {len(all_articles)} 条")
    print("=" * 50)
    for i, art in enumerate(all_articles, 1):
        cat, _ = classify(art)
        tag = f"[{cat}]" if cat != "其他" else ""
        title = art.get('title', '').replace('\xa0', ' ').strip()
        print(f"\n#{i} {tag} [{art.get('source','')}] {title}")
        if art.get("summary"):
            summary = art['summary'].replace('\xa0', ' ').strip()
            print(f"   >> {summary}")
        if art.get("link"):
            print(f"   -> {art['link']}")
    print()
    print("=" * 50)

    # 发送邮件
    send_email(email_cfg, all_articles)


if __name__ == "__main__":
    main()
