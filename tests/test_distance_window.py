import unittest
from unittest.mock import patch

import nse_scanner
import scanner


class DistanceWindowTests(unittest.TestCase):
    def test_crypto_ignores_too_close_zone_and_accepts_window(self):
        state = {}
        result = {"symbol": "BTCUSD", "price": 100.0}
        zone = {"bottom": 99.0, "top": 100.0}

        with (
            patch.object(scanner, "MIN_DISTANCE_PCT", 0.25),
            patch.object(scanner, "MAX_DISTANCE_PCT", 0.75),
            patch.object(scanner, "send_alert", return_value=True) as send,
        ):
            scanner.process_candidate(state, result, "demand", zone, 0.20, 1000)
            scanner.process_candidate(state, result, "demand", zone, 0.50, 1100)

        self.assertEqual(send.call_count, 1)

    def test_nse_ignores_too_close_zone_and_accepts_window(self):
        state = {}
        result = {"symbol": "RELIANCE.NS", "price": 100.0}
        zone = {"bottom": 99.0, "top": 100.0}

        with (
            patch.object(nse_scanner, "MIN_DISTANCE_PCT", 0.25),
            patch.object(nse_scanner, "MAX_DISTANCE_PCT", 0.75),
            patch.object(nse_scanner, "send_alert", return_value=True) as send,
        ):
            nse_scanner.process_candidate(state, result, "demand", zone, 0.20, 1000)
            nse_scanner.process_candidate(state, result, "demand", zone, 0.50, 1100)

        self.assertEqual(send.call_count, 1)


if __name__ == "__main__":
    unittest.main()
