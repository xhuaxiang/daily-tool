"""正文抽取 - 为已选文章抓取原文并提取正文，供邮件自包含展示。

目标：阅读邮件即可了解新闻要点，不依赖点开原文（原文在部分网络环境下需要 VPN）。
抽取失败时回退到 RSS 摘要，不阻断流程。
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("news")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml",
}

_MAX_BYTES = 2_000_000       # 单页最多读取 2MB，防止异常页面拖垮任务
_MAX_TEXT = 6000             # 正文最多保留 6000 字符，供 AI 和邮件摘录使用
_MIN_FEED_TEXT = 800         # feed 已含足够正文时不再请求原文
_MIN_PARA_LEN = 20           # 过短的段落（导航、版权等）丢弃

_SKIP_TAGS = (
    "script", "style", "noscript", "nav", "header", "footer",
    "aside", "form", "iframe", "svg", "figure", "button",
)


def _clean_text(text: str) -> str:
    """压缩空白、去掉重复空行"""
    lines = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return "\n".join(lines)


def _node_text(node) -> str:
    paragraphs = []
    for p in node.find_all("p"):
        text = p.get_text(" ", strip=True)
        if len(text) >= _MIN_PARA_LEN:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def _extract_text(html: str) -> str:
    """从 HTML 中提取正文：优先 article/main，其次按段落文本量找最大容器"""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(_SKIP_TAGS):
        tag.decompose()

    # 新闻页通常有 article/main，命中后直接返回，避免遍历整页
    for selector in ("article", "main", "[role=main]"):
        for node in soup.select(selector):
            text = _node_text(node)
            if len(text) >= 400:
                return _clean_text(text)[:_MAX_TEXT]

    best = ""
    for node in soup.find_all(["div", "section"]):
        if node.find("p") is None:
            continue
        text = _node_text(node)
        if len(text) > len(best):
            best = text

    # 没有像样的 <p> 结构时，退回整页文本
    if len(best) < 200:
        best = soup.get_text("\n", strip=True)

    return _clean_text(best)[:_MAX_TEXT]


def _decode(resp: requests.Response) -> str:
    encoding = resp.encoding
    if not encoding or encoding.lower() == "iso-8859-1":
        encoding = resp.apparent_encoding or "utf-8"
    return resp.content[:_MAX_BYTES].decode(encoding, errors="replace")


def fetch_full_text(url: str, timeout: int = 10) -> str:
    """抓取并抽取单篇文章正文；失败返回空字符串"""
    if not url or not url.lower().startswith(("http://", "https://")):
        return ""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "").lower()
        if content_type and "html" not in content_type:
            logger.debug("Skip non-HTML content [%s]: %s", content_type, url)
            return ""
        return _extract_text(_decode(resp))
    except Exception as e:
        logger.debug("Full text fetch failed [%s]: %s", url, e)
        return ""


def enrich_articles(articles: list[dict], max_workers: int = 4, timeout: int = 10) -> list[dict]:
    """为文章补充 full_text / text_source。

    - feed 内容已经足够长：直接用，不再请求原文；
    - 其余文章并发抓取原文，失败回退到 feed snippet。
    """
    targets = []
    for art in articles:
        feed_text = (art.get("snippet") or "").strip()
        if len(feed_text) >= _MIN_FEED_TEXT:
            art["full_text"] = feed_text
            art["text_source"] = "feed"
        elif (art.get("link") or "").lower().startswith(("http://", "https://")):
            targets.append(art)
        else:
            art["full_text"] = feed_text
            art["text_source"] = "feed" if feed_text else "none"

    def _work(art: dict) -> tuple[dict, str]:
        return art, fetch_full_text(art.get("link", ""), timeout)

    if targets:
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
            futures = [pool.submit(_work, art) for art in targets]
            for future in as_completed(futures):
                art, text = future.result()
                if text:
                    art["full_text"] = text
                    art["text_source"] = "page"
                    logger.info("Full text OK [%s] (%d chars)", art.get("source", ""), len(text))
                else:
                    art["full_text"] = (art.get("snippet") or "").strip()
                    art["text_source"] = "feed" if art["full_text"] else "none"
                    logger.debug("Full text failed, fallback to feed: %s", art.get("link", ""))

    from_page = sum(1 for art in articles if art.get("text_source") == "page")
    logger.info("Full text extracted for %d/%d articles", from_page, len(articles))
    return articles
