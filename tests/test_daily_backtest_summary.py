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


if __name__ == "__main__":
    unittest.main()
