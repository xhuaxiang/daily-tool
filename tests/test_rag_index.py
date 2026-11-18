"""R0 建索引流程测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from modules.rag.embedding import embed_texts
from modules.rag.index import build_index, find_archive_files, load_articles
from modules.rag.store import IndexStore

CONFIG = {
    "rag": {
        "embedding": {"provider": "hash"},
        "chunk_size": 120,
        "chunk_overlap": 20,
    },
}


def _write_archive(directory: Path, date: str, articles: list[dict]) -> Path:
    path = directory / f"articles-{date}.json"
    path.write_text(
        json.dumps({"articles": articles}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _article(article_id: str, title: str) -> dict:
    return {
        "id": article_id,
        "title": title,
        "title_zh": title,
        "link": f"https://example.com/{article_id}",
        "source": "S",
        "publisher": "P",
        "published": "2026-11-16 08:00:00",
        "category": "经济",
        "event_id": "e1",
        "text": f"{title}。" * 60,
    }


class BuildIndexTest(unittest.TestCase):
    def test_build_index_from_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_archive(root, "2026-11-16", [
                _article("a1", "美联储降息"),
                _article("a2", "科技股上涨"),
            ])
            paths = find_archive_files([root])
            articles = load_articles(paths)
            db_path = root / "index.db"

            stats = build_index(articles, db_path=db_path, config=CONFIG)

            self.assertEqual(stats["articles"], 2)
            self.assertGreater(stats["chunks"], 0)
            self.assertEqual(stats["dim"], 256)
            self.assertEqual(stats["stored"], stats["chunks"])
            self.assertEqual(stats["total_in_db"], stats["chunks"])

            with IndexStore(db_path) as store:
                self.assertEqual(store.count(), stats["chunks"])
                self.assertEqual(store.models(), [stats["model"]])
                first_text = store.conn.execute(
                    "SELECT text FROM chunks LIMIT 1"
                ).fetchone()["text"]
                query = embed_texts([first_text], config=CONFIG)[0]
                results = store.search(query, top_k=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["text"], first_text)

    def test_limit_and_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_archive(root, "2026-11-16", [
                _article("a1", "第一篇"),
                _article("a2", "第二篇"),
            ])
            articles = load_articles(find_archive_files([root]))
            db_path = root / "index.db"

            build_index(articles, db_path=db_path, config=CONFIG)
            stats = build_index(
                articles, db_path=db_path, config=CONFIG,
                limit=1, rebuild=True,
            )

            self.assertEqual(stats["articles"], 1)
            self.assertEqual(stats["total_in_db"], stats["chunks"])

    def test_empty_articles(self):
        with tempfile.TemporaryDirectory() as tmp:
            stats = build_index([], db_path=Path(tmp) / "index.db", config=CONFIG)

        self.assertEqual(stats["chunks"], 0)
        self.assertEqual(stats["dim"], 0)


class ArchiveLoadingTest(unittest.TestCase):
    def test_load_articles_dedupes_by_id_and_keeps_last(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_archive(root, "2026-11-15", [
                _article("a1", "旧标题"),
            ])
            _write_archive(root, "2026-11-16", [
                _article("a1", "新标题"),
                _article("a2", "第二篇"),
            ])

            paths = find_archive_files([root])
            articles = load_articles(paths)

        self.assertEqual(len(articles), 2)
        by_id = {article["id"]: article for article in articles}
        self.assertEqual(by_id["a1"]["title"], "新标题")

    def test_empty_field_does_not_clobber_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_archive(root, "2026-11-15", [_article("a1", "旧标题")])
            later = _article("a1", "旧标题")
            later["title_zh"] = ""
            _write_archive(root, "2026-11-16", [later])

            articles = load_articles(find_archive_files([root]))

        self.assertEqual(articles[0]["title_zh"], "旧标题")

    def test_missing_input_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                find_archive_files([Path(tmp) / "missing"])


if __name__ == "__main__":
    unittest.main()
