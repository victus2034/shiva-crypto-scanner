import unittest

import nse_scanner
import scanner
from zone_scoring import score_wick_zone


class ZoneScoringTests(unittest.TestCase):
    def test_weak_retested_zone_keeps_base_score(self):
        zone = {
            "wick_to_body": 1.5,
            "wick_atr": 0.15,
            "departure_atr": 0.75,
            "touch_count": 2,
        }

        self.assertEqual(score_wick_zone(zone, 1.25, 0.25, 1.25), 4)

    def test_strong_fresh_zone_reaches_ten(self):
        zone = {
            "wick_to_body": 3.0,
            "wick_atr": 0.8,
            "departure_atr": 3.0,
            "touch_count": 0,
        }

        self.assertEqual(score_wick_zone(zone, 0.4, 0.25, 1.25), 10)

    def test_crypto_four_hour_alert_displays_rule_based_score(self):
        result = {"symbol": "BTCUSDT", "price": 100.0, "demand_score": 8}
        zone = {"bottom": 99.0, "top": 99.5}

        message = scanner.format_alert(result, "demand", zone, 0.5)

        self.assertTrue(message.startswith("BTC | BUY | 8/10"))

    def test_nse_four_hour_alert_displays_rule_based_score(self):
        result = {"symbol": "RELIANCE.NS", "price": 100.0, "supply_score": 7}
        zone = {"bottom": 100.5, "top": 101.0}

        message = nse_scanner.format_alert(result, "supply", zone, 1.0)

        self.assertTrue(message.startswith("RELIANCE | SELL | 7/10"))

    def test_nse_thirty_minute_alert_displays_full_wick_score(self):
        result = {"symbol": "INDIGO.NS", "price": 100.0, "demand_score": 9}
        zone = {"bottom": 99.0, "top": 99.5}

        message = nse_scanner.format_alert(result, "demand", zone, 0.5)

        self.assertTrue(message.startswith("INDIGO | BUY | 9/10"))


if __name__ == "__main__":
    unittest.main()
