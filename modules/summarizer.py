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
    "deepseek": "deepseek-v4-flash",
    "gemini": "gemini-2.0-flash-lite",
    "openai-compat": "gpt-4o-mini",
}

# AI 回复疑似"素材不足"拒答的匹配模式（命中则视为失败，不展示）
_REFUSAL_RE = re.compile(
    r"(缺少.{0,8}(?:原文|正文|内容|新闻)|"
    r"没有提供.{0,8}(?:原文|正文|内容)|"
    r"未提供.{0,8}(?:原文|正文|内容)|"
    r"无法.{0,8}(?:为您|生成|总结|完成|提供)|"
    r"只有标题|内容不足|信息不足|"
    r"您似乎忘记|"
    r"insufficient|cannot summarize|unable to summarize|no content provided)",
    re.I | re.S,
)


def _is_refusal(text: str) -> bool:
    """判断 AI 回复是否为'素材不足'类拒答"""
    return bool(text and _REFUSAL_RE.search(text))


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


def _make_prompts(text: str, title: str, lang_label: str) -> list[str]:
    """构造 [主 prompt, 兜底 prompt]。主 prompt 拒答时，用兜底强制基于标题生成。"""
    main = (
        f"请用{lang_label}为以下新闻写一段摘要（50-100字）。"
        f"注意：以下素材可能只是新闻标题或导语，内容有限，"
        f"请据此给出最有用、最精炼的摘要；若只有标题，请基于标题合理概括。"
        f"规则：必须直接输出摘要正文，禁止出现'缺少内容/无法生成/请提供原文'等任何说明文字。"
        f"\n\n{text[:3000]}"
    )
    fallback = (
        f"请用{lang_label}写一段新闻摘要（50-100字）。"
        f"以下是全部可用素材（可能只有标题）：\n\n"
        f"标题：{title[:200]}\n{text[:500]}\n\n"
        f"规则：必须直接输出摘要正文，禁止出现'缺少内容/无法生成/请提供原文'等任何说明文字；"
        f"即使素材只有标题，也要基于标题合理概括出有信息量的摘要。"
    )
    return [main, fallback]


def summarize_all(articles: list[dict], language: str = "zh", ai_cfg: list | dict | None = None) -> list[dict]:
    """批量生成摘要：AI 优先，拒答自动用兜底 prompt 重试，最终失败则摘要留空（不展示原文）"""
    if isinstance(ai_cfg, dict):
        ai_cfg = [ai_cfg]
    ai_cfg = ai_cfg or []

    lang_label = "中文" if language == "zh" else "英文"

    for art in articles:
        text = art.get("snippet", "") or art.get("title", "")
        if not text:
            art["summary"] = ""
            continue

        summary = None
        for item in ai_cfg:
            provider = item.get("provider", "")
            key = _api_key(item)
            if not key:
                logger.debug("[%s] API key not set, skip", provider)
                continue

            model = item.get("model") or _DEFAULT_MODELS.get(provider, "gpt-4o-mini")
            base_url = item.get("base_url") or _BASE_URLS.get(provider, "https://api.openai.com")
            # 主 prompt 拒答时，用兜底 prompt（强制基于标题概括）重试一次
            for attempt, prompt in enumerate(_make_prompts(text, art.get("title", ""), lang_label)):
                resp = _call_ai(key, model, prompt, base_url)
                if not resp:
                    break
                if _is_refusal(resp):
                    logger.info("[%s] AI 回复疑似拒答，%s", provider, "改用兜底 prompt 重试" if attempt == 0 else "已忽略")
                    continue
                summary = resp
                break
            if summary:
                break

        art["summary"] = summary or ""
        art["excerpt"] = _english_excerpt(art.get("snippet", ""))

    return articles

