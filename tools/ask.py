#!/usr/bin/env python3
"""R1 单轮问答：从归档检索 + 引用校验后回答。

示例：
    python tools/ask.py "上周美联储做了什么"
    python tools/ask.py "英伟达财报" --top-k 8
    python tools/ask.py "英伟达财报" --no-llm     # 只看检索结果，不需要 LLM key
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.config import load_config
from modules.rag.answer import answer_question
from modules.rag.embedding import EmbeddingError, embed_texts, embedding_settings, model_key
from modules.rag.index import build_index, find_archive_files, load_articles
from modules.rag.store import IndexStore


def _print_hits(chunks: list[dict], *, preview: bool) -> None:
    print(f"\n[检索] 命中 {len(chunks)} 块")
    for index, chunk in enumerate(chunks, 1):
        title = chunk.get("title_zh") or chunk.get("title") or "(无标题)"
        meta = "｜".join(
            value for value in (
                chunk.get("publisher") or chunk.get("source") or "",
                (chunk.get("published") or "")[:10],
            )
            if value
        )
        print(f" {index}. {chunk['score']:.3f}  {title}  {meta}")
        if preview:
            text = " ".join((chunk.get("text") or "").split())
            print(f"    {text[:180]}{'…' if len(text) > 180 else ''}")
            print(f"    {chunk.get('link') or ''}")


def _print_answer(result: dict, chunks: list[dict]) -> None:
    status = result["status"]
    if status == "ok":
        print("\n[回答]")
        print(result["answer"])
        print("\n[引用]")
        for index, cite in enumerate(result["citations"], 1):
            print(f" [{index}] {cite['title']}  {cite['published'][:10]}")
            print(f"      {cite['quote'][:160]}")
            print(f"      {cite['link']}")
        if result["invalid"]:
            print(f"\n[已丢弃 {len(result['invalid'])} 条无效引用]")
            for item in result["invalid"]:
                print(f"  - {item['reason']}: {item['quote'][:60]}")
        return

    if status == "no_citation":
        print("\n[回答]")
        print(result["answer"])
        print("\n没有通过校验的引用，以下只列标题和链接：")
        seen = set()
        for chunk in chunks:
            link = chunk.get("link") or ""
            if not link or link in seen:
                continue
            seen.add(link)
            title = chunk.get("title_zh") or chunk.get("title") or ""
            print(f"  - {title}  {link}")
        return

    print(f"\n[回答失败] status={status}")
    if result.get("answer"):
        print(result["answer"])


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="R1 单轮问答（检索 + 引用校验）")
    parser.add_argument("question", help="要问的问题")
    parser.add_argument(
        "--input", action="append", default=[],
        help="归档文件或目录，可重复；默认 reports/runs",
    )
    parser.add_argument("--db", default="", help="索引库路径，默认 config.rag.db_path")
    parser.add_argument("--top-k", type=int, default=5, help="检索块数，默认 5")
    parser.add_argument("--no-llm", action="store_true", help="只检索，不调用模型")
    parser.add_argument("--rebuild", action="store_true", help="重建索引")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    config = load_config()
    rag = config.get("rag") if isinstance(config.get("rag"), dict) else {}
    db_path = Path(args.db or rag.get("db_path") or "data/rag/index.db")
    if not db_path.is_absolute():
        db_path = _ROOT / db_path

    inputs = args.input or [str(_ROOT / "reports" / "runs")]
    try:
        paths = find_archive_files(inputs)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))
    if not paths:
        raise SystemExit("没有找到 articles-*.json；先运行 tools/fetch_attachments.py")
    articles = load_articles(paths)
    if not articles:
        raise SystemExit("归档里没有文章")

    try:
        stats = build_index(
            articles, db_path=db_path, config=config, rebuild=args.rebuild,
        )
        vectors = embed_texts([args.question], config=config)
    except EmbeddingError as exc:
        raise SystemExit(f"检索失败：{exc}")

    with IndexStore(db_path) as store:
        index_model = store.latest_model()
        query_model = model_key(embedding_settings(config))
        if index_model and index_model != query_model:
            print(
                f"警告：索引模型 {index_model} 与当前 embedding {query_model} 不一致，"
                "请先 --rebuild"
            )
        try:
            chunks = store.search(vectors[0], top_k=args.top_k, model=index_model)
        except ValueError as exc:
            raise SystemExit(f"检索失败：{exc}")

    print(
        f"[索引] 文章 {stats['articles']}  块 {stats['chunks']}  "
        f"模型 {stats['model']}"
    )
    if not chunks:
        raise SystemExit("没有检索到任何块")

    if args.no_llm:
        _print_hits(chunks, preview=True)
        return

    print(f"[问题] {args.question}")
    _print_hits(chunks, preview=False)
    result = answer_question(args.question, chunks, config.get("ai"))
    _print_answer(result, chunks)


if __name__ == "__main__":
    main()
