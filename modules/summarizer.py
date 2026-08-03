"""摘要模块 - AI / 本地摘要生成"""

import logging
import os
import re

import requests

logger = logging.getLogger("news")


def _get_api_key(item: dict) -> str:
    """获取 API key：优先用 item 里指定的 api_key_env，否则读取 DEEPSEEK_API_KEY"""
    env_name = item.get("api_key_env", "") or "DEEPSEEK_API_KEY"
    return os.environ.get(env_name, "")


def _build_prompt(text: str, language: str) -> str:
    lang_label = "中文" if language == "zh" else "英文"
    return (
        f"请用{lang_label}为以下新闻写一段摘要（100-200字），"
        f"涵盖核心事实、关键数据、各方观点或背景，让读者无需点击原文也能了解全貌：\n\n{text[:3000]}"
    )


def _call_api(api_key: str, model: str, prompt: str, base_url: str = "https://api.deepseek.com") -> str | None:
    """调用 OpenAI 兼容 API（deepseek 等）"""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 400,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "").strip()
    except Exception as e:
        logger.warning("API call failed: %s", e)
    return None


def _ai_summarize(text: str, language: str, item: dict) -> str | None:
    api_key = _get_api_key(item)
    if not api_key:
        logger.debug("DEEPSEEK_API_KEY not set, skip AI summary")
        return None

    model = item.get("model", "deepseek-chat")
    base_url = item.get("base_url", "https://api.deepseek.com")
    prompt = _build_prompt(text, language)
    return _call_api(api_key, model, prompt, base_url)


def _is_metadata(text: str) -> bool:
    """判断文本是否只是 RSS 元数据而非文章正文"""
    url_count = len(re.findall(r"https?://\S+", text))
    word_count = len(text.split())
    if word_count > 0 and url_count / word_count > 0.3:
        return True

    meta_keywords = [
        "article url", "comments url", "points", "comments",
        "published", "updated", "source", "category",
    ]
    lower = text.lower()
    meta_hits = sum(1 for kw in meta_keywords if kw in lower)
    if meta_hits >= 2:
        return True

    return False


def _summarize_local(article: dict) -> str:
    """本地摘要：有正文取第一句，只有元数据则返回空"""
    snippet = article.get("snippet", "")
    if not snippet:
        return ""

    if _is_metadata(snippet):
        return ""

    sentences = re.split(r"[。！？\n]", snippet)
    first = sentences[0].strip() if sentences else ""
    if len(first) > 150:
        first = first[:147] + "..."
    return first if first else ""


def summarize(article: dict, language: str = "zh", ai_cfg: list | dict | None = None) -> dict:
    text = article.get("snippet", "") or article.get("title", "")
    if not text:
        article["summary"] = ""
        return article

    summary = None
    if ai_cfg:
        if isinstance(ai_cfg, dict):
            ai_cfg = [ai_cfg]
        for item in ai_cfg:
            summary = _ai_summarize(text, language, item)
            if summary:
                break

    if not summary:
        summary = _summarize_local(article)
    article["summary"] = summary
    return article


def summarize_all(articles: list[dict], language: str = "zh", ai_cfg: list | dict | None = None) -> list[dict]:
    return [summarize(art, language, ai_cfg) for art in articles]
