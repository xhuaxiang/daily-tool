"""分类关键词边界测试：避免 ASCII 短词误命中英文单词内部。"""

import unittest

from modules.categorizer import classify


class KeywordBoundaryTest(unittest.TestCase):
    def test_ai_does_not_match_said_or_chair(self):
        category, _ = classify({
            "title": "The chair said the market is calm",
            "snippet": "",
        })

        self.assertNotEqual(category, "科技")

    def test_ai_keyword_still_matches_standalone(self):
        category, _ = classify({
            "title": "AI chip demand surges",
            "snippet": "",
        })

        self.assertEqual(category, "科技")

    def test_fed_matches_standalone(self):
        category, _ = classify({
            "title": "Fed cuts rates as inflation cools",
            "snippet": "",
        })

        self.assertEqual(category, "经济")


if __name__ == "__main__":
    unittest.main()
