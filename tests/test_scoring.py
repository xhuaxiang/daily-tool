"""P1 评分信号测试：噪音惩罚、正文质量和事件覆盖。"""

import email.utils
import unittest
from datetime import datetime, timezone

from modules.scoring import score_article


def _now():
    return email.utils.format_datetime(datetime.now(timezone.utc).replace(microsecond=0), usegmt=True)


def _article(**extra):
    article = {
        "title": "Fed cuts rates as inflation cools",
        "snippet": "The central bank cut rates by 25 basis points.",
        "source": "CNBC Economy",
        "publisher": "CNBC",
        "pub_date": _now(),
    }
    article.update(extra)
    return article


def _config(patterns=None, weights=None):
    return {
        "prefer_categories": ["经济", "财经", "科技", "时政", "国际", "时事"],
        "selection": {
            "noise_title_patterns": patterns or [],
            "noise_penalty": 0.25,
            "weights": weights or {},
        },
    }


class ScoringTest(unittest.TestCase):
    def test_noise_pattern_lowers_score(self):
        article = _article(title="Current price of oil as of November 11, 2026")
        clean = score_article(article, config=_config())
        noisy = score_article(
            article,
            config=_config(patterns=["current price of"]),
        )

        self.assertLess(noisy["score"], clean["score"])
        self.assertEqual(noisy["noise_hits"], ["current price of"])

    def test_page_fulltext_beats_feed(self):
        feed = _article(snippet="short feed summary", text_source="feed")
        page = _article(snippet="short feed summary", text_source="page", full_text="x" * 1000)

        feed_score = score_article(feed, config=_config())
        page_score = score_article(page, config=_config())

        self.assertGreater(page_score["score"], feed_score["score"])
        self.assertGreater(page_score["signals"]["fulltext"], feed_score["signals"]["fulltext"])

    def test_event_coverage_raises_importance(self):
        article = _article()
        single = score_article(article, event={"coverage": 1}, config=_config())
        covered = score_article(article, event={"coverage": 4}, config=_config())

        self.assertGreater(covered["signals"]["importance"], single["signals"]["importance"])
        self.assertGreater(covered["score"], single["score"])

    def test_other_category_gets_low_fit(self):
        result = score_article(
            _article(title="Local team wins championship", snippet=""),
            config=_config(),
        )

        self.assertEqual(result["category"], "其他")
        self.assertEqual(result["signals"]["category_fit"], 0.2)


if __name__ == "__main__":
    unittest.main()
