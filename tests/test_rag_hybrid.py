"""R2 关键词 / RRF / 检索入口测试。"""

import unittest

from modules.rag.hybrid import rrf_fuse
from modules.rag.keyword import BM25Index, tokenize
from modules.rag.retrieval import Retriever

CHUNKS = [
    {
        "chunk_id": "a#0",
        "title": "Big Short investor Steve Eisman warns on AI stocks",
        "title_zh": "《大空头》投资者史蒂夫·艾斯曼警告AI股票",
        "link": "https://example.com/eisman",
        "text": "Steve Eisman said AI infrastructure stocks would suffer most.",
    },
    {
        "chunk_id": "b#0",
        "title": "Fed holds rates steady",
        "title_zh": "美联储维持利率不变",
        "link": "https://example.com/fed",
        "text": "美联储周三宣布维持基准利率不变，并暗示年内不会降息。",
    },
    {
        "chunk_id": "c#0",
        "title": "Bitcoin slides",
        "title_zh": "比特币跌至62000美元",
        "link": "https://example.com/btc",
        "text": "Bitcoin fell to 62000 dollars over the weekend.",
    },
]


class TokenizeTest(unittest.TestCase):
    def test_chinese_bigrams(self):
        tokens = tokenize("美联储")
        self.assertEqual(tokens, ["美联", "联储"])

    def test_single_chinese_char_kept(self):
        self.assertEqual(tokenize("美"), ["美"])

    def test_english_lowercased_words(self):
        self.assertEqual(tokenize("Fed Holds RATES"), ["fed", "holds", "rates"])

    def test_empty(self):
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize(None), [])


class BM25Test(unittest.TestCase):
    def search(self, query, top_k=5):
        return BM25Index(CHUNKS).search(query, top_k=top_k)

    def test_matches_chinese_title(self):
        results = self.search("艾斯曼认为哪些股票会受损")
        self.assertEqual(results[0]["chunk_id"], "a#0")

    def test_matches_english_body(self):
        results = self.search("bitcoin weekend")
        self.assertEqual(results[0]["chunk_id"], "c#0")

    def test_no_token_overlap_returns_empty(self):
        self.assertEqual(self.search("量子计算芯片"), [])

    def test_top_k_limits_results(self):
        results = self.search("美元", top_k=1)
        self.assertLessEqual(len(results), 1)

    def test_scores_descending(self):
        scores = [chunk["score"] for chunk in self.search("美联储利率")]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_empty_index(self):
        self.assertEqual(BM25Index([]).search("美联储"), [])


class RrfTest(unittest.TestCase):
    def test_union_and_order(self):
        first = [{"chunk_id": "a"}, {"chunk_id": "b"}]
        second = [{"chunk_id": "b"}, {"chunk_id": "c"}]
        fused = rrf_fuse([first, second])
        self.assertEqual([chunk["chunk_id"] for chunk in fused], ["b", "a", "c"])

    def test_top_n(self):
        fused = rrf_fuse([[{"chunk_id": "a"}], [{"chunk_id": "b"}]], top_n=1)
        self.assertEqual(len(fused), 1)

    def test_skips_items_without_id(self):
        self.assertEqual(rrf_fuse([[{"title": "x"}]]), [])

    def test_rejects_bad_k(self):
        with self.assertRaises(ValueError):
            rrf_fuse([[]], k=0)


class FakeStore:
    def __init__(self):
        self.search_calls = []

    def latest_model(self):
        return "fake-model"

    def all_chunks(self, model=None):
        return CHUNKS

    def search(self, query_vector, *, top_k=5, model=None):
        self.search_calls.append(top_k)
        return [{"chunk_id": "b#0", "score": 0.9}][:top_k]


class RetrieverTest(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.config = {"rag": {"rerank": {"enabled": False}}}

    def test_vector_mode_uses_store(self):
        results = Retriever(self.store, config=self.config).search(
            "随便问", [0.1, 0.2], top_k=1, mode="vector",
        )
        self.assertEqual(results[0]["chunk_id"], "b#0")

    def test_keyword_mode_skips_store_search(self):
        retriever = Retriever(self.store, config=self.config)
        results = retriever.search("艾斯曼", None, top_k=1, mode="keyword")
        self.assertEqual(results[0]["chunk_id"], "a#0")
        self.assertEqual(self.store.search_calls, [])

    def test_hybrid_mode_fuses_both(self):
        results = Retriever(self.store, config=self.config).search(
            "美联储 艾斯曼", [0.1, 0.2], top_k=2, mode="hybrid",
        )
        ids = [chunk["chunk_id"] for chunk in results]
        self.assertIn("b#0", ids)
        self.assertIn("a#0", ids)

    def test_hybrid_falls_back_when_keyword_empty(self):
        results = Retriever(self.store, config=self.config).search(
            "zzz", [0.1, 0.2], top_k=1, mode="hybrid",
        )
        self.assertEqual(results[0]["chunk_id"], "b#0")

    def test_rerank_pool_uses_candidates(self):
        Retriever(self.store, config=self.config).search(
            "美联储", [0.1], top_k=1, mode="vector", candidates=3, rerank=True,
        )
        self.assertEqual(self.store.search_calls, [3])

    def test_unknown_mode(self):
        with self.assertRaises(ValueError):
            Retriever(self.store, config=self.config).search("q", [0.1], mode="bm25")

    def test_zero_top_k(self):
        self.assertEqual(Retriever(self.store, config=self.config).search(
            "q", [0.1], top_k=0,
        ), [])


if __name__ == "__main__":
    unittest.main()
