import unittest
from unittest.mock import patch

import nse_scanner
import scanner


class DistanceWindowTests(unittest.TestCase):
    def test_crypto_range_signal_requires_an_active_zone(self):
        state = {}
        result = {
            "symbol": "EWYBUSD",
            "price": 161.1,
            "demand": None,
            "supply": None,
            "buy_signal": True,
            "sell_signal": False,
        }

        with patch.object(scanner, "send_alert", return_value=True) as send:
            sent = scanner.process_signal_candidate(state, result, "buy", 1000)

        self.assertFalse(sent)
        send.assert_not_called()

    def test_crypto_30m_zone_rating_below_six_is_blocked(self):
        state = {}
        result = {
            "symbol": "BTCUSD",
            "price": 100.0,
            "demand_rating": {"score": 5},
        }
        zone = {"bottom": 99.0, "top": 99.5}

        with (
            patch.object(scanner, "TIMEFRAME", "30m"),
            patch.object(scanner, "send_alert", return_value=True) as send,
        ):
            sent = scanner.process_candidate(state, result, "demand", zone, 0.5, 1000)

        self.assertFalse(sent)
        send.assert_not_called()

    def test_crypto_30m_zone_rating_six_or_higher_is_allowed(self):
        state = {}
        result = {
            "symbol": "BTCUSD",
            "price": 100.0,
            "demand_rating": {"score": 6},
        }
        zone = {"bottom": 99.0, "top": 99.5}

        with (
            patch.object(scanner, "TIMEFRAME", "30m"),
            patch.object(scanner, "send_alert", return_value=True) as send,
        ):
            sent = scanner.process_candidate(state, result, "demand", zone, 0.5, 1000)

        self.assertTrue(sent)
        send.assert_called_once()

    def test_nse_range_signal_requires_an_active_zone(self):
        state = {}
        result = {
            "symbol": "EWYBUSD",
            "price": 161.1,
            "demand": None,
            "supply": None,
            "buy_signal": True,
            "sell_signal": False,
        }

        with patch.object(nse_scanner, "send_alert", return_value=True) as send:
            sent = nse_scanner.process_signal_candidate(state, result, "buy", 1000)

        self.assertIsNone(sent)
        send.assert_not_called()

    def test_nse_range_signal_requires_a_nearby_directional_zone(self):
        state = {}
        result = {
            "symbol": "INFY.NS",
            "price": 1111.9,
            "demand": {"bottom": 900.0, "top": 901.0},
            "demand_dist": 15.77,
            "supply": None,
            "supply_dist": 999.0,
            "buy_signal": True,
            "sell_signal": False,
        }

        with patch.object(nse_scanner, "send_alert", return_value=True) as send:
            sent = nse_scanner.process_signal_candidate(state, result, "buy", 20000)

        self.assertIsNone(sent)
        send.assert_not_called()

    def test_nse_range_signal_can_confirm_a_nearby_directional_zone(self):
        state = {}
        result = {
            "symbol": "RELIANCE.NS",
            "price": 100.0,
            "demand": {"bottom": 99.0, "top": 99.5},
            "demand_dist": 0.5,
            "supply": None,
            "supply_dist": 999.0,
            "buy_signal": True,
            "sell_signal": False,
        }

        with patch.object(nse_scanner, "send_alert", return_value=True) as send:
            sent = nse_scanner.process_signal_candidate(state, result, "buy", 20000)

        self.assertTrue(sent)
        send.assert_called_once()

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
