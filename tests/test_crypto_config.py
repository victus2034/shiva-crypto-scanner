import os
import unittest
from unittest.mock import patch


class CryptoConfigTests(unittest.TestCase):
    def test_default_distance_window_alerts_within_a_fifth_of_a_percent(self):
        # Distance is measured to the entry edge, so this is how close price
        # has to come to the level actually traded before an alert fires.
        with patch.dict(os.environ, {"SHIVA_TIMEFRAME": "4h"}, clear=True):
            import config

            self.assertEqual(config.MIN_DISTANCE_PCT, 0.0)
            self.assertEqual(config.MAX_DISTANCE_PCT, 0.20)

    def test_watchlist_groups_are_composed_without_duplicates(self):
        with patch.dict(os.environ, {}, clear=True):
            import config

            self.assertEqual(len(config.CRYPTO_WATCHLIST), 94)
            self.assertLessEqual(len(config.CRYPTO_WATCHLIST), 100)
            self.assertEqual(
                config.WATCHLIST,
                config.CRYPTO_WATCHLIST
                + config.OTHER_WATCHLIST
                + config.XSTOCK_WATCHLIST,
            )
            self.assertEqual(len(config.WATCHLIST), len(set(config.WATCHLIST)))

    def test_existing_xstock_symbols_are_preserved(self):
        with patch.dict(os.environ, {}, clear=True):
            import config

            for symbol in (
                "SLX/USDT:USDT",
                "MSFT/USDT:USDT",
                "HOOD/USDT:USDT",
                "MRVL/USDT:USDT",
            ):
                self.assertIn(symbol, config.XSTOCK_WATCHLIST)

    def test_thin_volume_symbols_are_removed(self):
        # Measured on CoinSwitch over 96 30m candles: all ten traded under
        # 11,000 per candle against a watchlist median near 200,000, and
        # several had candles with no trades at all.
        with patch.dict(os.environ, {}, clear=True):
            import config

            for symbol in (
                "FLNC/USDT:USDT",
                "IBM/USDT:USDT",
                "PHAROS/USDT",
                "SOXX/USDT:USDT",
                "NVDL/USDT:USDT",
                "BABA/USDT:USDT",
                "DELL/USDT:USDT",
                "AVGO/USDT:USDT",
                "TAIKO/USDT",
                "TQQQ/USDT:USDT",
                # Measurable only once the xStocks were fetched under the
                # names CoinSwitch actually uses.
                "OPENAI/USDT:USDT",
                "AMZNXUSD",
                # Not thin but dead: unlisted, last candle ten days old.
                "VANRY/USDT",
            ):
                self.assertNotIn(symbol, config.WATCHLIST)

    def test_sector_context_survives_dropping_a_watchlist_symbol(self):
        # SOXX is both a scanned symbol and the sector reference for the
        # semiconductor names. Dropping it from the watchlist must not take
        # the sector context with it - that comes from the listed ETF.
        import xstock_hybrid_rating as rating

        self.assertEqual(rating.XSTOCK_UNDERLYINGS["INTCBUSD"]["sector"], "SOXX")

    def test_low_volume_and_unlisted_crypto_symbols_are_removed(self):
        with patch.dict(os.environ, {}, clear=True):
            import config

            removed_symbols = {
                "ETCUSD",
                "EVAAUSD",
                "BILLUSD",
                "RIVERUSD",
                "VELVET/USDT",
                "T/USDT",
                "MUSD",
                "TRIA/USDT",
                "MAGMA/USDT",
                "SXT/USDT",
                "CVX/USDT:USDT",
                "THE/USDT",
                "FET/USDT",
                "DODO/USDT",
                "AIOTUSD",
                "SYN/USDT",
                "LIT/USDT",
                "RIF/USDT",
            }
            self.assertTrue(removed_symbols.isdisjoint(config.WATCHLIST))

    def test_crypto_slx_is_excluded_to_avoid_xstock_symbol_collision(self):
        with patch.dict(os.environ, {}, clear=True):
            import config

            self.assertNotIn("SLX/USDT", config.CRYPTO_WATCHLIST)
            self.assertIn("SLX/USDT:USDT", config.XSTOCK_WATCHLIST)

    def test_active_watchlist_blocks_misidentified_xstock_contracts(self):
        import scanner

        symbols = scanner.active_watchlist()

        self.assertNotIn("BZ/USDT:USDT", symbols)
        self.assertNotIn("SLX/USDT:USDT", symbols)


if __name__ == "__main__":
    unittest.main()
