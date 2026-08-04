"""摘要模块 - AI / 本地摘要生成，所有 provider 统一走 OpenAI 兼容 API。"""

import logging
import os
import re

import requests

logger = logging.getLogger("news")

# provider → 默认环境变量
_DEFAULT_ENV = {"deepseek": "DEEPSEEK_API_KEY", "gemini": "GEMINI_API_KEY"}

# provider → base_url（均为 OpenAI 兼容端点）
_BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openai-compat": "https://api.openai.com",
}

# provider → 默认模型
_DEFAULT_MODELS = {
    "deepseek": "deepseek-chat",
    "gemini": "gemini-2.0-flash-lite",
    "openai-compat": "gpt-4o-mini",
}


def _api_key(item: dict) -> str:
    """获取 API key：item.api_key > item.api_key_env 环境变量 > provider 默认环境变量"""
    if key := item.get("api_key", ""):
        return key
    provider = item.get("provider", "")
    env_name = item.get("api_key_env", "") or _DEFAULT_ENV.get(provider, "")
    return os.environ.get(env_name, "")


def _call_ai(api_key: str, model: str, prompt: str, base_url: str) -> str | None:
    """通用 OpenAI 兼容 API 调用"""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
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
        logger.warning("AI API call failed (%s/%s): %s", base_url, model, e)
    return None


def _english_excerpt(snippet: str) -> str:
    """提取英文原文前 1-2 句，100-150 字符，仅处理英文为主的文本"""
    if not snippet:
        return ""
    ascii_ratio = sum(1 for c in snippet if ord(c) < 128) / max(len(snippet), 1)
    if ascii_ratio < 0.5:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", snippet)
    result = ""
    for s in sentences[:2]:
        if len(result) + len(s) > 150:
            break
        result += s + " "
    result = result.strip()
    if len(result) > 150:
        result = result[:147] + "..."
    return result


def summarize_all(articles: list[dict], language: str = "zh", ai_cfg: list | dict | None = None) -> list[dict]:
    """批量生成摘要：AI 优先，失败则摘要留空（不展示 fallback）"""
    if isinstance(ai_cfg, dict):
        ai_cfg = [ai_cfg]
    ai_cfg = ai_cfg or []

    lang_label = "中文" if language == "zh" else "英文"

    for art in articles:
        text = art.get("snippet", "") or art.get("title", "")
        if not text:
            art["summary"] = ""
            continue

        prompt = (
            f"请用{lang_label}为以下新闻写一段摘要（100-200字），"
            f"涵盖核心事实、关键数据、各方观点或背景，让读者无需点击原文也能了解全貌：\n\n{text[:3000]}"
        )

        summary = None
        for item in ai_cfg:
            provider = item.get("provider", "")
            key = _api_key(item)
            if not key:
                logger.debug("[%s] API key not set, skip", provider)
                continue

            model = item.get("model") or _DEFAULT_MODELS.get(provider, "gpt-4o-mini")
            base_url = item.get("base_url") or _BASE_URLS.get(provider, "https://api.openai.com")
            summary = _call_ai(key, model, prompt, base_url)
            if summary:
                break

        art["summary"] = summary or ""
        art["excerpt"] = _english_excerpt(art.get("snippet", ""))

    return articles

