import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from stock_market.scraper import bulk_deals_from_nse as scraper


class NSEBulkDealsTests(unittest.TestCase):
    def test_collect_snapshots_uses_each_table_row_date(self):
        payload = {
            "BULK_DEALS_DATA": [
                {
                    "date": "11-Nov-2026",
                    "symbol": "EXAMPLE",
                    "name": "Example Ltd",
                    "clientName": "Example Client",
                    "buySell": "BUY",
                    "qty": "1,200",
                    "watp": "42.50",
                    "remarks": "-",
                },
                {
                    "date": "10-Nov-2026",
                    "symbol": "OTHER",
                    "name": "Other Ltd",
                    "clientName": "Other Client",
                    "buySell": "SELL",
                    "qty": "500",
                    "watp": "10",
                    "remarks": None,
                },
            ]
        }

        snapshots = scraper.collect_snapshots(
            payload,
            datetime(2026, 11, 11, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
        )

        self.assertEqual([item["deal_date"] for item in snapshots], ["2026-11-10", "2026-11-11"])
        self.assertEqual(snapshots[1]["deals"][0]["quantity"], 1200)
        self.assertEqual(snapshots[1]["deals"][0]["weighted_average_trade_price"], 42.5)

    def test_merge_skips_exact_duplicate_for_table_date(self):
        snapshot = {
            "deal_date": "2026-11-11",
            "captured_at": "2026-11-11T16:00:00+05:30",
            "deals": [{"symbol": "EXAMPLE", "quantity": 1200}],
        }
        document = scraper.empty_document()
        document["data"] = [snapshot]

        updated, changed, skipped = scraper.merge_snapshots(
            document,
            [{**snapshot, "captured_at": "2026-11-12T16:00:00+05:30"}],
        )

        self.assertEqual(changed, [])
        self.assertEqual(skipped, ["2026-11-11"])
        self.assertEqual(updated["data"], [snapshot])
        self.assertEqual(updated["updated_at"], None)

    def test_merge_replaces_changed_data_for_existing_date(self):
        document = scraper.empty_document()
        document["data"] = [
            {
                "deal_date": "2026-11-11",
                "captured_at": "old",
                "deals": [{"symbol": "EXAMPLE", "quantity": 1200}],
            }
        ]
        corrected = {
            "deal_date": "2026-11-11",
            "captured_at": "new",
            "deals": [{"symbol": "EXAMPLE", "quantity": 1300}],
        }

        updated, changed, skipped = scraper.merge_snapshots(document, [corrected])

        self.assertEqual(changed, ["2026-11-11"])
        self.assertEqual(skipped, [])
        self.assertEqual(updated["data"], [corrected])
        self.assertEqual(updated["updated_at"], "new")

    def test_merge_keeps_only_15_most_recent_table_dates(self):
        document = scraper.empty_document()
        snapshots = [
            {
                "deal_date": f"2026-10-{day:02d}",
                "captured_at": f"2026-10-{day:02d}T16:00:00+05:30",
                "deals": [],
            }
            for day in range(1, 17)
        ]

        updated, _, _ = scraper.merge_snapshots(document, snapshots)

        self.assertEqual(len(updated["data"]), 15)
        self.assertEqual(updated["data"][0]["deal_date"], "2026-10-02")
        self.assertEqual(updated["data"][-1]["deal_date"], "2026-10-16")


if __name__ == "__main__":
    unittest.main()
