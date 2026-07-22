import unittest
from unittest.mock import patch

import pandas as pd

import nse_scanner


class NseIndicatorParityTests(unittest.TestCase):
    def test_atr_uses_wilder_rma(self):
        data = pd.DataFrame(
            {
                "high": [11.0, 13.0, 14.0, 18.0],
                "low": [9.0, 10.0, 11.0, 14.0],
                "close": [10.0, 12.0, 13.0, 17.0],
            }
        )

        result = nse_scanner.atr(data, period=3)

        self.assertTrue(pd.isna(result.iloc[0]))
        self.assertTrue(pd.isna(result.iloc[1]))
        self.assertAlmostEqual(result.iloc[2], 8.0 / 3.0)
        self.assertAlmostEqual(result.iloc[3], 31.0 / 9.0)

    def test_broken_zone_does_not_block_later_replacement(self):
        data = pd.DataFrame(
            {
                "high": [90.0, 95.0, 100.0, 96.0, 95.0, 102.0, 101.0, 98.0, 97.0, 96.0],
                "low": [80.0] * 10,
                "close": [90.0, 90.0, 90.0, 90.0, 90.0, 101.0, 90.0, 90.0, 99.0, 99.0],
            }
        )
        atr_values = pd.Series([2.0] * len(data), index=data.index)

        with (
            patch.object(nse_scanner, "SWING_LENGTH", 2),
            patch.object(nse_scanner, "atr", return_value=atr_values),
            patch.object(nse_scanner, "find_pivots", return_value=([2, 6], [])),
        ):
            supply, _ = nse_scanner.build_zones(data)

        active_supply = [zone for zone in supply if zone["active"]]
        self.assertEqual(len(active_supply), 1)
        self.assertEqual(active_supply[0]["top"], 101.0)
        self.assertEqual(active_supply[0]["pivot_idx"], 6)

    def test_30m_resample_is_anchored_to_nse_open(self):
        index = pd.date_range("2026-07-22 09:15", periods=4, freq="15min", tz="Asia/Kolkata")
        data = pd.DataFrame(
            {
                "open": [10.0, 11.0, 12.0, 13.0],
                "high": [11.0, 12.0, 13.0, 14.0],
                "low": [9.0, 10.0, 11.0, 12.0],
                "close": [10.5, 11.5, 12.5, 13.5],
                "volume": [1, 2, 3, 4],
            },
            index=index,
        )

        with (
            patch.object(nse_scanner, "TIMEFRAME", "30m"),
            patch.object(nse_scanner, "SOURCE_INTERVAL", "15m"),
        ):
            result = nse_scanner.resample_for_timeframe(data)

        self.assertEqual(list(result.index.minute), [15, 45])
        self.assertEqual(result.iloc[0]["open"], 10.0)
        self.assertEqual(result.iloc[0]["close"], 11.5)
        self.assertEqual(result.iloc[0]["volume"], 3)

    def test_incomplete_candle_is_excluded_from_indicator(self):
        data = pd.DataFrame(
            {
                "Datetime": pd.to_datetime(
                    ["2026-07-22 09:15", "2026-07-22 09:45"]
                ).tz_localize("Asia/Kolkata"),
                "close": [100.0, 101.0],
            }
        )
        now = pd.Timestamp("2026-07-22 10:00", tz="Asia/Kolkata")

        with patch.object(nse_scanner, "TIMEFRAME", "30m"):
            result = nse_scanner.confirmed_candles(data, now=now)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[-1]["close"], 100.0)

    def test_hourly_download_uses_bounded_explicit_range(self):
        now = pd.Timestamp("2026-07-22 16:00", tz="UTC")

        with patch.object(nse_scanner, "SOURCE_INTERVAL", "1h"):
            result = nse_scanner.yfinance_time_range(now=now)

        self.assertNotIn("period", result)
        self.assertEqual(result["end"] - result["start"], pd.Timedelta(days=700))


if __name__ == "__main__":
    unittest.main()
