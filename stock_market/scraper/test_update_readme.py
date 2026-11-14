import unittest

from stock_market.scraper.update_readme import find_streaks, format_percent, latest_fetch_label


class READMEStreakTests(unittest.TestCase):
    def test_streaks_compound_returns_and_reset_when_missing(self):
        streaks = find_streaks(
            [
                ("2026-11-09", {"AAA": 10.0, "BBB": -2.0}),
                ("2026-11-10", {"AAA": 10.0, "BBB": -2.0}),
                ("2026-11-11", {}),
                ("2026-11-12", {"AAA": 5.0}),
                ("2026-11-13", {"AAA": 2.0}),
            ]
        )

        runs_by_symbol = {}
        for streak in streaks:
            runs_by_symbol.setdefault(streak["symbol"], []).append(streak)

        self.assertEqual(len(runs_by_symbol["AAA"]), 2)
        self.assertEqual(runs_by_symbol["AAA"][0]["snapshots"], 2)
        self.assertAlmostEqual(runs_by_symbol["AAA"][0]["change_percent"], 21.0)
        self.assertEqual(runs_by_symbol["AAA"][1]["start"], "2026-11-12")
        self.assertAlmostEqual(runs_by_symbol["AAA"][1]["change_percent"], 7.1)
        self.assertAlmostEqual(runs_by_symbol["BBB"][0]["change_percent"], -3.96)

    def test_percentages_use_matching_circle_marker(self):
        self.assertEqual(format_percent(2.5), ":green_circle: +2.50%")
        self.assertEqual(format_percent(-1.25), ":red_circle: -1.25%")

    def test_latest_fetch_uses_newest_document_timestamp(self):
        latest = latest_fetch_label(
            [
                {"updated_at": "2026-11-13T16:00:00+05:30"},
                {"updated_at": "2026-11-13T23:27:19+05:30"},
            ]
        )

        self.assertEqual(latest, "2026-11-13 23:27:19 IST")


if __name__ == "__main__":
    unittest.main()