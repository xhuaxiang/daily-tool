"""摘要模块 - AI(Gemini) / 本地摘要生成"""

import logging
import os
import re

import requests

logger = logging.getLogger("news")


def _summarize_with_gemini(text: str, language: str = "zh") -> str | None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.debug("GEMINI_API_KEY not set, skip AI summary")
        return None
    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-lite")
    lang_label = "中文" if language == "zh" else "英文"
    prompt = (
        f"请用{lang_label}为以下新闻写一句话摘要（不超过50字），"
        f"要求准确概括核心信息，保留关键数据：\n\n{text[:2000]}"
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    params = {"key": api_key}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 100},
    }
    try:
        resp = requests.post(url, params=params, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [])
        if candidates:
            result = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            return result.strip()
    except Exception as e:
        logger.warning("Gemini API call failed: %s", e)
    return None


def _summarize_local(text: str) -> str:
    if not text:
        return ""
    sentences = re.split(r"[。！？\n]", text)
    first = sentences[0].strip() if sentences else ""
    if len(first) > 150:
        first = first[:147] + "..."
    return first if first else text[:150]


def summarize(article: dict, language: str = "zh") -> dict:
    text = article.get("snippet", "") or article.get("title", "")
    if not text:
        article["summary"] = ""
        return article
    summary = _summarize_with_gemini(text, language)
    if not summary:
        summary = _summarize_local(text)
    article["summary"] = summary
    return article


def summarize_all(articles: list[dict], language: str = "zh") -> list[dict]:
    return [summarize(art, language) for art in articles]
