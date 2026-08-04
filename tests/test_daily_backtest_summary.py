import unittest

import pandas as pd

import daily_backtest_summary as summary


class DailyBacktestSummaryTests(unittest.TestCase):
    def test_nse_tracking_stops_on_same_trading_day(self):
        index = pd.DatetimeIndex(
            [
                "2026-07-22 09:15",
                "2026-07-22 13:15",
                "2026-07-23 09:15",
            ],
            tz=summary.IST,
        )
        frame = pd.DataFrame(
            {
                "open": [100.0, 101.0, 120.0],
                "high": [102.0, 103.0, 130.0],
                "low": [99.0, 100.0, 110.0],
                "close": [101.0, 102.0, 125.0],
                "volume": [1, 1, 1],
            },
            index=index,
        )

        end_index, mature = summary.same_day_tracking_end(
            frame,
            pd.Timestamp("2026-07-22 10:00", tz=summary.IST),
        )

        self.assertTrue(mature)
        self.assertEqual(end_index, 1)

    def test_rating_table_includes_all_rating_buckets(self):
        records = pd.DataFrame(
            [
                {"rating": 4},
                {"rating": 5},
                {"rating": 10},
            ]
        )
        table = summary.format_rating_table(records, pd.DataFrame())

        self.assertIn("Rating breakdown", table)
        self.assertIn("Rate  Alert Touch NoTouch Dup Entry BE .5R 1R 2R SL Neither WR", table)
        for rating in range(4, 11):
            self.assertIn(f"{rating:>2}/10", table)

    def test_win_rate_uses_decided_one_r_and_sl_only(self):
        records = pd.DataFrame([{"rating": 6}, {"rating": 6}, {"rating": 6}])
        results = pd.DataFrame(
            [
                {
                    "rating": 6,
                    "filled": True,
                    "outcome": "target_1_then_timeout",
                    "target_1_hit": True,
                    "target_2_hit": False,
                    "mfe_r": 1.1,
                },
                {
                    "rating": 6,
                    "filled": True,
                    "outcome": "stopped",
                    "target_1_hit": False,
                    "target_2_hit": False,
                    "mfe_r": 0.1,
                },
                {
                    "rating": 6,
                    "filled": False,
                    "outcome": "zone_not_touched",
                    "target_1_hit": False,
                    "target_2_hit": False,
                    "mfe_r": float("nan"),
                },
            ]
        )

        table = summary.format_rating_table(records, results)

        self.assertIn(" 6/10     3     2       1   0     2  0   1  1  0  1       0  50.0%", table)


if __name__ == "__main__":
    unittest.main()
