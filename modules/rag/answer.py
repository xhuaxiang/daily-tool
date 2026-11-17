"""R1 单轮问答：把检索到的块拼成 prompt，并校验模型给的引用。

引用校验是硬约束：chunk_id 必须来自本次检索结果，quote 必须是原文子串，
否则丢弃。没有有效引用时，调用方只展示标题和链接。
"""

from __future__ import annotations

import json
import re

from modules.summarizer import complete

MAX_CHUNK_CHARS = 1200

PROMPT_TEMPLATE = """你是新闻检索助手。只依据下面给出的资料回答，不要使用资料以外的知识。

规则：
1. 用中文回答，控制在 3-6 句。
2. 每个论断后面标出引用编号，如 [1]。
3. 只输出 JSON，不要输出解释或代码块，格式：
   {{"answer": "...", "citations": [{{"chunk_id": "...", "quote": "原文片段"}}]}}
4. quote 必须是资料里连续的一段原文，不能改写、不能拼接。
5. 资料不足以回答时，answer 写“资料中没有相关信息”，citations 为空数组。

资料：
{context}

问题：{question}
"""


def format_context(chunks: list[dict], max_chars: int = MAX_CHUNK_CHARS) -> str:
    """把检索结果拼成带编号的资料块，过长的块截断。"""
    parts = []
    for index, chunk in enumerate(chunks, 1):
        header = "｜".join(
            value for value in (
                chunk.get("title_zh") or chunk.get("title") or "",
                chunk.get("publisher") or chunk.get("source") or "",
                (chunk.get("published") or "")[:10],
            )
            if value
        )
        text = (chunk.get("text") or "").strip()
        if len(text) > max_chars:
            text = text[:max_chars] + "…"
        parts.append(f"[{index}] chunk_id={chunk['chunk_id']}\n{header}\n{text}")
    return "\n\n".join(parts)


def build_prompt(question: str, chunks: list[dict]) -> str:
    return PROMPT_TEMPLATE.format(
        context=format_context(chunks),
        question=question.strip(),
    )


def parse_answer(text: str) -> dict | None:
    """从模型回复里抠出 JSON，容忍代码块和前后多余文字。"""
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def validate_citations(citations, chunks: list[dict]) -> tuple[list[dict], list[dict]]:
    """保留 chunk_id 存在且 quote 为原文子串的引用，其余记入 invalid。"""
    by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
    valid, invalid = [], []
    for item in citations if isinstance(citations, list) else []:
        if not isinstance(item, dict):
            continue
        chunk_id = str(item.get("chunk_id") or "").strip()
        quote = str(item.get("quote") or "").strip()
        chunk = by_id.get(chunk_id)
        if not chunk or not quote:
            invalid.append({"chunk_id": chunk_id, "quote": quote, "reason": "缺少块或引用"})
            continue
        if _normalize(quote) not in _normalize(chunk.get("text") or ""):
            invalid.append({"chunk_id": chunk_id, "quote": quote, "reason": "quote 不在原文中"})
            continue
        valid.append({
            "chunk_id": chunk_id,
            "quote": quote,
            "title": chunk.get("title_zh") or chunk.get("title") or "",
            "link": chunk.get("link") or "",
            "published": chunk.get("published") or "",
        })
    return valid, invalid


def answer_question(
    question: str,
    chunks: list[dict],
    ai_cfg,
    *,
    complete_fn=complete,
) -> dict:
    """调用模型并校验引用；不抛异常，返回带状态的结果。"""
    if not chunks:
        return {"status": "no_context", "answer": "", "citations": [], "invalid": []}

    raw = complete_fn(build_prompt(question, chunks), ai_cfg)
    if not raw:
        return {"status": "llm_failed", "answer": "", "citations": [], "invalid": []}

    parsed = parse_answer(raw)
    if not parsed:
        return {
            "status": "unparsed",
            "answer": raw.strip(),
            "citations": [],
            "invalid": [],
        }

    valid, invalid = validate_citations(parsed.get("citations"), chunks)
    answer = str(parsed.get("answer") or "").strip()
    if not valid:
        return {
            "status": "no_citation",
            "answer": answer,
            "citations": [],
            "invalid": invalid,
        }
    return {
        "status": "ok",
        "answer": answer,
        "citations": valid,
        "invalid": invalid,
    }
