"""解析模块 - 从RSS/HTML提取新闻要素"""

import logging
import re
from html import unescape
from xml.etree import ElementTree

from bs4 import BeautifulSoup

logger = logging.getLogger("news")


def _parse_rss(content: str, source_name: str, max_articles: int) -> list[dict]:
    articles = []
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        logger.warning("[%s] XML parse error", source_name)
        return articles

    for item in root.iter("item"):
        if len(articles) >= max_articles:
            break
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        pub_el = item.find("pubDate")
        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        link = link_el.text.strip() if link_el is not None and link_el.text else ""
        description = desc_el.text.strip() if desc_el is not None and desc_el.text else ""
        pub_date = pub_el.text.strip() if pub_el is not None and pub_el.text else ""
        if not title:
            continue
        plain_text = (
            BeautifulSoup(description, "html.parser").get_text(separator=" ")
            if description
            else ""
        )
        plain_text = re.sub(r"\s+", " ", plain_text).strip()
        articles.append({
            "title": unescape(title),
            "link": link,
            "snippet": plain_text[:500],
            "pub_date": pub_date,
            "source": source_name,
        })

    ns = "{http://www.w3.org/2005/Atom}"
    for entry in root.iter(f"{ns}entry"):
        if len(articles) >= max_articles:
            break
        title_el = entry.find(f"{ns}title")
        link_el = entry.find(f"{ns}link")
        summary_el = entry.find(f"{ns}summary")
        updated_el = entry.find(f"{ns}updated")
        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        link = link_el.get("href", "") if link_el is not None else ""
        summary_text = ""
        if summary_el is not None and summary_el.text:
            summary_text = BeautifulSoup(summary_el.text, "html.parser").get_text(separator=" ")
        pub_date = updated_el.text.strip() if updated_el is not None and updated_el.text else ""
        if not title:
            continue
        articles.append({
            "title": unescape(title),
            "link": link,
            "snippet": summary_text[:500] if summary_text else "",
            "pub_date": pub_date,
            "source": source_name,
        })

    logger.info("[%s] Parsed %d articles", source_name, len(articles))
    return articles


def _parse_html(content: str, source_name: str, max_articles: int) -> list[dict]:
    articles = []
    soup = BeautifulSoup(content, "html.parser")
    for tag in ["article", "li", "div"]:
        items = soup.find_all(tag, class_=re.compile(r"(post|news|item|article|entry)", re.I))
        if not items:
            items = soup.select(
                f'{tag}[class*="post"], {tag}[class*="news"], {tag}[class*="item"]'
            )
        for item in items:
            if len(articles) >= max_articles:
                break
            title_el = item.find(["h1", "h2", "h3", "h4", "a"])
            if title_el is None:
                continue
            title = title_el.get_text(strip=True)
            link = ""
            if title_el.name == "a":
                link = title_el.get("href", "")
            elif title_el.find("a"):
                link = title_el.find("a").get("href", "")
            if link and not link.startswith("http"):
                link = source_name + "/" + link.lstrip("/")
            snippet = item.get_text(separator=" ", strip=True)[:300]
            articles.append({
                "title": title,
                "link": link,
                "snippet": snippet,
                "pub_date": "",
                "source": source_name,
            })
    logger.info("[%s] HTML parsed %d articles", source_name, len(articles))
    return articles


def parse(source: dict, raw_content: str | None, max_articles: int = 20) -> list[dict]:
    if not raw_content:
        return []
    source_type = source.get("type", "rss")
    source_name = source.get("name", "unknown")
    try:
        if source_type == "rss":
            return _parse_rss(raw_content, source_name, max_articles)
        elif source_type == "html":
            return _parse_html(raw_content, source_name, max_articles)
        else:
            stripped = raw_content.strip()
            if stripped.startswith("<?xml") or "<rss" in stripped[:200] or "<feed" in stripped[:200]:
                return _parse_rss(raw_content, source_name, max_articles)
            else:
                return _parse_html(raw_content, source_name, max_articles)
    except Exception as e:
        logger.exception("Parse error [%s]: %s", source_name, e)
        return []
