import unittest

import config
import nse_config


class LookbackTests(unittest.TestCase):
    def test_crypto_sees_at_least_a_month_of_30m_candles(self):
        # A zone from three weeks back was never ignored - it was not in the
        # data. Crypto trades around the clock, so 500 candles is ten days.
        days = config.OHLCV_LIMIT * 30 / 60 / 24
        self.assertGreaterEqual(days, 30)

    def test_nse_sees_at_least_a_month_of_sessions(self):
        # NSE trades 6.25 hours a day, so the same 500 candles is forty
        # sessions. The lookback is fine there; only the cap needed raising.
        sessions = nse_config.OHLCV_LIMIT / 12.5
        self.assertGreaterEqual(sessions, 30)

    def test_the_zone_cap_does_not_bite_before_the_lookback_does(self):
        # The cap keeps the newest zones, so setting it below what a symbol
        # actually produces discards exactly the old levels the lookback
        # exists to find. Six majors produced 19-32 a side at 1500 bars.
        for module in (config, nse_config):
            with self.subTest(module=module.__name__):
                self.assertGreaterEqual(module.HISTORY_OF_ZONES_TO_KEEP, 40)


if __name__ == "__main__":
    unittest.main()
