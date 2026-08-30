import unittest
from unittest.mock import patch

import scanner


def candles(start_ms, count, step_ms=1_800_000, price=100.0):
    return [[start_ms + i * step_ms, price, price, price, price, 1.0] for i in range(count)]


class SpliceTests(unittest.TestCase):
    def setUp(self):
        self.recent = candles(2_000_000_000_000, 5)
        self.oldest = int(self.recent[0][0])

    def test_a_symbol_not_measured_is_left_alone(self):
        # Splicing a symbol whose venues disagree would draw the zone at a
        # price that never traded on the book being charted.
        with patch.object(scanner, "DEEP_HISTORY_SYMBOLS", set()):
            self.assertIs(scanner.splice_deep_history("BTCUSDT", self.recent), self.recent)

    def test_older_candles_are_prepended_in_order(self):
        older = candles(self.oldest - 10 * 1_800_000, 10)
        with patch.object(scanner, "DEEP_HISTORY_SYMBOLS", {"BTC"}):
            with patch.object(scanner, "fetch_exchange_ohlcv", return_value=older):
                with patch.dict(scanner.EXCHANGES_BY_ID, {"kucoin": object()}):
                    result = scanner.splice_deep_history("BTCUSDT", self.recent)

        self.assertEqual(len(result), 15)
        stamps = [int(row[0]) for row in result]
        self.assertEqual(stamps, sorted(stamps))
        self.assertEqual(result[-5:], self.recent)

    def test_the_charted_venue_always_wins_on_overlap(self):
        # The deep venue also returns bars CoinSwitch already has. Those must
        # be discarded: current price, the entry level and zone breaks all
        # have to come from the book on screen.
        overlapping = candles(self.oldest, 5, price=999.0)
        older = candles(self.oldest - 3 * 1_800_000, 3)
        with patch.object(scanner, "DEEP_HISTORY_SYMBOLS", {"BTC"}):
            with patch.object(scanner, "fetch_exchange_ohlcv", return_value=older + overlapping):
                with patch.dict(scanner.EXCHANGES_BY_ID, {"kucoin": object()}):
                    result = scanner.splice_deep_history("BTCUSDT", self.recent)

        self.assertEqual(len(result), 8)
        self.assertNotIn(999.0, [row[4] for row in result])

    def test_a_failed_extension_leaves_the_series_intact(self):
        with patch.object(scanner, "DEEP_HISTORY_SYMBOLS", {"BTC"}):
            with patch.object(scanner, "fetch_exchange_ohlcv", side_effect=RuntimeError("429")):
                with patch.dict(scanner.EXCHANGES_BY_ID, {"kucoin": object()}):
                    result = scanner.splice_deep_history("BTCUSDT", self.recent)

        self.assertEqual(result, self.recent)

    def test_nothing_older_available_is_not_an_error(self):
        with patch.object(scanner, "DEEP_HISTORY_SYMBOLS", {"BTC"}):
            with patch.object(scanner, "fetch_exchange_ohlcv", return_value=self.recent):
                with patch.dict(scanner.EXCHANGES_BY_ID, {"kucoin": object()}):
                    result = scanner.splice_deep_history("BTCUSDT", self.recent)

        self.assertEqual(result, self.recent)


if __name__ == "__main__":
    unittest.main()

class SpliceListTests(unittest.TestCase):
    def test_the_list_only_holds_symbols_we_actually_scan(self):
        import config

        held = {scanner.display_symbol(s) for s in scanner.active_watchlist()}
        self.assertTrue(config.DEEP_HISTORY_SYMBOLS <= held)

    def test_the_measured_majors_are_spliced(self):
        # These priced the same candle within 0.05%, a quarter of the
        # alert distance, across 751 shared candles.
        import config

        for symbol in ("BTC", "ETH", "SOL", "XRP", "BNB"):
            with self.subTest(symbol=symbol):
                self.assertIn(symbol, config.DEEP_HISTORY_SYMBOLS)

    def test_the_venues_that_disagree_are_not_spliced(self):
        # ESPORTS is 1.11% apart typically and 2.9% at worst - five to
        # fifteen times the alert distance. STORJ, COTI and ZIL likewise.
        import config

        for symbol in ("ESPORTS", "STORJ", "COTI", "ZIL", "ACE", "HOME"):
            with self.subTest(symbol=symbol):
                self.assertNotIn(symbol, config.DEEP_HISTORY_SYMBOLS)

