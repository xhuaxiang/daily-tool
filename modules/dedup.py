"""去重模块 - 过滤同一/不同站点的重复新闻。

命中以下任一条件即视为重复：
1. 规范化 URL 相同（忽略跟踪参数、末尾斜杠、www 前缀）；
2. 规范化标题相同（忽略大小写、标点、HTML 实体、来源后缀）；
3. 标题高度相似（仅比较长标题，且数字/月份/星期一致，避免误合并不同日期/金额的新闻）；
4. 摘要高度相似（应对同一篇通稿被不同站点改标题转载）。

保留信息更新的一条：发布时间最新优先，其次摘要更长。
"""

import html
import logging
import re
import unicodedata
from difflib import SequenceMatcher
from datetime import timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

logger = logging.getLogger("news")

# 常见跟踪参数，不参与 URL 身份判断
_TRACKING_PARAM_RE = re.compile(
    r"^(utm_\w+|fbclid|gclid|dclid|msclkid|yclid|igshid|mc_cid|mc_eid|cmpid|spm|sr_share)$",
    re.I,
)

# 标题末尾的来源后缀分隔符，如 "Fed cuts rates - CNBC"
_SUFFIX_SEP_RE = re.compile(r"[\s\-–—|:·]+\s*([^\-–—|:·]{1,50})\s*$")

_WHITESPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[\W_]+")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

# 月份/星期词：仅在两边都存在且不一致时阻止合并
_DATE_WORD_RE = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
    r"monday|mon|tuesday|tue|wednesday|wed|thursday|thu|"
    r"friday|fri|saturday|sat|sunday|sun)\b",
    re.I,
)

_DATE_CANON = {
    "jan": "january", "feb": "february", "mar": "march", "apr": "april",
    "jun": "june", "jul": "july", "aug": "august", "sep": "september",
    "sept": "september", "oct": "october", "nov": "november", "dec": "december",
    "mon": "monday", "tue": "tuesday", "wed": "wednesday", "thu": "thursday",
    "fri": "friday", "sat": "saturday", "sun": "sunday",
}


def _date_tokens(text: str) -> set[str]:
    return {_DATE_CANON.get(w.lower(), w.lower()) for w in _DATE_WORD_RE.findall(text)}


# 标题模糊匹配：短标题风险高（如 "11月" vs "10月"），只比较长标题
_FUZZY_MIN_TITLE_LEN = 20
_FUZZY_THRESHOLD = 0.9

# 摘要模糊匹配：5-gram 集合的 Jaccard 相似度
_SNIPPET_MIN_CHARS = 200
_SNIPPET_MAX_CHARS = 800
_SNIPPET_GRAM = 5
_SNIPPET_THRESHOLD = 0.7


def _normalize_text(text: str) -> str:
    """转小写、去标点/多余空白，保留中英文与数字"""
    return _WHITESPACE_RE.sub(" ", _NON_WORD_RE.sub(" ", text.casefold())).strip()


def normalize_title(title: str, source_names: set[str] | None = None) -> str:
    """规范化标题：去 HTML 实体、统一全半角、去来源后缀、去标点"""
    if not title:
        return ""
    text = unicodedata.normalize("NFKC", html.unescape(title))
    if source_names:
        m = _SUFFIX_SEP_RE.search(text)
        if m and _normalize_text(m.group(1)) in source_names:
            text = text[:m.start()]
    return _normalize_text(text)


def normalize_url(url: str) -> str:
    """规范化 URL：去 fragment、跟踪参数、末尾斜杠，忽略 www 前缀"""
    url = (url or "").strip()
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _TRACKING_PARAM_RE.match(k)
    ]
    path = parts.path.rstrip("/") or "/"
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return urlunsplit((parts.scheme.lower() or "https", netloc, path, urlencode(query), ""))


def _url_key(url: str) -> str:
    """仅对具体文章页返回 URL key，站点首页不参与去重"""
    key = normalize_url(url)
    if key and urlsplit(key).path not in ("", "/"):
        return key
    return ""


def _titles_similar(a: str, b: str, threshold: float) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    if min(len(a), len(b)) < _FUZZY_MIN_TITLE_LEN:
        return False
    if abs(len(a) - len(b)) > max(len(a), len(b)) * 0.4:
        return False
    nums_a = set(_NUMBER_RE.findall(a))
    nums_b = set(_NUMBER_RE.findall(b))
    if nums_a and nums_b and nums_a != nums_b:
        return False
    dates_a = _date_tokens(a)
    dates_b = _date_tokens(b)
    if dates_a and dates_b and dates_a != dates_b:
        return False
    matcher = SequenceMatcher(None, a, b)
    return matcher.quick_ratio() >= threshold and matcher.ratio() >= threshold


def _content_grams(snippet: str) -> set[str]:
    text = _normalize_text(snippet or "")
    if len(text) < _SNIPPET_MIN_CHARS:
        return set()
    text = text[:_SNIPPET_MAX_CHARS]
    return {text[i:i + _SNIPPET_GRAM] for i in range(len(text) - _SNIPPET_GRAM + 1)}


def _content_similar(a: set[str], b: set[str]) -> bool:
    if not a or not b:
        return False
    inter = len(a & b)
    return inter > 0 and inter / len(a | b) >= _SNIPPET_THRESHOLD


def _rank(article: dict, date_parser) -> tuple:
    """保留优先级：发布时间最新 > 摘要更长 > 标题更长"""
    timestamp = 0.0
    if date_parser:
        dt = date_parser(article.get("pub_date", ""))
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            timestamp = dt.timestamp()
    return (timestamp, len(article.get("snippet", "")), len(article.get("title", "")))


def dedupe(
    articles: list[dict],
    threshold: float = _FUZZY_THRESHOLD,
    source_names: list[str] | None = None,
    date_parser=None,
) -> list[dict]:
    """返回去重后的文章列表，重复时保留信息更新的一条"""
    names = {_normalize_text(n) for n in (source_names or []) if n}
    kept: list[dict] = []
    kept_titles: list[str] = []
    kept_grams: list[set[str]] = []
    kept_urls: list[str] = []
    url_index: dict[str, int] = {}

    for art in articles:
        title_key = normalize_title(art.get("title", ""), names)
        url_key = _url_key(art.get("link", ""))
        grams = _content_grams(art.get("snippet", ""))

        dup_idx = url_index.get(url_key) if url_key else None
        if dup_idx is None:
            for idx in range(len(kept)):
                if _titles_similar(title_key, kept_titles[idx], threshold) or _content_similar(
                    grams, kept_grams[idx]
                ):
                    dup_idx = idx
                    break

        if dup_idx is None:
            if url_key:
                url_index.setdefault(url_key, len(kept))
            kept.append(art)
            kept_titles.append(title_key)
            kept_grams.append(grams)
            kept_urls.append(url_key)
            continue

        # 重复：保留信息更新（时间更新/内容更全）的那一条
        if _rank(art, date_parser) > _rank(kept[dup_idx], date_parser):
            old_url = kept_urls[dup_idx]
            if old_url and url_index.get(old_url) == dup_idx:
                url_index.pop(old_url, None)
            kept[dup_idx] = art
            kept_titles[dup_idx] = title_key
            kept_grams[dup_idx] = grams
            kept_urls[dup_idx] = url_key
            if url_key:
                url_index.setdefault(url_key, dup_idx)

    removed = len(articles) - len(kept)
    if removed:
        logger.info("Deduped %d duplicate articles (%d -> %d)", removed, len(articles), len(kept))
    return kept
