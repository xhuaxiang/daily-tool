"""R0 SQLite 索引测试。"""

import unittest

from modules.rag.store import IndexStore


def _row(chunk_id, vector, *, article_id="a1", model="m1", text="text"):
    return {
        "chunk_id": chunk_id,
        "article_id": article_id,
        "chunk_index": 0,
        "chunk_count": 1,
        "title": "title",
        "title_zh": "标题",
        "link": "https://example.com/a",
        "source": "S",
        "publisher": "P",
        "published": "2026-11-16 08:00:00",
        "category": "经济",
        "event_id": "e1",
        "text": text,
        "model": model,
        "vector": vector,
    }


class IndexStoreTest(unittest.TestCase):
    def test_upsert_and_search(self):
        with IndexStore(":memory:") as store:
            store.upsert_chunks([
                _row("a#0", [1.0, 0.0], text="A"),
                _row("b#0", [0.0, 1.0], text="B"),
                _row("c#0", [0.8, 0.2], text="C"),
            ])

            results = store.search([1.0, 0.0], top_k=2)
            self.assertEqual(store.count(), 3)

        self.assertEqual([result["text"] for result in results], ["A", "C"])
        self.assertGreater(results[0]["score"], results[1]["score"])

    def test_count_and_clear(self):
        with IndexStore(":memory:") as store:
            store.upsert_chunks([_row("a#0", [1.0, 0.0])])
            self.assertEqual(store.count(), 1)
            self.assertEqual(store.count("m1"), 1)
            self.assertEqual(store.count("other"), 0)

            store.clear()
            self.assertEqual(store.count(), 0)
            self.assertEqual(store.latest_model(), "")
            self.assertEqual(store.search([1.0, 0.0]), [])

    def test_search_uses_latest_model(self):
        with IndexStore(":memory:") as store:
            store.upsert_chunks([
                _row("old#0", [1.0, 0.0], model="old", text="old"),
            ])
            store.upsert_chunks([
                _row("new#0", [0.0, 1.0], model="new", text="new"),
            ])

            results = store.search([0.0, 1.0])

        self.assertEqual(results[0]["text"], "new")
        self.assertEqual(results[0]["article_id"], "a1")

    def test_dimension_mismatch_raises(self):
        with IndexStore(":memory:") as store:
            store.upsert_chunks([_row("a#0", [1.0, 0.0])])
            with self.assertRaises(ValueError):
                store.search([1.0, 0.0, 0.0])

    def test_zero_query_raises(self):
        with IndexStore(":memory:") as store:
            store.upsert_chunks([_row("a#0", [1.0, 0.0])])
            with self.assertRaises(ValueError):
                store.search([0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
