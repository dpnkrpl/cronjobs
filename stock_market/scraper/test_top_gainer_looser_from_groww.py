import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from stock_market.scraper import top_gainer_looser_from_groww as scraper


class GrowwScraperTests(unittest.TestCase):
    def test_normalize_stock_calculates_change_and_keeps_identifiers(self):
        result = scraper.normalize_stock(
            {
                "companyName": "Example Ltd",
                "nseScriptCode": "EXAMPLE",
                "ltp": 110,
                "close": 100,
                "yearHigh": 120,
                "yearLow": 80,
            },
            rank=1,
        )

        self.assertEqual(result["symbol"], "EXAMPLE")
        self.assertEqual(result["rank"], 1)
        self.assertEqual(result["change"], 10)
        self.assertEqual(result["change_percent"], 10)
        self.assertEqual(result["week_52_high"], 120)

    def test_collect_snapshot_includes_all_categories_and_empty_lists(self):
        stock = {"companyName": "Example Ltd", "ltp": 12, "close": 10}
        with patch.object(
            scraper,
            "fetch_page_props",
            side_effect=[
                {"stocks": [stock]},
                {"stocks": [stock]},
                {"stocks": [stock]},
                {"stocks": []},
            ],
        ):
            snapshot = scraper.collect_snapshot(
                datetime(2026, 11, 11, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
            )

        self.assertEqual(snapshot["date"], "2026-11-11")
        self.assertEqual(set(snapshot["categories"]), set(scraper.SOURCE_URLS))
        self.assertEqual(snapshot["categories"]["top_gainers"]["count"], 1)
        self.assertEqual(snapshot["categories"]["week_52_low"]["count"], 0)
        self.assertEqual(snapshot["categories"]["week_52_low"]["stocks"], [])

    def test_update_document_replaces_same_day_and_retains_15_calendar_dates(self):
        document = scraper.empty_document()
        document["data"] = [
            {"date": "2026-10-27", "captured_at": "old"},
            {"date": "2026-10-28", "captured_at": "cutoff"},
            {"date": "2026-11-10", "captured_at": "yesterday"},
            {"date": "2026-11-11", "captured_at": "replace me"},
        ]
        snapshot = {"date": "2026-11-11", "captured_at": "new"}

        updated = scraper.update_document(document, snapshot)

        self.assertEqual(
            [record["date"] for record in updated["data"]],
            ["2026-10-28", "2026-11-10", "2026-11-11"],
        )
        self.assertEqual(updated["data"][-1]["captured_at"], "new")
        self.assertEqual(updated["updated_at"], "new")

    def test_update_document_skips_snapshot_matching_older_market_content(self):
        prior_snapshot = {
            "date": "2026-11-10",
            "captured_at": "2026-11-10T16:00:00+05:30",
            "index": {"id": "GIDXNIFTY500", "name": "NIFTY 500"},
            "categories": {"top_gainers": {"count": 1, "stocks": [{"symbol": "EXAMPLE"}]}},
        }
        document = scraper.empty_document()
        document["data"] = [prior_snapshot]
        matching_snapshot = {
            **prior_snapshot,
            "date": "2026-11-11",
            "captured_at": "2026-11-11T16:00:00+05:30",
        }

        updated = scraper.update_document(document, matching_snapshot)

        self.assertIsNone(updated)
        self.assertEqual(document["data"], [prior_snapshot])

    def test_update_document_keeps_snapshot_when_market_content_changes(self):
        document = scraper.empty_document()
        document["data"] = [
            {
                "date": "2026-11-10",
                "index": {"id": "GIDXNIFTY500", "name": "NIFTY 500"},
                "categories": {"top_gainers": {"count": 0, "stocks": []}},
            }
        ]
        snapshot = {
            "date": "2026-11-11",
            "captured_at": "2026-11-11T16:00:00+05:30",
            "index": {"id": "GIDXNIFTY500", "name": "NIFTY 500"},
            "categories": {"top_gainers": {"count": 1, "stocks": [{"symbol": "EXAMPLE"}]}},
        }

        updated = scraper.update_document(document, snapshot)

        self.assertIsNotNone(updated)
        self.assertEqual(len(updated["data"]), 2)


if __name__ == "__main__":
    unittest.main()
