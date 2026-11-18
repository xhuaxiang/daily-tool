#!/usr/bin/env python3
"""R2/R3 检索评测：固定问题集上算 recall@k 和 MRR。

问题集是 JSONL，每行 {id, question, expect, note}，expect 是期望命中的链接片段。

示例：
    python tools/eval_retrieval.py                      # 纯向量基线
    python tools/eval_retrieval.py --mode keyword
    python tools/eval_retrieval.py --mode hybrid --rerank
    python tools/eval_retrieval.py --top-k 10 --json
    python tools/eval_retrieval.py --eval eval/rag_questions.jsonl --limit 5
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.config import load_config
from modules.rag.embedding import EmbeddingError, embed_texts
from modules.rag.index import build_index, find_archive_files, load_articles
from modules.rag.retrieval import MODES, Retriever
from modules.rag.store import IndexStore

DEFAULT_EVAL = _ROOT / "eval" / "rag_questions.jsonl"


def load_questions(path: Path) -> list[dict]:
    questions = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{line_no} JSON 解析失败：{exc}")
        if not item.get("question") or not item.get("expect"):
            raise SystemExit(f"{path}:{line_no} 缺少 question 或 expect")
        questions.append(item)
    return questions


def expected_fragments(item: dict) -> list[str]:
    expect = item["expect"]
    return [expect] if isinstance(expect, str) else list(expect)


def match_rank(results: list[dict], fragments: list[str]) -> int | None:
    """返回第一个命中期望链接片段的排名（1 起），没命中返回 None。"""
    for index, result in enumerate(results, 1):
        link = result.get("link") or ""
        if any(fragment in link for fragment in fragments):
            return index
    return None


def summarize(rows: list[dict]) -> dict:
    total = len(rows)
    if not total:
        return {"n": 0, "hits": 0, "recall": 0.0, "mrr": 0.0, "top1": 0}
    hits = [row for row in rows if row["rank"]]
    return {
        "n": total,
        "hits": len(hits),
        "recall": len(hits) / total,
        "mrr": sum(1 / row["rank"] for row in hits) / total,
        "top1": sum(1 for row in rows if row["rank"] == 1),
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="检索评测：recall@k / MRR")
    parser.add_argument("--eval", default=str(DEFAULT_EVAL), help="问题集 JSONL")
    parser.add_argument(
        "--input", action="append", default=[],
        help="归档文件或目录，可重复；默认 reports/runs",
    )
    parser.add_argument("--db", default="", help="索引库路径")
    parser.add_argument("--top-k", type=int, default=5, help="评测的 k，默认 5")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 题")
    parser.add_argument(
        "--mode", choices=MODES, default="vector", help="检索方式，默认 vector",
    )
    parser.add_argument("--rerank", action="store_true", help="对候选池做 rerank")
    parser.add_argument(
        "--candidates", type=int, default=20, help="rerank 前每路召回条数，默认 20",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    logging.basicConfig(level=logging.ERROR, format="%(message)s")

    eval_path = Path(args.eval)
    if not eval_path.is_absolute():
        eval_path = _ROOT / eval_path
    if not eval_path.exists():
        raise SystemExit(f"问题集不存在：{eval_path}")
    questions = load_questions(eval_path)
    if args.limit:
        questions = questions[: args.limit]

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
    articles = load_articles(paths) if paths else []
    if not articles:
        raise SystemExit("归档里没有文章；先运行 tools/fetch_attachments.py")

    need_vectors = args.mode in ("vector", "hybrid") or args.rerank
    try:
        build_index(articles, db_path=db_path, config=config)
        vectors = (
            embed_texts([item["question"] for item in questions], config=config)
            if need_vectors else [None] * len(questions)
        )
    except EmbeddingError as exc:
        raise SystemExit(f"评测失败：{exc}")

    rows = []
    with IndexStore(db_path) as store:
        retriever = Retriever(store, config=config)
        for item, vector in zip(questions, vectors):
            try:
                results = retriever.search(
                    item["question"], vector,
                    top_k=args.top_k, mode=args.mode,
                    candidates=args.candidates, rerank=args.rerank,
                )
            except ValueError as exc:
                raise SystemExit(f"检索失败：{exc}")
            rows.append({
                "id": item.get("id", ""),
                "question": item["question"],
                "note": item.get("note", ""),
                "rank": match_rank(results, expected_fragments(item)),
                "top1": (
                    (results[0].get("title_zh") or results[0].get("title") or "")
                    if results else ""
                ),
                "top1_link": (results[0].get("link") or "") if results else "",
            })

    stats = summarize(rows)
    stats["top_k"] = args.top_k
    stats["mode"] = args.mode
    stats["rerank"] = args.rerank

    if args.json:
        print(json.dumps({"stats": stats, "rows": rows}, ensure_ascii=False, indent=2))
        return

    label = args.mode + ("+rerank" if args.rerank else "")
    print(f"[评测] {label}  {stats['n']} 题  top{args.top_k}  "
          f"recall={stats['recall']:.2f}  MRR={stats['mrr']:.3f}  "
          f"top1={stats['top1']}/{stats['n']}")
    print()
    for row in rows:
        mark = f"✓ {row['rank']}" if row["rank"] else "✗ -"
        print(f" {mark:5} [{row['id']}] {row['question']}")
        if not row["rank"]:
            print(f"        top1: {row['top1'][:50]}  {row['top1_link'][:60]}")
    misses = [row for row in rows if not row["rank"]]
    print()
    print(f"命中 {stats['hits']}/{stats['n']}，未命中 {len(misses)} 题")


if __name__ == "__main__":
    main()
