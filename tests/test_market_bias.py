import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from market_bias import (
    build_force_test_report,
    build_intraday_report,
    build_report,
    classify_bias,
    classify_intraday,
)


class MarketBiasTests(unittest.TestCase):
    def test_bullish_regime(self):
        close = pd.Series(range(100, 220), dtype=float)
        result = classify_bias(pd.DataFrame({"close": close}))
        self.assertEqual(result["bias"], "Bullish")

    def test_bearish_regime(self):
        close = pd.Series(range(220, 100, -1), dtype=float)
        result = classify_bias(pd.DataFrame({"close": close}))
        self.assertEqual(result["bias"], "Bearish")

    def test_report_is_compact_and_labeled(self):
        item = {"name": "NIFTY 50", "metrics": {"bias": "Bullish", "score": 3, "last": 100.0, "one_day_pct": 1.0, "five_day_pct": 2.0}}
        report = build_report({"INDIA": item, "US": item, "LONDON": item})
        self.assertIn("INDIA (NIFTY 50): Bullish", report)
        self.assertIn("Overall: Bullish", report)

    def test_us_report_shows_sector_alerts_only_at_two_percent(self):
        weak = {"bias": "Bearish", "score": -2, "last": 100.0, "bar_pct": -0.3, "session_pct": -1.0}
        results = {"S&P 500": weak, "NASDAQ 100": weak}
        sectors = {"AI / SEMIS": {**weak, "session_pct": -2.4}, "US TECH": weak}
        report = build_intraday_report("us", results, sectors)
        self.assertIn("AI / SEMIS: 2.40% DOWN", report)
        self.assertNotIn("US TECH: 1.00% DOWN", report)

    def test_india_sector_alerts_show_up_and_down(self):
        item = {"bias": "Neutral", "score": 0, "last": 100.0, "bar_pct": 0.0, "session_pct": 2.1}
        sectors = {
            "INDIA HEALTHCARE": item,
            "INDIA IT": {**item, "session_pct": -3.0},
        }
        report = build_intraday_report("india", {}, sectors)
        self.assertIn("INDIA HEALTHCARE: 2.10% UP", report)
        self.assertIn("INDIA IT: 3.00% DOWN", report)

    def test_india_report_uses_sector_names_without_stock_counts(self):
        report = build_intraday_report("india", {}, {})
        self.assertNotIn("89 stocks", report)
        self.assertNotIn("68 stocks", report)
        self.assertNotIn("25 stocks", report)

    def test_us_report_includes_xstock_sector_groups(self):
        weak = {"bias": "Bearish", "score": -2, "last": 100.0, "bar_pct": -0.3, "session_pct": -2.1}
        sectors = {
            "US BROAD / INDEX": weak,
            "US ENERGY": weak,
            "US OTHER / INDUSTRIALS": weak,
        }
        report = build_intraday_report("us", {}, sectors)
        self.assertIn("US BROAD / INDEX: 2.10% DOWN", report)
        self.assertIn("US ENERGY: 2.10% DOWN", report)
        self.assertIn("US OTHER / INDUSTRIALS: 2.10% DOWN", report)

    def test_force_test_is_labeled_and_contains_both_formats(self):
        india = build_force_test_report("india")
        us = build_force_test_report("us")
        self.assertTrue(india.startswith("FORCE TEST - NOT LIVE MARKET DATA"))
        self.assertIn("NSE FINANCIALS: 2.35% DOWN", india)
        self.assertIn("US AI / SEMIS / HARDWARE: 3.05% DOWN", us)

    def test_intraday_session_move_starts_at_market_open(self):
        index = pd.date_range(
            "2026-07-29 09:00", periods=7, freq="30min", tz="America/New_York"
        )
        close = pd.Series([90, 100, 100, 101, 102, 103, 104], index=index)
        result = classify_intraday(
            pd.DataFrame({"close": close}),
            session="us",
            now=datetime(2026, 7, 29, 12, 30, tzinfo=ZoneInfo("America/New_York")),
        )
        self.assertAlmostEqual(result["session_pct"], 4.0)
        self.assertAlmostEqual(result["bar_pct"], 104 / 103 * 100 - 100)

    def test_intraday_session_requires_current_regular_session(self):
        index = pd.date_range(
            "2026-07-28 09:30", periods=4, freq="30min", tz="America/New_York"
        )
        close = pd.Series([100, 101, 102, 103], index=index)
        with self.assertRaisesRegex(RuntimeError, "no current us session data"):
            classify_intraday(
                pd.DataFrame({"close": close}),
                session="us",
                now=datetime(2026, 7, 29, 12, 30, tzinfo=ZoneInfo("America/New_York")),
            )


if __name__ == "__main__":
    unittest.main()
