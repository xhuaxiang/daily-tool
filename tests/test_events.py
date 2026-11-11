"""事件聚类 v0 测试：同事件合并、数字/日期守卫、发布方覆盖。"""

import unittest

from modules.events import cluster_events


def _article(title, source="CNBC", publisher="CNBC", pub_date="Wed, 11 Nov 2026 10:00:00 GMT"):
    return {
        "title": title,
        "source": source,
        "publisher": publisher,
        "pub_date": pub_date,
    }


class ClusterEventsTest(unittest.TestCase):
    def test_same_event_merges_across_sources(self):
        articles = [
            _article("Fed cuts rates by 25 basis points", source="CNBC", publisher="CNBC"),
            _article(
                "Fed cuts rates 25 basis points, signals more easing",
                source="NPR Business", publisher="NPR",
                pub_date="Wed, 11 Nov 2026 11:00:00 GMT",
            ),
        ]

        events = cluster_events(articles, window_hours=36, threshold=0.58)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["coverage"], 2)
        self.assertEqual(set(events[0]["sources"]), {"CNBC", "NPR"})
        self.assertEqual(articles[0]["_event_id"], articles[1]["_event_id"])

    def test_different_numbers_do_not_merge(self):
        articles = [
            _article("Fed cuts rates by 25 basis points"),
            _article("Fed cuts rates by 50 basis points", pub_date="Wed, 11 Nov 2026 11:00:00 GMT"),
        ]

        events = cluster_events(articles, window_hours=36, threshold=0.58)

        self.assertEqual(len(events), 2)

    def test_different_dates_do_not_merge(self):
        articles = [
            _article("Fed decision expected on Monday"),
            _article("Fed decision expected on Friday", pub_date="Wed, 11 Nov 2026 11:00:00 GMT"),
        ]

        events = cluster_events(articles, window_hours=36, threshold=0.58)

        self.assertEqual(len(events), 2)

    def test_outside_window_does_not_merge(self):
        articles = [
            _article("Fed cuts rates by 25 basis points", pub_date="Mon, 09 Nov 2026 10:00:00 GMT"),
            _article("Fed cuts rates by 25 basis points", pub_date="Wed, 11 Nov 2026 10:00:00 GMT"),
        ]

        events = cluster_events(articles, window_hours=24, threshold=0.58)

        self.assertEqual(len(events), 2)

    def test_same_number_and_shared_terms_merge(self):
        articles = [
            _article(
                "Anthropic sets a $1.4 trillion IPO target, but bankers may aim higher",
                source="Fortune", publisher="Fortune",
            ),
            _article(
                "Anthropic eyes $1.4 trillion valuation in blockbuster IPO",
                source="France 24 Economy", publisher="France 24",
                pub_date="Wed, 11 Nov 2026 11:00:00 GMT",
            ),
        ]

        events = cluster_events(articles, window_hours=36, threshold=0.58)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["coverage"], 2)

    def test_same_publisher_counts_once_in_coverage(self):
        articles = [
            _article("Fed cuts rates by 25 basis points", source="CNBC Top News", publisher="CNBC"),
            _article(
                "Fed cuts rates by 25 basis points",
                source="CNBC Economy", publisher="CNBC",
                pub_date="Wed, 11 Nov 2026 11:00:00 GMT",
            ),
        ]

        events = cluster_events(articles, window_hours=36, threshold=0.58)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["coverage"], 1)


if __name__ == "__main__":
    unittest.main()
