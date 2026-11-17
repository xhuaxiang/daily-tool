#!/usr/bin/env python3
"""R0 建索引：从 articles-*.json 生成 embedding 并写入 SQLite。

示例：
    python tools/build_index.py \
      --input reports/runs/2026-11-16/articles-2026-11-16.json \
      --db data/rag/index.db --rebuild

离线调试（不具备语义检索能力）：
    python tools/build_index.py --provider hash --limit 20
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
from modules.rag.embedding import EmbeddingError, embedding_settings
from modules.rag.index import build_index, find_archive_files, load_articles


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="R0 从全文归档建 RAG 索引（SQLite + embedding）",
    )
    parser.add_argument(
        "--input", action="append", default=[],
        help="articles-*.json 文件或目录，可重复；默认 reports/runs",
    )
    parser.add_argument(
        "--db", default="",
        help="SQLite 路径；默认取 config.rag.db_path 或 data/rag/index.db",
    )
    parser.add_argument(
        "--provider", default="",
        help="embedding provider：openai-compatible（默认）或 hash（离线调试）",
    )
    parser.add_argument("--model", default="", help="覆盖 embedding 模型")
    parser.add_argument("--base-url", default="", help="覆盖 embedding API base_url")
    parser.add_argument(
        "--chunk-size", type=int, default=None, help="每块最大字符数",
    )
    parser.add_argument(
        "--overlap", type=int, default=None, help="块间重叠字符数",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="最多处理多少篇文章（0=全部）",
    )
    parser.add_argument(
        "--rebuild", action="store_true", help="清空现有索引后重建",
    )
    parser.add_argument(
        "--list", action="store_true", help="只列出将读取的归档文件",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    config = load_config()
    rag = config.get("rag")
    if not isinstance(rag, dict):
        rag = {}
        config["rag"] = rag
    embedding = rag.get("embedding")
    if not isinstance(embedding, dict):
        embedding = {}
        rag["embedding"] = embedding
    if args.provider:
        embedding["provider"] = args.provider
    if args.model:
        embedding["model"] = args.model
    if args.base_url:
        embedding["base_url"] = args.base_url
    if args.chunk_size is not None:
        rag["chunk_size"] = args.chunk_size
    if args.overlap is not None:
        rag["chunk_overlap"] = args.overlap

    inputs = args.input or [str(_ROOT / "reports" / "runs")]
    try:
        paths = find_archive_files(inputs)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))

    if not paths:
        raise SystemExit(
            "没有找到 articles-*.json；先用邮件附件放到 reports/runs/<日期>/，"
            "或用 --input 指定文件"
        )

    if args.list:
        print(f"找到 {len(paths)} 个归档：")
        for path in paths:
            print(f"  {path}")
        return

    articles = load_articles(paths)
    if not articles:
        raise SystemExit("归档里没有文章")

    db_path = Path(args.db) if args.db else Path(
        rag.get("db_path", "data/rag/index.db")
    )
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path

    settings = embedding_settings(config)
    if settings["provider"] == "hash":
        print(
            "警告：provider=hash 只用于离线跑通流程，"
            "向量没有语义，检索结果不可用于评估。"
        )

    try:
        stats = build_index(
            articles,
            db_path=db_path,
            config=config,
            chunk_size=args.chunk_size,
            overlap=args.overlap,
            rebuild=args.rebuild,
            limit=args.limit,
        )
    except EmbeddingError as exc:
        raise SystemExit(f"建索引失败：{exc}")

    print()
    print("=" * 56)
    print("[R0 建索引]")
    print(f"归档文件: {len(paths)}")
    print(f"文章: {stats['articles']}  块: {stats['chunks']}  维度: {stats['dim']}")
    print(f"模型: {stats['model']}")
    print(f"数据库: {db_path.resolve()}")
    if stats.get("chunks"):
        print(f"本次写入: {stats.get('stored', 0)}  库内总数: {stats.get('total_in_db', 0)}")
    else:
        print("没有可索引的正文，未写入向量")
    print("=" * 56)


if __name__ == "__main__":
    main()
