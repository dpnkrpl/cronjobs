import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from stock_market.scraper import financial_results_from_nse as scraper


class NSEFinancialResultsTests(unittest.TestCase):
    def test_collect_events_filters_results_and_normalizes_equity_and_sme_dates(self):
        feeds = {
            "equity": [
                {
                    "symbol": "EXAMPLE",
                    "company": "Example Ltd",
                    "purpose": "Financial Results/Other business matters",
                    "bm_desc": "Results for September 2026",
                    "date": "12-Nov-2026",
                },
                {
                    "symbol": "OTHER",
                    "company": "Other Ltd",
                    "purpose": "Board Meeting",
                    "bm_desc": "Approve a dividend",
                    "date": "12-Nov-2026",
                },
            ],
            "sme": [
                {
                    "bm_symbol": "SMECO",
                    "sm_name": "SME Co",
                    "bm_purpose": "Board Meeting Intimation",
                    "bm_desc": "To approve unaudited financial results for September 2026",
                    "bm_date": "14-Nov-2026",
                    "bm_timestamp": "11-Nov-2026 22:43:16",
                    "sm_isin": "12345",
                    "attachment": "https://example.test/filing.pdf",
                    "ixbrl": None,
                },
                {
                    "bm_symbol": "SMEOTHER",
                    "sm_name": "SME Other",
                    "bm_purpose": "Board Meeting Intimation",
                    "bm_desc": "Other business matters",
                    "bm_date": "14-Nov-2026",
                },
            ],
        }

        events = scraper.collect_events(
            feeds,
            datetime(2026, 11, 11, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event_date"], "2026-11-12")
        self.assertEqual(events[0]["symbol"], "EXAMPLE")
        self.assertEqual(events[1]["event_date"], "2026-11-14")
        self.assertEqual(events[1]["market_segment"], "sme")
        self.assertEqual(events[1]["attachment_url"], "https://example.test/filing.pdf")

    def test_add_new_events_deduplicates_ignoring_capture_timestamp(self):
        document = scraper.empty_document()
        existing = {
            "event_date": "2026-11-12",
            "market_segment": "equity",
            "symbol": "EXAMPLE",
            "purpose": "Financial Results",
            "captured_at": "2026-11-11T16:00:00+05:30",
        }
        document["data"] = [existing]
        repeated = {**existing, "captured_at": "2026-11-12T16:00:00+05:30"}

        updated, added_count = scraper.add_new_events(document, [repeated])

        self.assertEqual(added_count, 0)
        self.assertIs(updated, document)
        self.assertEqual(updated["data"], [existing])

    def test_add_new_events_keeps_unlimited_history_and_unique_events(self):
        document = scraper.empty_document()
        document["data"] = [
            {"event_date": f"2025-01-{day:02d}", "symbol": f"OLD{day}"}
            for day in range(1, 21)
        ]
        new_event = {
            "event_date": "2026-11-12",
            "market_segment": "equity",
            "symbol": "NEWCO",
            "purpose": "Financial Results",
            "captured_at": "2026-11-11T16:00:00+05:30",
        }

        updated, added_count = scraper.add_new_events(document, [new_event, new_event])

        self.assertEqual(added_count, 1)
        self.assertEqual(len(updated["data"]), 21)
        self.assertEqual(updated["data"][-1], new_event)
        self.assertEqual(updated["updated_at"], new_event["captured_at"])


if __name__ == "__main__":
    unittest.main()
