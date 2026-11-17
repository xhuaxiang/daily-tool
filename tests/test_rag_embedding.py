"""R0 embedding 封装与缓存测试。"""

import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.rag.embedding import (
    EmbeddingCache,
    EmbeddingError,
    embed_texts,
    embedding_settings,
    model_key,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self.payload


CONFIG = {
    "rag": {
        "embedding": {
            "provider": "openai-compatible",
            "base_url": "https://example.test/v1",
            "model": "test-embed",
            "batch_size": 2,
        },
    },
}


class EmbedTextsTest(unittest.TestCase):
    def test_batches_and_sorts_by_index(self):
        calls = []

        def fake_post(url, headers, json, timeout):
            offset = sum(len(call) for call in calls)
            calls.append(json["input"])
            data = [
                {
                    "index": offset + index,
                    "embedding": [float(offset + index), 1.0],
                }
                for index in range(len(json["input"]))
            ]
            return FakeResponse({"data": list(reversed(data))})

        with patch.dict(os.environ, {"EMBEDDING_API_KEY": "key"}, clear=True), \
                patch("modules.rag.embedding.requests.post", side_effect=fake_post):
            vectors = embed_texts(["a", "b", "c"], config=CONFIG)

        self.assertEqual([vector[0] for vector in vectors], [0.0, 1.0, 2.0])
        self.assertEqual(calls, [["a", "b"], ["c"]])

    def test_cache_avoids_second_api_call(self):
        calls = []

        def fake_post(url, headers, json, timeout):
            calls.append(json["input"])
            return FakeResponse({
                "data": [
                    {"index": index, "embedding": [1.0, float(index)]}
                    for index in range(len(json["input"]))
                ],
            })

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "cache.db"
            with patch.dict(os.environ, {"EMBEDDING_API_KEY": "key"}, clear=True), \
                    patch("modules.rag.embedding.requests.post", side_effect=fake_post):
                with EmbeddingCache(cache_path) as cache:
                    first = embed_texts(["a", "b"], config=CONFIG, cache=cache)
                    second = embed_texts(["a", "b"], config=CONFIG, cache=cache)
                    count = cache.count(model_key(embedding_settings(CONFIG)))

            self.assertEqual(first, second)
            self.assertEqual(len(calls), 1)
            self.assertEqual(count, 2)

    def test_missing_api_key_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(EmbeddingError, "EMBEDDING_API_KEY"):
                embed_texts(["a"], config=CONFIG)

    def test_unsupported_provider_raises(self):
        config = {
            "rag": {"embedding": {"provider": "unknown"}},
        }
        with self.assertRaisesRegex(EmbeddingError, "不支持的 embedding provider"):
            embed_texts(["a"], config=config)

    def test_empty_input_returns_empty(self):
        self.assertEqual(embed_texts([], config=CONFIG), [])


class HashEmbeddingTest(unittest.TestCase):
    def test_hash_embedding_is_deterministic_and_normalized(self):
        config = {"rag": {"embedding": {"provider": "hash"}}}

        first = embed_texts(["相同文本"], config=config)
        second = embed_texts(["相同文本"], config=config)
        different = embed_texts(["不同文本"], config=config)

        self.assertEqual(first, second)
        self.assertNotEqual(first, different)
        self.assertEqual(len(first[0]), 256)
        self.assertAlmostEqual(
            math.sqrt(sum(value * value for value in first[0])), 1.0, places=5
        )
        self.assertEqual(model_key(embedding_settings(config)), "hash:256")


if __name__ == "__main__":
    unittest.main()
