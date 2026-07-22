import unittest

import nse_scanner
import scanner


class AlertFormatTests(unittest.TestCase):
    def test_crypto_zone_alert_uses_compact_format(self):
        result = {
            "symbol": "MSTRBUSD",
            "price": 100.6,
            "buy_signal": False,
            "sell_signal": False,
        }
        zone = {"bottom": 100.2, "top": 100.33645}

        message = scanner.format_alert(result, "demand", zone, 0.4)

        self.assertEqual(
            message,
            "MSTRBUSD is 0.40% away from a BUY zone\n"
            "Price: 100.600000\n"
            "Level: 100.200000\n"
            "Zone: 100.200000 - 100.336450\n"
            "Range Filter Buy Signal: False\n"
            "Range Filter Sell Signal: False",
        )

    def test_nse_zone_alert_has_no_market_or_timeframe_lines(self):
        result = {
            "symbol": "PIDILITIND.NS",
            "price": 1610.9,
            "buy_signal": False,
            "sell_signal": False,
        }
        zone = {"bottom": 1624.95, "top": 1626.6}

        message = nse_scanner.format_alert(result, "supply", zone, 0.97)

        self.assertNotIn("Market:", message)
        self.assertNotIn("Timeframe:", message)
        self.assertNotIn("\n\n", message)

    def test_range_filter_alerts_are_compact(self):
        crypto_result = {
            "symbol": "BTCUSD",
            "price": 100.0,
            "demand_dist": 1.0,
            "supply_dist": 2.0,
        }
        nse_result = {**crypto_result, "symbol": "RELIANCE.NS"}

        crypto_message = scanner.format_signal_alert(crypto_result, "buy")
        nse_message = nse_scanner.format_signal_alert(nse_result, "sell")

        for message in (crypto_message, nse_message):
            self.assertNotIn("Exchange:", message)
            self.assertNotIn("Price source:", message)
            self.assertNotIn("Candle time", message)
            self.assertNotIn("Market:", message)
            self.assertNotIn("Timeframe:", message)


if __name__ == "__main__":
    unittest.main()
