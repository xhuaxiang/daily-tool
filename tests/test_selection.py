"""P1 选稿测试：配额、类别保底和候选池。"""

import email.utils
import unittest
from collections import Counter
from datetime import datetime, timezone

from modules.selection import final_select, preselect


def _date(hours_ago=1):
    return email.utils.format_datetime(
        datetime.now(timezone.utc).replace(microsecond=0),
        usegmt=True,
    )


def _article(title, source, publisher, event_id, **extra):
    article = {
        "title": title,
        "snippet": "",
        "source": source,
        "publisher": publisher,
        "pub_date": _date(extra.pop("hours_ago", 1)),
        "_event_id": event_id,
        "_event": {"event_id": event_id, "coverage": extra.pop("coverage", 1), "sources": []},
    }
    article.update(extra)
    return article


def _config(**selection):
    base = {
        "enabled": True,
        "candidate_pool": 30,
        "per_source_max": 3,
        "per_publisher_max": 4,
        "per_event_max": 2,
        "category_min": {},
        "noise_title_patterns": [],
        "weights": {
            "importance": 0.30,
            "info_density": 0.20,
            "source_weight": 0.20,
            "recency": 0.15,
            "category_fit": 0.10,
            "fulltext": 0.05,
        },
    }
    base.update(selection)
    return {
        "prefer_categories": ["经济", "财经", "科技", "时政", "国际", "时事"],
        "selection": base,
    }


class FinalSelectTest(unittest.TestCase):
    def test_per_source_cap(self):
        articles = [
            _article("Fed cuts rates as inflation cools", "A", "PA", "e1"),
            _article("Inflation slows in October", "A", "PA", "e2"),
            _article("AI chip demand surges", "B", "PB", "e3"),
            _article("Storm hits Florida coast", "C", "PC", "e4"),
        ]
        selected = final_select(
            articles,
            _config(per_source_max=1, per_publisher_max=9, per_event_max=1),
            total=2,
        )

        self.assertEqual(len(selected), 2)
        self.assertLessEqual(Counter(a["source"] for a in selected)["A"], 1)

    def test_per_publisher_cap(self):
        articles = [
            _article("Fed cuts rates as inflation cools", "A", "P", "e1"),
            _article("AI chip demand surges", "B", "P", "e2"),
            _article("Storm hits Florida coast", "C", "PC", "e3"),
            _article("Election results draw protests", "D", "PD", "e4"),
        ]
        selected = final_select(
            articles,
            _config(per_source_max=9, per_publisher_max=1, per_event_max=1),
            total=2,
        )

        self.assertEqual(len(selected), 2)
        self.assertLessEqual(Counter(a["publisher"] for a in selected)["P"], 1)

    def test_per_event_cap(self):
        articles = [
            _article("Fed cuts rates as inflation cools", "A", "PA", "e1"),
            _article("Inflation slows in October", "B", "PB", "e1"),
            _article("AI chip demand surges", "C", "PC", "e1"),
            _article("Storm hits Florida coast", "D", "PD", "e2"),
            _article("Election results draw protests", "E", "PE", "e3"),
            _article("Oil prices climb on supply fears", "F", "PF", "e4"),
        ]
        selected = final_select(
            articles,
            _config(per_source_max=9, per_publisher_max=9, per_event_max=1),
            total=3,
        )

        self.assertEqual(len(selected), 3)
        self.assertLessEqual(Counter(a["_event_id"] for a in selected)["e1"], 1)

    def test_category_minimum_is_selected_first(self):
        articles = [
            _article("Local team wins championship", "Other", "PO", "e1"),
            _article("Inflation cools as Fed cuts rates", "Econ", "PE", "e2"),
        ]
        config = _config(
            per_source_max=9,
            per_publisher_max=9,
            per_event_max=1,
            category_min={"经济": 1},
            source_weights={"Other": 1.0, "Econ": 0.3},
        )
        selected = final_select(articles, config, total=1)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["source"], "Econ")
        self.assertEqual(selected[0]["_selection"]["category"], "经济")

    def test_returns_fewer_when_pool_is_small(self):
        articles = [
            _article("Fed cuts rates as inflation cools", "A", "PA", "e1"),
            _article("AI chip demand surges", "B", "PB", "e2"),
        ]
        selected = final_select(articles, _config(), total=5)

        self.assertEqual(len(selected), 2)
        self.assertTrue(all("_selection" in a for a in selected))


class PreselectTest(unittest.TestCase):
    def test_respects_pool_size_and_event_diversity(self):
        articles = [
            _article("Fed cuts rates as inflation cools", "A", "PA", "e1"),
            _article("AI chip demand surges", "B", "PB", "e2"),
            _article("Storm hits Florida coast", "C", "PC", "e3"),
            _article("Election results draw protests", "D", "PD", "e4"),
        ]
        selected = preselect(articles, _config(candidate_pool=2, per_event_max=1))

        self.assertEqual(len(selected), 2)
        self.assertEqual(len({a["_event_id"] for a in selected}), 2)


if __name__ == "__main__":
    unittest.main()
