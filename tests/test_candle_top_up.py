import time
import unittest
from unittest.mock import patch

import scanner


def minute(start_ms, offset_minutes, open_, high, low, close, volume):
    return [start_ms + offset_minutes * 60_000, open_, high, low, close, volume]


class BucketCandlesTests(unittest.TestCase):
    def test_finer_candles_collapse_into_one_bucket(self):
        base = 1787000000000 // 1_800_000 * 1_800_000
        rows = [
            minute(base, 0, 10, 12, 9, 11, 5),
            minute(base, 1, 11, 15, 10, 14, 7),
            minute(base, 2, 14, 14, 13, 13, 2),
        ]

        buckets = scanner.bucket_candles(rows, 1800)

        self.assertEqual(len(buckets), 1)
        start, open_, high, low, close, volume = buckets[0]
        self.assertEqual(start, base)
        self.assertEqual(open_, 10)   # first
        self.assertEqual(high, 15)    # highest
        self.assertEqual(low, 9)      # lowest
        self.assertEqual(close, 13)   # last
        self.assertEqual(volume, 14)  # summed

    def test_gaps_do_not_invent_buckets(self):
        # CoinSwitch omits any period with no trades. An absent bucket must
        # stay absent, because the user's chart does not draw one either.
        base = 1787000000000 // 1_800_000 * 1_800_000
        rows = [minute(base, 0, 10, 10, 10, 10, 1), minute(base, 65, 20, 20, 20, 20, 1)]

        buckets = scanner.bucket_candles(rows, 1800)

        self.assertEqual([bucket[0] for bucket in buckets], [base, base + 2 * 1_800_000])


class TopUpTests(unittest.TestCase):
    def setUp(self):
        now = time.time()
        self.bucket_ms = 1_800_000
        # Three whole buckets back, so everything below is safely complete.
        self.base = int(now * 1000) // self.bucket_ms * self.bucket_ms - 3 * self.bucket_ms
        self.published = [[self.base, 1.0, 1.0, 1.0, 1.0, 1.0]]

    def _finer(self):
        return [
            minute(self.base + self.bucket_ms, 0, 2.0, 3.0, 1.5, 2.5, 4.0),
            minute(self.base + 2 * self.bucket_ms, 0, 2.5, 4.0, 2.0, 3.5, 6.0),
        ]

    def test_missing_buckets_are_rebuilt_from_finer_candles(self):
        with patch.object(scanner, "TIMEFRAME", "30m"):
            with patch.object(scanner, "_fetch_coinswitch_ohlcv_once", return_value=self._finer()):
                result = scanner.top_up_recent_candles("BTCUSDT", self.published)

        self.assertEqual(len(result), 3)
        self.assertEqual([row[0] for row in result],
                         [self.base, self.base + self.bucket_ms, self.base + 2 * self.bucket_ms])

    def test_published_candles_are_never_rewritten(self):
        overlapping = [minute(self.base, 0, 99.0, 99.0, 99.0, 99.0, 99.0)] + self._finer()

        with patch.object(scanner, "TIMEFRAME", "30m"):
            with patch.object(scanner, "_fetch_coinswitch_ohlcv_once", return_value=overlapping):
                result = scanner.top_up_recent_candles("BTCUSDT", self.published)

        self.assertEqual(result[0], self.published[0])

    def test_a_still_forming_bucket_is_left_out(self):
        forming_start = int(time.time() * 1000) // self.bucket_ms * self.bucket_ms
        finer = self._finer() + [[forming_start, 5.0, 5.0, 5.0, 5.0, 1.0]]

        with patch.object(scanner, "TIMEFRAME", "30m"):
            with patch.object(scanner, "_fetch_coinswitch_ohlcv_once", return_value=finer):
                result = scanner.top_up_recent_candles("BTCUSDT", self.published)

        self.assertNotIn(forming_start, [row[0] for row in result])

    def test_a_failed_top_up_leaves_the_published_series_alone(self):
        with patch.object(scanner, "TIMEFRAME", "30m"):
            with patch.object(scanner, "_fetch_coinswitch_ohlcv_once",
                              side_effect=RuntimeError("429")):
                result = scanner.top_up_recent_candles("BTCUSDT", self.published)

        self.assertEqual(result, self.published)

    def test_timeframes_without_a_finer_source_are_untouched(self):
        with patch.object(scanner, "TIMEFRAME", "1d"):
            result = scanner.top_up_recent_candles("BTCUSDT", self.published)

        self.assertEqual(result, self.published)


if __name__ == "__main__":
    unittest.main()
