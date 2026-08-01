#!/usr/bin/env python3
"""全球财经 RSS 聚合器 — GitHub Actions 定时运行，抓取被本地网络屏蔽的全球财经源

输出 feed/aggregated.xml（标准 RSS 2.0），本地 daily-tool 通过 git pull 获取
"""

import email.utils
import logging
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from html import unescape
from xml.etree import ElementTree
from xml.etree.ElementTree import Element, SubElement

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("aggregator")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "aggregated.xml")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
}

# ── 全球财经源（GitHub Actions Runner 可访问）─────────────────────────
SOURCES = [
    # 北美
    {"name": "Bloomberg Markets", "url": "https://feeds.bloomberg.com/markets/news.rss"},
    {"name": "Reuters Business", "url": "https://feeds.reuters.com/reuters/businessNews"},
    {"name": "NYT Business", "url": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"},
    {"name": "CNN Business", "url": "https://edition.cnn.com/business/rss"},
    # 欧洲
    {"name": "Financial Times", "url": "https://www.ft.com/rss/home"},
    {"name": "BBC Business", "url": "https://feeds.bbci.co.uk/news/business/rss.xml"},
    {"name": "Economist Finance", "url": "https://www.economist.com/finance-and-economics/rss.xml"},
    # 亚太
    {"name": "Nikkei Asia", "url": "https://asia.nikkei.com/rss/feed"},
    {"name": "SCMP Business", "url": "https://www.scmp.com/rss/4/feed"},
]

FETCH_TIMEOUT = 20  # 秒
MAX_PER_SOURCE = 10  # 每源最多取几篇


# ── 工具函数 ──────────────────────────────────────────────────────────

def fetch_url(url: str) -> str | None:
    """HTTP GET，返回文本或 None"""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            raw = resp.read()
            # 编码检测
            content_type = resp.headers.get("Content-Type", "")
            encoding = "utf-8"
            if "charset=" in content_type:
                encoding = content_type.split("charset=")[-1].split(";")[0].strip()
            try:
                return raw.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                return raw.decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("Fetch failed [%s]: %s", url, e)
        return None


def _clean_html(html_text: str) -> str:
    """去除 HTML 标签，保留纯文本"""
    import re
    text = re.sub(r"<[^>]+>", " ", html_text)
    text = re.sub(r"\s+", " ", text)
    return unescape(text).strip()


def parse_feed(xml_content: str, source_name: str, max_items: int) -> list[dict]:
    """解析 RSS 2.0 或 Atom feed，返回标准化文章列表"""
    articles = []
    try:
        root = ElementTree.fromstring(xml_content)
    except ElementTree.ParseError as e:
        logger.warning("[%s] XML parse error: %s", source_name, e)
        return articles

    # ── RSS 2.0 ──
    for item in root.iter("item"):
        if len(articles) >= max_items:
            break
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        pub_el = item.find("pubDate")

        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        link = link_el.text.strip() if link_el is not None and link_el.text else ""
        snippet = _clean_html(desc_el.text) if desc_el is not None and desc_el.text else ""
        pub_date = pub_el.text.strip() if pub_el is not None and pub_el.text else ""

        if not title:
            continue
        articles.append({
            "title": title,
            "link": link,
            "snippet": snippet[:500],
            "pub_date": pub_date,
            "source": source_name,
        })

    # ── Atom ──
    ns = "{http://www.w3.org/2005/Atom}"
    for entry in root.iter(f"{ns}entry"):
        if len(articles) >= max_items:
            break
        title_el = entry.find(f"{ns}title")
        link_el = entry.find(f"{ns}link")
        summary_el = entry.find(f"{ns}summary")
        updated_el = entry.find(f"{ns}updated")

        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        link = link_el.get("href", "") if link_el is not None else ""
        summary = _clean_html(summary_el.text) if summary_el is not None and summary_el.text else ""
        pub_date = updated_el.text.strip() if updated_el is not None and updated_el.text else ""

        if not title:
            continue
        articles.append({
            "title": title,
            "link": link,
            "snippet": summary[:500],
            "pub_date": pub_date,
            "source": source_name,
        })

    logger.info("[%s] Parsed %d articles", source_name, len(articles))
    return articles


def generate_rss(articles: list[dict]) -> str:
    """将文章列表输出为标准 RSS 2.0 XML"""
    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")

    SubElement(channel, "title").text = "Global Financial News Aggregator"
    SubElement(channel, "description").text = "Aggregated financial news from Bloomberg, FT, Reuters, BBC, NYT, Economist, Nikkei Asia, SCMP"
    SubElement(channel, "link").text = "https://github.com/xhx/daily-tool"
    now_rfc = email.utils.format_datetime(datetime.now(timezone.utc))
    SubElement(channel, "lastBuildDate").text = now_rfc

    for art in articles:
        item = SubElement(channel, "item")
        SubElement(item, "title").text = art.get("title", "")
        SubElement(item, "link").text = art.get("link", "")
        SubElement(item, "description").text = art.get("snippet", "")
        if art.get("pub_date"):
            SubElement(item, "pubDate").text = art.get("pub_date")
        # 用 source 作为 category，方便本地区分
        SubElement(item, "category").text = art.get("source", "")

    tree = ElementTree.ElementTree(rss)
    ElementTree.indent(tree, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ElementTree.tostring(rss, encoding="unicode")


def main():
    logger.info("=== Global Financial News Aggregator ===")
    logger.info("Sources: %d", len(SOURCES))

    all_articles = []
    success_count = 0

    for src in SOURCES:
        name = src["name"]
        url = src["url"]
        raw = fetch_url(url)
        if not raw:
            continue
        articles = parse_feed(raw, name, MAX_PER_SOURCE)
        if articles:
            all_articles.extend(articles)
            success_count += 1
        # 温和节流
        time.sleep(0.5)

    if not all_articles:
        logger.error("No articles fetched from any source!")
        sys.exit(1)

    # 去重（按 title 前 80 字符）
    seen = set()
    unique = []
    for art in all_articles:
        key = art["title"][:80].strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(art)

    # 按 pub_date 倒序（无日期的排最后）
    def _sort_key(a):
        try:
            return email.utils.parsedate_to_datetime(a["pub_date"])
        except (ValueError, TypeError):
            return datetime.min.replace(tzinfo=timezone.utc)

    unique.sort(key=_sort_key, reverse=True)

    # 生成 RSS
    rss_xml = generate_rss(unique[:60])  # 最多 60 篇

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(rss_xml)

    logger.info("=== Done: %d sources OK, %d unique articles, %d in output ===",
                 success_count, len(unique), min(len(unique), 60))

    # GitHub Actions 输出摘要
    if "GITHUB_STEP_SUMMARY" in os.environ:
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(f"## 📰 Global Financial News Aggregator\n\n")
            f.write(f"**{success_count}/{len(SOURCES)}** sources OK, **{len(unique)}** unique articles\n\n")
            for i, art in enumerate(unique[:10], 1):
                f.write(f"{i}. **[{art['source']}]** {art['title'][:100]}\n")


if __name__ == "__main__":
    main()
