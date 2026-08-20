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

            self.assertEqual(len(config.CRYPTO_WATCHLIST), 97)
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
                "NVDL/USDT:USDT",
                "SLX/USDT:USDT",
                "SOXX/USDT:USDT",
                "MSFT/USDT:USDT",
                "TQQQ/USDT:USDT",
            ):
                self.assertIn(symbol, config.XSTOCK_WATCHLIST)

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
