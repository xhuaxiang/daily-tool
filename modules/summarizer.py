"""摘要模块 - 可配置 AI / 本地摘要生成

AI provider 的 API key 按以下约定从环境变量读取：

  provider       | 默认环境变量
  ---------------|------------------
  gemini         | GEMINI_API_KEY
  deepseek       | DEEPSEEK_API_KEY
  openai-compat  | 需在配置中指定 api_key_env

config.json 示例：
  "ai": [
    { "provider": "gemini", "model": "gemini-2.0-flash-lite" },
    { "provider": "deepseek", "model": "deepseek-chat" }
  ]
"""

import logging
import os
import re

import requests

logger = logging.getLogger("news")

# 每个 provider 对应的默认环境变量名
_DEFAULT_ENV = {
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


def _get_api_key(item: dict) -> str:
    """获取 API key：优先用 item 里指定的 api_key_env，否则按 provider 默认"""
    provider = item.get("provider", "")
    env_name = item.get("api_key_env", "") or _DEFAULT_ENV.get(provider, "")
    return os.environ.get(env_name, "")


def _build_prompt(text: str, language: str) -> str:
    lang_label = "中文" if language == "zh" else "英文"
    return (
        f"请用{lang_label}为以下新闻写一句话摘要（不超过50字），"
        f"要求准确概括核心信息，保留关键数据：\n\n{text[:2000]}"
    )


def _call_gemini(api_key: str, model: str, prompt: str) -> str | None:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 100},
    }
    try:
        resp = requests.post(url, params={"key": api_key}, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [])
        if candidates:
            return candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
    except Exception as e:
        logger.warning("Gemini API call failed: %s", e)
    return None


def _call_openai_compat(api_key: str, model: str, prompt: str, base_url: str) -> str | None:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 100,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "").strip()
    except Exception as e:
        logger.warning("OpenAI-compat API call failed: %s", e)
    return None


def _ai_summarize(text: str, language: str, item: dict) -> str | None:
    provider = item.get("provider", "")
    api_key = _get_api_key(item)

    if not api_key:
        logger.debug("[%s] API key not set, skip", provider)
        return None

    prompt = _build_prompt(text, language)

    if provider == "gemini":
        model = item.get("model", "gemini-2.0-flash-lite")
        return _call_gemini(api_key, model, prompt)

    elif provider == "deepseek":
        model = item.get("model", "deepseek-chat")
        return _call_openai_compat(api_key, model, prompt, "https://api.deepseek.com")

    elif provider == "openai-compat":
        model = item.get("model", "gpt-4o-mini")
        base_url = item.get("base_url", "https://api.openai.com")
        return _call_openai_compat(api_key, model, prompt, base_url)

    else:
        logger.warning("Unknown AI provider: %s", provider)
        return None


def _is_metadata(text: str) -> bool:
    """判断文本是否只是 RSS 元数据而非文章正文"""
    # 如果片段里 URL 占比很高，说明是元数据
    url_count = len(re.findall(r"https?://\S+", text))
    word_count = len(text.split())
    if word_count > 0 and url_count / word_count > 0.3:
        return True

    # 常见元数据关键词
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
    """本地摘要：有正文取第一句，只有元数据则返回空（交给调用方决定是否显示）"""
    snippet = article.get("snippet", "")
    title = article.get("title", "")

    if not snippet:
        return ""

    # 如果 snippet 全是 RSS 元数据（如 HN 的 "Article URL: ... Points: ..."），不要
    if _is_metadata(snippet):
        return ""

    # 正常情况：取第一句
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

