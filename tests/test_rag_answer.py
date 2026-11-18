"""R1 问答测试：prompt 组装、JSON 解析、引用校验。"""

import json
import unittest

from modules.rag.answer import (
    answer_question,
    build_prompt,
    format_context,
    parse_answer,
    validate_citations,
)

CHUNKS = [
    {
        "chunk_id": "a1#0",
        "title": "Fed holds rates steady",
        "title_zh": "美联储维持利率不变",
        "link": "https://example.com/fed",
        "source": "CNBC Top News",
        "publisher": "CNBC",
        "published": "2026-11-16T10:00:00",
        "text": "美联储周三宣布维持基准利率不变，并暗示年内不会降息。",
        "score": 0.82,
    },
    {
        "chunk_id": "a2#1",
        "title": "Nvidia earnings",
        "link": "https://example.com/nvda",
        "publisher": "Fortune",
        "published": "2026-11-15T08:00:00",
        "text": "英伟达三季度营收同比增长百分之九十四。",
        "score": 0.61,
    },
]


class ContextTest(unittest.TestCase):
    def test_context_has_ids_and_metadata(self):
        context = format_context(CHUNKS)
        self.assertIn("chunk_id=a1#0", context)
        self.assertIn("美联储维持利率不变", context)
        self.assertIn("2026-11-16", context)
        self.assertIn("chunk_id=a2#1", context)

    def test_long_chunk_is_truncated(self):
        chunk = dict(CHUNKS[1], text="长" * 50)
        self.assertEqual(format_context([chunk], max_chars=10).count("长"), 10)

    def test_prompt_contains_question_and_rules(self):
        prompt = build_prompt("美联储做了什么？", CHUNKS)
        self.assertIn("美联储做了什么？", prompt)
        self.assertIn("quote 必须是资料里连续的一段原文", prompt)


class ParseTest(unittest.TestCase):
    def test_parses_plain_json(self):
        text = json.dumps({"answer": "维持利率不变", "citations": []}, ensure_ascii=False)
        self.assertEqual(parse_answer(text)["answer"], "维持利率不变")

    def test_parses_fenced_json(self):
        text = '```json\n{"answer": "a", "citations": []}\n```'
        self.assertEqual(parse_answer(text)["answer"], "a")

    def test_parses_json_with_surrounding_text(self):
        text = '结果如下：{"answer": "a", "citations": []} 以上。'
        self.assertEqual(parse_answer(text)["answer"], "a")

    def test_invalid_returns_none(self):
        self.assertIsNone(parse_answer("没有 JSON"))
        self.assertIsNone(parse_answer(""))


class CitationTest(unittest.TestCase):
    def test_keeps_valid_and_rejects_fabricated(self):
        valid, invalid = validate_citations(
            [
                {"chunk_id": "a1#0", "quote": "维持基准利率不变"},
                {"chunk_id": "a1#0", "quote": "这句话原文里没有"},
                {"chunk_id": "missing#9", "quote": "任意内容"},
                {"chunk_id": "a2#1", "quote": ""},
            ],
            CHUNKS,
        )
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0]["title"], "美联储维持利率不变")
        # index 与回答里的 [n] 对齐
        self.assertEqual(valid[0]["index"], 1)
        self.assertEqual(len(invalid), 3)

    def test_quote_whitespace_is_normalized(self):
        valid, invalid = validate_citations(
            [{"chunk_id": "a1#0", "quote": "美联储周三宣布\n维持基准利率不变"}],
            CHUNKS,
        )
        self.assertEqual(len(valid), 1)
        self.assertEqual(invalid, [])

    def test_non_list_citations(self):
        valid, invalid = validate_citations("bad", CHUNKS)
        self.assertEqual((valid, invalid), ([], []))


class AnswerQuestionTest(unittest.TestCase):
    def test_no_context(self):
        result = answer_question("q", [], [], complete_fn=lambda *a: "x")
        self.assertEqual(result["status"], "no_context")

    def test_llm_failure(self):
        result = answer_question("q", CHUNKS, [], complete_fn=lambda *a: None)
        self.assertEqual(result["status"], "llm_failed")

    def test_valid_answer(self):
        reply = json.dumps(
            {
                "answer": "维持利率不变 [1]",
                "citations": [{"chunk_id": "a1#0", "quote": "维持基准利率不变"}],
            },
            ensure_ascii=False,
        )
        result = answer_question("q", CHUNKS, [{"provider": "deepseek"}],
                                 complete_fn=lambda *a: reply)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["citations"]), 1)

    def test_fabricated_citation_falls_back(self):
        reply = json.dumps(
            {
                "answer": "编的",
                "citations": [{"chunk_id": "a1#0", "quote": "原文没有这句"}],
            },
            ensure_ascii=False,
        )
        result = answer_question("q", CHUNKS, [], complete_fn=lambda *a: reply)
        self.assertEqual(result["status"], "no_citation")
        self.assertEqual(len(result["invalid"]), 1)

    def test_unparsed_reply(self):
        result = answer_question("q", CHUNKS, [], complete_fn=lambda *a: "纯文本回答")
        self.assertEqual(result["status"], "unparsed")


if __name__ == "__main__":
    unittest.main()
