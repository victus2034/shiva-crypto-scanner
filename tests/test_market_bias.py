import unittest

import pandas as pd

from market_bias import build_intraday_report, build_report, classify_bias


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

    def test_us_report_warns_when_ai_and_tech_are_weak(self):
        weak = {"bias": "Bearish", "score": -2, "last": 100.0, "bar_pct": -0.3, "session_pct": -1.0}
        results = {"S&P 500": weak, "NASDAQ 100": weak, "AI / SEMIS": weak, "US TECH": weak}
        report = build_intraday_report("us", results)
        self.assertIn("US AI/tech risk-off", report)


if __name__ == "__main__":
    unittest.main()
