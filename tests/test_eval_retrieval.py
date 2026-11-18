"""R2 检索评测的纯函数测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from tools.eval_retrieval import (
    expected_fragments,
    load_questions,
    match_rank,
    summarize,
)

RESULTS = [
    {"link": "https://example.com/a"},
    {"link": "https://example.com/b"},
    {"link": "https://example.com/c"},
]


class MatchRankTest(unittest.TestCase):
    def test_returns_first_match_position(self):
        self.assertEqual(match_rank(RESULTS, ["/b"]), 2)

    def test_matches_any_fragment(self):
        self.assertEqual(match_rank(RESULTS, ["/missing", "/c"]), 3)

    def test_returns_none_when_absent(self):
        self.assertIsNone(match_rank(RESULTS, ["/zzz"]))
        self.assertIsNone(match_rank([], ["/a"]))

    def test_handles_link_without_scheme(self):
        self.assertIsNone(match_rank([{}], ["/a"]))


class QuestionTest(unittest.TestCase):
    def test_expect_can_be_string_or_list(self):
        self.assertEqual(expected_fragments({"expect": "x"}), ["x"])
        self.assertEqual(expected_fragments({"expect": ["x", "y"]}), ["x", "y"])

    def test_load_skips_blank_and_comment_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "q.jsonl"
            path.write_text(
                "# 注释\n\n"
                + json.dumps({"id": "a", "question": "问题", "expect": "x"},
                             ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )
            questions = load_questions(path)
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["question"], "问题")

    def test_load_rejects_missing_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "q.jsonl"
            path.write_text(json.dumps({"id": "a"}, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "question"):
                load_questions(path)


class SummarizeTest(unittest.TestCase):
    def test_recall_and_mrr(self):
        rows = [
            {"rank": 1},
            {"rank": 3},
            {"rank": None},
            {"rank": None},
        ]
        stats = summarize(rows)
        self.assertEqual(stats["n"], 4)
        self.assertEqual(stats["hits"], 2)
        self.assertAlmostEqual(stats["recall"], 0.5)
        self.assertAlmostEqual(stats["mrr"], (1 + 1 / 3) / 4)
        self.assertEqual(stats["top1"], 1)

    def test_empty(self):
        self.assertEqual(summarize([])["recall"], 0.0)


if __name__ == "__main__":
    unittest.main()
