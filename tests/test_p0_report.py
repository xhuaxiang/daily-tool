"""P0 离线评估指标测试。"""

import unittest

from tools.report import compute_metrics, merge_rows


def _row(selected, label, source, publisher, text_source, event_id):
    return {
        "selected": selected,
        "label": label,
        "source": source,
        "publisher": publisher,
        "text_source": text_source,
        "event_id": event_id,
    }


SAMPLE = [
    _row("1", "4", "A", "P", "page", "e1"),
    _row("1", "3", "A", "P", "feed", "e1"),
    _row("1", "1", "B", "Q", "none", "e3"),
    _row("0", "3", "C", "R", "page", "e4"),
    _row("0", "2", "C", "R", "feed", "e5"),
]


class ComputeMetricsTest(unittest.TestCase):
    def test_precision_recall_and_noise(self):
        metrics = compute_metrics(SAMPLE, total=15)

        self.assertEqual(metrics["rows"], 5)
        self.assertEqual(metrics["labeled"], 5)
        self.assertEqual(metrics["selected"], 3)
        self.assertEqual(metrics["good_selected"], 2)
        self.assertEqual(metrics["good_all"], 3)
        self.assertEqual(metrics["precision_at_15"], 0.133)
        self.assertEqual(metrics["precision"], 0.667)
        self.assertEqual(metrics["recall"], 0.667)
        self.assertEqual(metrics["noise_rate"], 0.333)

    def test_concentration_and_duplicate_rate(self):
        metrics = compute_metrics(SAMPLE, total=15)

        self.assertEqual(metrics["fulltext_coverage"], 0.333)
        self.assertEqual(metrics["source_share_max"], 0.667)
        self.assertEqual(metrics["publisher_share_max"], 0.667)
        self.assertEqual(metrics["event_duplicate_rate"], 0.667)
        self.assertEqual(
            metrics["label_distribution"], {1: 1, 2: 1, 3: 2, 4: 1}
        )
        self.assertEqual(
            metrics["by_source"]["A"], {"selected": 2, "good": 2}
        )
        self.assertEqual(
            metrics["by_source"]["B"], {"selected": 1, "good": 0}
        )

    def test_unlabeled_rows_do_not_affect_quality_metrics(self):
        rows = SAMPLE + [
            _row("1", "", "D", "S", "page", "e6"),
        ]
        metrics = compute_metrics(rows, total=15)

        self.assertEqual(metrics["rows"], 6)
        self.assertEqual(metrics["labeled"], 5)
        self.assertEqual(metrics["selected"], 4)
        self.assertEqual(metrics["selected_labeled"], 3)
        self.assertEqual(metrics["precision"], 0.667)
        self.assertEqual(metrics["fulltext_coverage"], 0.5)

    def test_empty_rows_return_zero_metrics(self):
        metrics = compute_metrics([], total=15)

        self.assertEqual(metrics["rows"], 0)
        self.assertEqual(metrics["precision_at_15"], 0.0)
        self.assertEqual(metrics["recall"], 0.0)
        self.assertEqual(metrics["noise_rate"], 0.0)
        self.assertEqual(metrics["fulltext_coverage"], 0.0)
        self.assertEqual(metrics["source_share_max"], 0.0)
        self.assertEqual(metrics["event_duplicate_rate"], 0.0)


class MergeRowsTest(unittest.TestCase):
    def test_snapshot_fills_missing_fields_and_keeps_labels(self):
        snapshot = {
            "candidates": [
                {
                    "id": "abc123",
                    "source": "S1",
                    "publisher": "P1",
                    "score": 0.8,
                    "selected": True,
                    "text_source": "page",
                    "event_id": "e1",
                },
            ],
        }
        rows = [{"id": "abc123", "label": "4", "reason": "重要"}]
        merged = merge_rows(rows, snapshot)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["source"], "S1")
        self.assertEqual(merged[0]["score"], 0.8)
        self.assertEqual(merged[0]["label"], "4")
        self.assertEqual(merged[0]["reason"], "重要")

    def test_without_snapshot_rows_are_unchanged(self):
        rows = [{"id": "abc123", "label": "3"}]
        self.assertEqual(merge_rows(rows, None), rows)


if __name__ == "__main__":
    unittest.main()
