"""P0 运行快照、归档和标注表测试。"""

import csv
import tempfile
import unittest
from pathlib import Path

from modules.snapshot import (
    article_id,
    build_archive,
    build_snapshot,
    write_labels_csv,
)


def _article(link, title, source, publisher, selected, score, event_id, **extra):
    article = {
        "title": title,
        "link": link,
        "source": source,
        "publisher": publisher,
        "pub_date": "Sat, 15 Nov 2026 06:00:00 GMT",
        "snippet": extra.pop("snippet", ""),
        "_selection": {
            "event_id": event_id,
            "score": score,
            "signals": {"importance": 0.5},
            "coverage": 2,
            "category": extra.pop("category", "经济"),
            "reasons": [],
            "selected": selected,
            "reject_reason": "" if selected else "总数已满",
        },
    }
    article.update(extra)
    return article


class ArticleIdTest(unittest.TestCase):
    def test_tracking_params_do_not_change_id(self):
        first = {"link": "https://example.com/a?utm_source=x"}
        second = {"link": "https://www.example.com/a/"}

        self.assertEqual(article_id(first), article_id(second))


class BuildSnapshotTest(unittest.TestCase):
    def test_counts_selected_and_rejected_candidates(self):
        candidates = [
            _article(
                "https://example.com/a", "Fed cuts rates", "S1", "P1",
                True, 0.9, "e1", text_source="page", full_text="x" * 500,
            ),
            _article(
                "https://example.com/b", "AI chips", "S2", "P2",
                False, 0.4, "e2", text_source="feed", snippet="y" * 100,
            ),
        ]
        snapshot = build_snapshot(
            candidates,
            run_date="2026-11-15",
            source_stats=[
                {"name": "S1", "publisher": "P1", "fetch_ok": True, "parsed": 3},
                {"name": "S2", "publisher": "P2", "fetch_ok": False, "parsed": 0},
            ],
            dedupe_stats={
                "input": 5, "kept": 3, "duplicates_removed": 2,
                "by_source": {"S2": 2},
            },
            fresh_by_source={"S1": 2, "S2": 1},
            parsed_total=5,
            unique_total=3,
            fresh_total=3,
            selection_total=1,
        )

        totals = snapshot["totals"]
        self.assertEqual(totals["candidates"], 2)
        self.assertEqual(totals["selected"], 1)
        self.assertEqual(totals["duplicates_removed"], 2)
        self.assertEqual(totals["fulltext_coverage"], 1.0)
        self.assertEqual(totals["source_share_max"], 1.0)
        self.assertEqual(snapshot["sources"][0]["fresh"], 2)
        self.assertEqual(snapshot["sources"][1]["duplicates_removed"], 2)

        selected = [row for row in snapshot["candidates"] if row["selected"]]
        rejected = [row for row in snapshot["candidates"] if not row["selected"]]
        self.assertEqual(len(selected), 1)
        self.assertEqual(rejected[0]["reject_reason"], "总数已满")


class BuildArchiveTest(unittest.TestCase):
    def test_archive_keeps_text_and_source(self):
        archive = build_archive(
            [{"title": "A", "link": "https://example.com/a", "snippet": "hello"}],
            run_date="2026-11-15",
        )

        self.assertEqual(archive["count"], 1)
        self.assertEqual(archive["articles"][0]["text"], "hello")
        self.assertEqual(archive["articles"][0]["text_source"], "feed")


class LabelsCsvTest(unittest.TestCase):
    def test_labels_use_stable_id_and_leave_label_blank(self):
        candidates = [
            _article(
                "https://example.com/a", "Fed cuts rates", "S1", "P1",
                True, 0.9, "e1", text_source="page", full_text="x" * 500,
            ),
        ]
        snapshot = build_snapshot(
            candidates,
            run_date="2026-11-15",
            source_stats=[],
            dedupe_stats={"input": 1, "kept": 1, "duplicates_removed": 0},
            fresh_by_source={"S1": 1},
            parsed_total=1,
            unique_total=1,
            fresh_total=1,
            selection_total=1,
        )

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "labels.csv"
            write_labels_csv(snapshot["candidates"], output)
            with output.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(rows[0]["id"], article_id(candidates[0]))
        self.assertEqual(rows[0]["selected"], "1")
        self.assertEqual(rows[0]["publisher"], "P1")
        self.assertEqual(rows[0]["label"], "")
        self.assertEqual(rows[0]["reason"], "")


if __name__ == "__main__":
    unittest.main()
