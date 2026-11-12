import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from stock_market.scraper import trending_sector_from_groww as scraper


class GrowwTrendingSectorTests(unittest.TestCase):
    def test_normalize_sector_keeps_breadth_and_change_data(self):
        result = scraper.normalize_sector(
            {
                "sectorName": "Real Estate",
                "industryCode": "GIC-00005",
                "totalStocks": 171,
                "positiveStocks": 124,
                "negativeStocks": 47,
                "dayChangePercent": 2.8,
            },
            rank=1,
        )

        self.assertEqual(result["rank"], 1)
        self.assertEqual(result["name"], "Real Estate")
        self.assertEqual(result["positive_stocks"], 124)
        self.assertEqual(result["day_change_percent"], 2.8)

    def test_collect_snapshot_normalizes_page_sectors(self):
        sectors = [
            {
                "sectorName": "Real Estate",
                "totalStocks": 2,
                "positiveStocks": 2,
                "negativeStocks": 0,
                "dayChangePercent": 1.5,
            }
        ]
        with patch.object(scraper, "fetch_sectors", return_value=sectors):
            snapshot = scraper.collect_snapshot(
                datetime(2026, 11, 11, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
            )

        self.assertEqual(snapshot["date"], "2026-11-11")
        self.assertEqual(snapshot["count"], 1)
        self.assertEqual(snapshot["sectors"][0]["name"], "Real Estate")
        self.assertEqual(snapshot["source_url"], scraper.SOURCE_URL)

    def test_update_document_retains_15_calendar_dates_and_replaces_same_day(self):
        document = scraper.empty_document()
        document["data"] = [
            {"date": "2026-10-27", "sectors": []},
            {"date": "2026-10-28", "sectors": []},
            {"date": "2026-11-10", "sectors": [{"name": "Old"}]},
            {"date": "2026-11-11", "sectors": [{"name": "Earlier"}]},
        ]
        snapshot = {
            "date": "2026-11-11",
            "captured_at": "2026-11-11T16:00:00+05:30",
            "sectors": [{"name": "Current"}],
        }

        updated = scraper.update_document(document, snapshot)

        self.assertEqual(
            [record["date"] for record in updated["data"]],
            ["2026-10-28", "2026-11-10", "2026-11-11"],
        )
        self.assertEqual(updated["data"][-1]["sectors"], [{"name": "Current"}])

    def test_update_document_skips_duplicate_content_on_another_date(self):
        document = scraper.empty_document()
        prior = {"date": "2026-11-10", "sectors": [{"name": "Real Estate"}]}
        document["data"] = [prior]
        snapshot = {
            "date": "2026-11-11",
            "captured_at": "2026-11-11T16:00:00+05:30",
            "sectors": [{"name": "Real Estate"}],
        }

        updated = scraper.update_document(document, snapshot)

        self.assertIsNone(updated)
        self.assertEqual(document["data"], [prior])

    def test_update_document_skips_unchanged_same_day_snapshot(self):
        snapshot = {
            "date": "2026-11-11",
            "captured_at": "2026-11-11T16:00:00+05:30",
            "sectors": [{"name": "Real Estate"}],
        }
        document = scraper.empty_document()
        document["data"] = [snapshot]
        document["updated_at"] = snapshot["captured_at"]
        repeated = {**snapshot, "captured_at": "2026-11-11T16:05:00+05:30"}

        updated = scraper.update_document(document, repeated)

        self.assertIsNone(updated)
        self.assertEqual(document["data"], [snapshot])

    def test_update_document_updates_same_date_even_if_content_matches_an_older_date(self):
        document = scraper.empty_document()
        prior = {"date": "2026-11-09", "sectors": [{"name": "Real Estate"}]}
        existing_today = {"date": "2026-11-11", "sectors": [{"name": "Other"}]}
        document["data"] = [prior, existing_today]
        snapshot = {
            "date": "2026-11-11",
            "captured_at": "2026-11-11T16:00:00+05:30",
            "sectors": [{"name": "Real Estate"}],
        }

        updated = scraper.update_document(document, snapshot)

        self.assertEqual(updated["data"], [prior, snapshot])


if __name__ == "__main__":
    unittest.main()
