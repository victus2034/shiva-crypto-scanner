import unittest

import pandas as pd

import weekly_backtest_summary as weekly


class WeeklyBacktestSummaryTests(unittest.TestCase):
    def rows(self):
        return pd.DataFrame(
            [
                {
                    "market": "NSE",
                    "timeframe": "30m",
                    "date": "2026-08-03",
                    "symbol": "A.NS",
                    "display_symbol": "A",
                    "side": "long",
                    "rating": 5,
                    "filled": False,
                    "outcome": "zone_not_touched",
                    "final_result": "",
                    "net_realized_r": float("nan"),
                },
                {
                    "market": "NSE",
                    "timeframe": "30m",
                    "date": "2026-08-03",
                    "symbol": "B.NS",
                    "display_symbol": "B",
                    "side": "short",
                    "rating": 5,
                    "filled": False,
                    "outcome": "data_missing",
                    "final_result": "",
                    "net_realized_r": float("nan"),
                },
                {
                    "market": "NSE",
                    "timeframe": "30m",
                    "date": "2026-08-04",
                    "symbol": "A.NS",
                    "display_symbol": "A",
                    "side": "long",
                    "rating": 6,
                    "filled": True,
                    "outcome": "+1R",
                    "final_result": "+1R",
                    "net_realized_r": 1.0,
                },
            ]
        )

    def test_weekly_no_touch_uses_explicit_outcome_only(self):
        message = weekly.build_weekly_summary(
            self.rows(),
            "30m",
            pd.Timestamp("2026-08-03").date(),
            pd.Timestamp("2026-08-07").date(),
        )

        self.assertIn("Stocks — 2", message)
        self.assertIn("No Touch — 1", message)
        self.assertNotIn("No Touch — 2", message)

    def test_weekly_rating_blocks_use_explicit_no_touch_only(self):
        blocks = weekly.format_weekly_rating_blocks(self.rows())

        self.assertIn("5/10", blocks)
        self.assertIn("No Touch — 1", blocks)
        self.assertNotIn("No Touch — 2", blocks)


if __name__ == "__main__":
    unittest.main()
