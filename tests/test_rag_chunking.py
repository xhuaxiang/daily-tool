"""R0 切块测试。"""

import unittest

from modules.rag.chunking import article_chunks, chunk_text, chunks_for_articles


class ChunkTextTest(unittest.TestCase):
    def test_short_text_returns_one_chunk(self):
        self.assertEqual(chunk_text("短文本。", max_chars=100), ["短文本。"])

    def test_empty_text_returns_empty(self):
        self.assertEqual(chunk_text("   \n\n "), [])
        self.assertEqual(chunk_text(""), [])

    def test_long_text_respects_max_chars(self):
        text = "这是第一句。" * 200
        chunks = chunk_text(text, max_chars=200, overlap=20)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 200 for chunk in chunks))
        self.assertTrue(all(chunk.strip() for chunk in chunks))

    def test_paragraph_boundary_is_kept(self):
        text = ("第一段内容。" * 80) + "\n\n" + ("第二段内容。" * 80)
        chunks = chunk_text(text, max_chars=300, overlap=30)

        self.assertTrue(any("第二段内容" in chunk for chunk in chunks))
        self.assertTrue(all(len(chunk) <= 300 for chunk in chunks))

    def test_text_without_punctuation_is_hard_split(self):
        chunks = chunk_text("无标点" * 500, max_chars=120, overlap=10)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 120 for chunk in chunks))


class ArticleChunksTest(unittest.TestCase):
    def test_metadata_and_stable_ids(self):
        article = {
            "id": "abc123",
            "title": "Fed cuts rates",
            "title_zh": "美联储降息",
            "link": "https://example.com/a",
            "source": "S",
            "publisher": "P",
            "published": "2026-11-16 08:00:00",
            "category": "经济",
            "event_id": "e1",
            "text": "正文内容。" * 100,
        }
        chunks = article_chunks(article, max_chars=150, overlap=20)

        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0]["chunk_id"], "abc123#0")
        self.assertEqual(chunks[0]["article_id"], "abc123")
        self.assertEqual(chunks[0]["chunk_count"], len(chunks))
        self.assertEqual(chunks[0]["title_zh"], "美联储降息")
        self.assertEqual(chunks[0]["publisher"], "P")

    def test_empty_article_is_skipped(self):
        self.assertEqual(article_chunks({"id": "x", "text": ""}), [])
        self.assertEqual(chunks_for_articles([{"id": "x"}]), [])

    def test_chunks_for_articles_combines(self):
        articles = [
            {"id": "a", "text": "第一篇正文。" * 20},
            {"id": "b", "text": "第二篇正文。" * 20},
        ]
        chunks = chunks_for_articles(articles, max_chars=100, overlap=10)

        self.assertEqual({chunk["article_id"] for chunk in chunks}, {"a", "b"})


if __name__ == "__main__":
    unittest.main()
