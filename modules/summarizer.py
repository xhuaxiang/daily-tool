<<<<<<< HEAD
"""摘要模块 - AI / 本地摘要生成，所有 provider 统一走 OpenAI 兼容 API。"""
=======
"""摘要模块 - AI / 本地摘要生成"""
>>>>>>> 27236778aaa9982d5d782b700c0927079270510a

import logging
import os
import re

import requests

logger = logging.getLogger("news")

<<<<<<< HEAD
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
=======

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
>>>>>>> 27236778aaa9982d5d782b700c0927079270510a
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
<<<<<<< HEAD
        logger.warning("AI API call failed (%s/%s): %s", base_url, model, e)
    return None


def _local_summary(article: dict) -> str:
    """本地摘要：取正文第一句"""
    snippet = article.get("snippet", "")
    if not snippet:
        return ""
=======
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

>>>>>>> 27236778aaa9982d5d782b700c0927079270510a
    sentences = re.split(r"[。！？\n]", snippet)
    first = sentences[0].strip() if sentences else ""
    if len(first) > 150:
        first = first[:147] + "..."
    return first


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
    """批量生成摘要：AI 优先，失败则本地 fallback"""
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

        art["summary"] = summary or _local_summary(art)
        art["excerpt"] = _english_excerpt(art.get("snippet", ""))

<<<<<<< HEAD
    return articles

=======
def summarize_all(articles: list[dict], language: str = "zh", ai_cfg: list | dict | None = None) -> list[dict]:
    return [summarize(art, language, ai_cfg) for art in articles]
>>>>>>> 27236778aaa9982d5d782b700c0927079270510a
