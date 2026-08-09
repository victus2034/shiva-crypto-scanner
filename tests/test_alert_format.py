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
            "MSTR is 0.40% away from a BUY zone\n"
            "Price: 100.600000\n"
            "Level: 100.200000\n"
            "Zone: 100.200000 - 100.336450",
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
        self.assertNotIn("Range Filter", message)

    def test_nse_30m_zone_rating_starts_at_four(self):
        result = {"symbol": "TEST.NS", "price": 100.0}
        zone = {"bottom": 99.0, "top": 99.5, "max_touch_streak": 1}
        nse_scanner.TIMEFRAME = "30m"
        nse_scanner.SHOW_ZONE_RATINGS = True
        nse_scanner.MAX_DISTANCE_PCT = 0.75

        message = nse_scanner.format_alert(result, "demand", zone, 0.70)

        self.assertIn("Zone Rating: 4/10", message)

    def test_nse_4h_zone_alert_has_no_rating(self):
        result = {"symbol": "TEST.NS", "price": 100.0}
        zone = {"bottom": 99.0, "top": 99.5, "max_touch_streak": 0}
        nse_scanner.TIMEFRAME = "4h"
        nse_scanner.SHOW_ZONE_RATINGS = True

        message = nse_scanner.format_alert(result, "demand", zone, 0.70)

        self.assertNotIn("Zone Rating:", message)

    def test_crypto_zone_rating_adds_one_compact_line(self):
        result = {
            "symbol": "BTCUSD",
            "price": 100.6,
            "demand_rating": {
                "score": 9,
            },
        }
        zone = {"bottom": 100.2, "top": 100.33645}

        message = scanner.format_alert(result, "demand", zone, 0.4)

        self.assertTrue(message.endswith("Score: 9/10"))
        self.assertNotIn("\n\n", message)

    def test_xstock_hybrid_score_overrides_base_display_score(self):
        result = {
            "symbol": "NVDAXUSD",
            "price": 190.0,
            "demand_score": 5,
            "demand_rating": {
                "kind": "xstock_hybrid",
                "score": 8,
            },
        }
        zone = {"bottom": 188.0, "top": 188.5}

        message = scanner.format_alert(result, "demand", zone, 0.5)

        self.assertTrue(message.endswith("Score: 8/10"))
        self.assertNotIn("Score: 5/10", message)
        self.assertEqual(message.count("Score:"), 1)

    def test_xstock_range_filter_alert_has_one_compact_score(self):
        result = {
            "symbol": "NVDAXUSD",
            "price": 190.0,
            "demand": {"bottom": 188.0, "top": 188.5},
            "supply": None,
            "demand_dist": 0.5,
            "supply_dist": 999.0,
            "demand_rating": {
                "kind": "xstock_hybrid",
                "score": 8,
            },
        }

        message = scanner.format_signal_alert(result, "buy")

        self.assertTrue(message.endswith("Score: 8/10"))
        self.assertEqual(message.count("Score:"), 1)

    def test_range_filter_alerts_are_compact(self):
        crypto_result = {
            "symbol": "BTCUSD",
            "price": 100.0,
            "demand": {"bottom": 99.0, "top": 99.5},
            "supply": None,
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

    def test_range_filter_alert_does_not_print_missing_zone_as_999(self):
        result = {
            "symbol": "EWYBUSD",
            "price": 161.1,
            "demand": None,
            "supply": {"bottom": 162.0, "top": 162.5},
            "demand_dist": 999.0,
            "supply_dist": 0.56,
        }

        message = scanner.format_signal_alert(result, "buy")

        self.assertIn("Nearest Demand Distance: N/A", message)
        self.assertNotIn("999.00%", message)


if __name__ == "__main__":
    unittest.main()
