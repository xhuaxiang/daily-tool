"""P0 诊断工具测试：去重统计、正文抽样、标注 CSV。"""

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.dedup import dedupe
from tools.diagnose import _latest_datetime, _probe_fulltext
from tools.label_sample import _write_labels


class DedupStatsTest(unittest.TestCase):
    def test_stats_records_duplicate_source(self):
        articles = [
            {
                "title": "Fed cuts rates by 25 basis points",
                "link": "https://example.com/a",
                "snippet": "short",
                "source": "A",
            },
            {
                "title": "Fed cuts rates by 25 basis points",
                "link": "https://example.org/b",
                "snippet": "a much longer duplicate snippet",
                "source": "B",
            },
        ]
        stats: dict = {}
        kept = dedupe(articles, stats=stats)

        self.assertEqual(len(kept), 1)
        self.assertEqual(stats["input"], 2)
        self.assertEqual(stats["kept"], 1)
        self.assertEqual(stats["duplicates_removed"], 1)
        self.assertEqual(stats["by_source"], {"B": 1})


class DiagnoseHelpersTest(unittest.TestCase):
    def test_latest_datetime_picks_newest_and_ignores_invalid(self):
        articles = [
            {"pub_date": "Mon, 27 Jan 2025 14:26:00 -0500"},
            {"pub_date": "Wed, 11 Nov 2026 15:08:00 GMT"},
            {"pub_date": "not a date"},
        ]
        latest = _latest_datetime(articles)
        self.assertIsNotNone(latest)
        self.assertEqual((latest.year, latest.month, latest.day), (2026, 11, 11))

    def test_latest_datetime_returns_none_without_dates(self):
        self.assertIsNone(_latest_datetime([{"pub_date": ""}]))


class FulltextProbeTest(unittest.TestCase):
    def test_probe_counts_page_success_and_average(self):
        articles = [
            {"link": "https://example.com/a", "snippet": "feed a"},
            {"link": "https://example.com/b", "snippet": "feed b"},
        ]

        def fake_fetch(url, timeout):
            return "x" * 500 if url.endswith("/a") else ""

        with patch("tools.diagnose.fetch_full_text", side_effect=fake_fetch):
            probe = _probe_fulltext(articles, timeout=1, max_workers=1)

        self.assertEqual(probe["sample"], 2)
        self.assertEqual(probe["page_ok"], 1)
        self.assertEqual(probe["avg_page_chars"], 500)

    def test_probe_handles_empty_sample(self):
        probe = _probe_fulltext([], timeout=1)
        self.assertEqual(probe["sample"], 0)
        self.assertEqual(probe["page_ok"], 0)


class LabelSampleTest(unittest.TestCase):
    def test_write_labels_has_expected_columns_and_rows(self):
        sample = [{
            "source": "Test Source",
            "pub_date": "Sat, 08 Nov 2026 00:00:00 GMT",
            "title": "Fed cuts rates",
            "link": "https://example.com/a",
            "snippet": "Some summary",
        }]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "labels.csv"
            _write_labels(sample, output)

            with output.open("r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "1")
        self.assertEqual(rows[0]["source"], "Test Source")
        self.assertEqual(rows[0]["title"], "Fed cuts rates")
        self.assertEqual(rows[0]["label"], "")
        self.assertEqual(rows[0]["reason"], "")
        self.assertIn("category", rows[0])


if __name__ == "__main__":
    unittest.main()
