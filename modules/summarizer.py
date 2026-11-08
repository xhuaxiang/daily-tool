"""摘要模块 - DeepSeek 摘要生成（OpenAI 兼容 API）。

输出结构化结果，供邮件自包含展示：
- title_zh：中文标题
- points：3 条中文要点
- excerpt_zh：一句话核心结论
AI 不可用时回退到原文首句，保证邮件里始终有可读内容。
"""

import json
import logging
import os
import re

import requests

logger = logging.getLogger("news")

# 仅支持 DeepSeek
_PROVIDER = "deepseek"
_DEFAULT_API_KEY_ENV = "DEEPSEEK_API_KEY"
_DEFAULT_BASE_URL = "https://api.deepseek.com"
_DEFAULT_MODEL = "deepseek-v4-flash"

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
    """获取 API key：item.api_key > item.api_key_env 环境变量 > DEEPSEEK_API_KEY"""
    if key := item.get("api_key", ""):
        return key
    env_name = item.get("api_key_env", "") or _DEFAULT_API_KEY_ENV
    return os.environ.get(env_name, "")


def _call_ai(api_key: str, model: str, prompt: str, base_url: str) -> str | None:
    """通用 OpenAI 兼容 API 调用"""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 600,
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
    """构造 [主 prompt, 兜底 prompt]，要求模型输出结构化 JSON。"""
    schema = '{"title_zh": "中文标题", "points": ["要点1", "要点2", "要点3"], "excerpt_zh": "一句话核心结论"}'
    main = (
        f"你是新闻编辑。请阅读以下新闻素材，用{lang_label}输出严格 JSON（不要 markdown 代码块，不要任何额外文字）：\n"
        f"{schema}\n\n"
        f"要求：\n"
        f"1. title_zh：把标题翻译或改写成简洁的中文标题；原标题已是中文时保留原意；\n"
        f"2. points：输出 3 条要点，每条不超过 60 字，必须包含素材中的关键数字、主体和动作；\n"
        f"3. excerpt_zh：一句话核心结论，不超过 50 字；\n"
        f"4. 只使用素材中明确出现的信息，禁止推测、补充背景或编造；\n"
        f"5. 素材不足时 points 可以少于 3 条，但不得编造；\n"
        f"6. 标题和要点使用自然中文，除专有名词外不要中英混杂。\n\n"
        f"标题：{title[:300]}\n素材：\n{text[:4000]}"
    )
    fallback = (
        f"请仅根据下面的标题和素材，用{lang_label}输出严格 JSON（不要代码块、不要额外文字）：\n"
        f"{schema}\n\n"
        f"要求：\n"
        f"1. title_zh 按标题字面翻译或转述；\n"
        f"2. points 只复述素材中明确写出的信息；素材不足时宁可少写，不要编造；\n"
        f"3. 禁止出现'无法生成/请提供原文/内容不足'等说明文字。\n\n"
        f"标题：{title[:300]}\n素材：\n{text[:800]}"
    )
    return [main, fallback]


def _parse_ai_json(text: str) -> dict | None:
    """解析模型返回的 JSON；兼容代码块包裹和前后多余文字。"""
    if not text:
        return None
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S | re.I)
    if fence:
        raw = fence.group(1).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    title = str(data.get("title_zh") or "").strip()
    points = data.get("points")
    if isinstance(points, str):
        points = [points]
    if not isinstance(points, list):
        return None

    cleaned = []
    for point in points:
        point = re.sub(r"^[\s•\-*·]+", "", str(point).strip()).strip()
        if point:
            cleaned.append(point[:200])
    if not title and not cleaned:
        return None
    return {
        "title_zh": title,
        "points": cleaned[:5],
        "excerpt_zh": str(data.get("excerpt_zh") or "").strip(),
    }


def _local_summary(art: dict) -> str:
    """AI 不可用时的本地兜底：取正文/摘要的前 1-2 句。"""
    text = (art.get("full_text") or art.get("snippet") or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    sentences = re.split(r"(?<=[。.!?！？])\s*", text)
    out = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(out) + len(sentence) > 160:
            break
        out = f"{out} {sentence}".strip()
    if not out:
        out = text[:160]
    return out[:160] + ("..." if len(out) > 160 else "")


def _summarize_one(art: dict, ai_cfg: list[dict], lang_label: str) -> dict | None:
    title = (art.get("title") or "").strip()
    text = (art.get("full_text") or art.get("snippet") or title).strip()
    if not text:
        return None

    for item in ai_cfg:
        provider = (item.get("provider") or _PROVIDER).strip().lower()
        if provider != _PROVIDER:
            logger.warning("Unsupported AI provider '%s', only deepseek is supported; skip", provider)
            continue

        key = _api_key(item)
        if not key:
            logger.debug("[%s] API key not set, skip", provider)
            continue

        model = item.get("model") or _DEFAULT_MODEL
        base_url = item.get("base_url") or _DEFAULT_BASE_URL
        # 主 prompt 拒答时，用兜底 prompt（强制基于标题概括）重试一次
        for attempt, prompt in enumerate(_make_prompts(text, title, lang_label)):
            resp = _call_ai(key, model, prompt, base_url)
            if not resp:
                break
            parsed = _parse_ai_json(resp)
            if parsed:
                return parsed
            if _is_refusal(resp):
                logger.info(
                    "[%s] AI 回复疑似拒答，%s",
                    provider,
                    "改用兜底 prompt 重试" if attempt == 0 else "已忽略",
                )
                continue
            # 模型没按 JSON 输出，但内容可用：作为单条要点
            cleaned = resp.strip()
            if len(cleaned) >= 10:
                return {"title_zh": "", "points": [cleaned], "excerpt_zh": ""}
            break
    return None


def summarize_all(articles: list[dict], language: str = "zh", ai_cfg: list | dict | None = None) -> list[dict]:
    """批量生成结构化摘要：AI 优先，失败回退到原文首句，保证邮件始终有内容。"""
    if isinstance(ai_cfg, dict):
        ai_cfg = [ai_cfg]
    ai_cfg = ai_cfg or []

    lang_label = "中文" if language == "zh" else "英文"

    for art in articles:
        parsed = _summarize_one(art, ai_cfg, lang_label)
        if parsed and parsed["points"]:
            art["title_zh"] = parsed["title_zh"] or art.get("title", "")
            art["summary_points"] = parsed["points"]
            art["summary"] = "\n".join(parsed["points"])
            art["summary_status"] = "ok"
        else:
            art["title_zh"] = art.get("title", "")
            fallback = _local_summary(art)
            art["summary_points"] = [fallback] if fallback else []
            art["summary"] = fallback
            art["summary_status"] = "local"
        art["excerpt"] = _english_excerpt(art.get("snippet", ""))

    return articles

