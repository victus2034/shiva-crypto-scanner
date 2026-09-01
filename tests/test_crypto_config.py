import os
import unittest
from unittest.mock import patch


class CryptoConfigTests(unittest.TestCase):
    def test_default_distance_window_alerts_within_a_fifth_of_a_percent(self):
        # Distance is measured to the entry edge, so this is how close price
        # has to come to the level actually traded before an alert fires.
        with patch.dict(os.environ, {"VICTUS_TIMEFRAME": "4h"}, clear=True):
            import config

            self.assertEqual(config.MIN_DISTANCE_PCT, 0.0)
            self.assertEqual(config.MAX_DISTANCE_PCT, 0.20)

    def test_watchlist_groups_are_composed_without_duplicates(self):
        with patch.dict(os.environ, {}, clear=True):
            import config

            self.assertEqual(len(config.CRYPTO_WATCHLIST), 53)
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
                "MRVL/USDT:USDT",
                # Re-admitted 2026-09-01. It had been dropped for having no
                # live data, but a re-audit - two rounds 30s apart, the same
                # method that removed it - answered from delta_india both
                # times, so the fetch chain reaches it now.
                "NVDAXUSD",
            ):
                self.assertIn(symbol, config.XSTOCK_WATCHLIST)

    def test_symbols_added_from_the_volume_sweep_are_present(self):
        # ETC was culled once for thin volume and came back at 115M over
        # thirty days, so the removal list is not a permanent verdict - it
        # is only ever as good as the last measurement.
        with patch.dict(os.environ, {}, clear=True):
            import config

            # ETC went out again in the 2026-09-01 cut at $49.9K a day on
            # Delta. The CoinSwitch three stay: no volume figure exists for
            # that venue yet, so nothing has been measured to cut them on.
            for symbol in ("CL/USDT", "KORU/USDT", "ACE/USDT"):
                self.assertIn(symbol, config.CRYPTO_WATCHLIST)

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
                # The token is thin even where the ETF behind it is not.
                "SPYXUSD",
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
                "EVAAUSD",
                "BILLUSD",
                # RIVERUSD is gone from this list: re-measured on
                # 2026-09-01 at $6.8M over seven days on Delta, and it
                # answered with 1,000 candles. As the sweep test above
                # says, a removal is only as good as the last measurement.
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
