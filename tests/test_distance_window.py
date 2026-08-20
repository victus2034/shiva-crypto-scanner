import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import nse_scanner
import scanner


class DistanceWindowTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp_path = Path(self._tmp.name)
        self._crypto_record_patch = patch.object(
            scanner, "ALERT_RECORD_FILE", tmp_path / "crypto_alert_records.jsonl"
        )
        self._nse_record_patch = patch.object(
            nse_scanner, "ALERT_RECORD_FILE", tmp_path / "nse_alert_records.jsonl"
        )
        self._crypto_record_patch.start()
        self._nse_record_patch.start()

    def tearDown(self):
        self._nse_record_patch.stop()
        self._crypto_record_patch.stop()
        self._tmp.cleanup()

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

    def test_crypto_range_signal_requires_a_nearby_directional_zone(self):
        state = {}
        result = {
            "symbol": "OPENAIUSDT",
            "price": 111.51,
            "demand": {"bottom": 109.0, "top": 109.2},
            "demand_dist": 2.01,
            "supply": None,
            "supply_dist": 999.0,
            "buy_signal": True,
            "sell_signal": False,
        }

        with patch.object(scanner, "send_alert", return_value=True) as send:
            sent = scanner.process_signal_candidate(state, result, "buy", 20000)

        self.assertFalse(sent)
        send.assert_not_called()

    def test_crypto_range_signal_can_confirm_a_nearby_directional_zone(self):
        state = {}
        result = {
            "symbol": "BTCUSDT",
            "price": 100.0,
            "demand": {"bottom": 99.0, "top": 99.5},
            "demand_dist": 0.15,
            "supply": None,
            "supply_dist": 999.0,
            "buy_signal": True,
            "sell_signal": False,
        }

        with patch.object(scanner, "send_alert", return_value=True) as send:
            sent = scanner.process_signal_candidate(state, result, "buy", 20000)

        self.assertTrue(sent)
        send.assert_called_once()

    def test_crypto_30m_range_signal_rating_below_six_is_blocked(self):
        state = {}
        result = {
            "symbol": "BTCUSDT",
            "price": 100.0,
            "demand": {"bottom": 99.0, "top": 99.5},
            "demand_dist": 0.15,
            "supply": None,
            "supply_dist": 999.0,
            "demand_rating": {"score": 5},
            "buy_signal": True,
            "sell_signal": False,
        }

        with (
            patch.object(scanner, "TIMEFRAME", "30m"),
            patch.object(scanner, "send_alert", return_value=True) as send,
        ):
            sent = scanner.process_signal_candidate(state, result, "buy", 20000)

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
            sent = scanner.process_candidate(state, result, "demand", zone, 0.15, 1000)

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
            sent = scanner.process_candidate(state, result, "demand", zone, 0.15, 1000)

        self.assertTrue(sent)
        send.assert_called_once()

    def test_xstock_hybrid_zone_is_blocked_outside_us_session(self):
        state = {}
        result = {
            "symbol": "NVDAXUSD",
            "price": 190.0,
            "demand_rating": {
                "kind": "xstock_hybrid",
                "score": 9,
                "minimum_score": 5,
                "alert_allowed": False,
            },
        }
        zone = {"bottom": 188.0, "top": 188.5}

        with patch.object(scanner, "send_alert", return_value=True) as send:
            sent = scanner.process_candidate(
                state,
                result,
                "demand",
                zone,
                0.15,
                1000,
            )

        self.assertFalse(sent)
        send.assert_not_called()

    def test_xstock_hybrid_zone_is_allowed_when_rating_passes(self):
        state = {}
        result = {
            "symbol": "NVDAXUSD",
            "price": 190.0,
            "demand_rating": {
                "kind": "xstock_hybrid",
                "score": 8,
                "minimum_score": 5,
                "alert_allowed": True,
            },
        }
        zone = {"bottom": 188.0, "top": 188.5}

        with patch.object(scanner, "send_alert", return_value=True) as send:
            sent = scanner.process_candidate(
                state,
                result,
                "demand",
                zone,
                0.15,
                1000,
            )

        self.assertTrue(sent)
        send.assert_called_once()

    def test_xstock_range_signal_respects_hybrid_gate(self):
        state = {}
        result = {
            "symbol": "NVDAXUSD",
            "price": 190.0,
            "demand": {"bottom": 188.0, "top": 188.5},
            "demand_dist": 0.15,
            "supply": None,
            "supply_dist": 999.0,
            "demand_rating": {
                "kind": "xstock_hybrid",
                "score": 9,
                "minimum_score": 5,
                "alert_allowed": False,
            },
            "buy_signal": True,
            "sell_signal": False,
        }

        with patch.object(scanner, "send_alert", return_value=True) as send:
            sent = scanner.process_signal_candidate(
                state,
                result,
                "buy",
                20000,
            )

        self.assertFalse(sent)
        send.assert_not_called()

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
            "demand_dist": 0.15,
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

        with TemporaryDirectory() as tmp:
            record_path = Path(tmp) / "nse_alert_records.jsonl"
            with (
                patch.object(nse_scanner, "ALERT_RECORD_FILE", record_path),
                patch.object(nse_scanner, "MIN_DISTANCE_PCT", 0.25),
                patch.object(nse_scanner, "MAX_DISTANCE_PCT", 0.75),
                patch.object(nse_scanner, "send_alert", return_value=True) as send,
            ):
                nse_scanner.process_candidate(state, result, "demand", zone, 0.20, 1000)
                nse_scanner.process_candidate(state, result, "demand", zone, 0.50, 1100)

        self.assertEqual(send.call_count, 1)

    def test_crypto_successful_zone_suppression_survives_touch(self):
        state = {}
        result = {"symbol": "BTCUSD", "price": 100.0}
        zone = {"bottom": 99.0, "top": 100.0}

        with (
            patch.object(scanner, "MIN_DISTANCE_PCT", 0.25),
            patch.object(scanner, "MAX_DISTANCE_PCT", 0.75),
            patch.object(scanner, "send_alert", return_value=True) as send,
        ):
            self.assertTrue(scanner.process_candidate(state, result, "demand", zone, 0.50, 1000))
            scanner.process_candidate(state, result, "demand", zone, 0.0, 1100)
            self.assertFalse(scanner.process_candidate(state, result, "demand", zone, 0.50, 2000))

        self.assertEqual(send.call_count, 1)

    def test_nse_successful_zone_suppression_survives_touch(self):
        state = {}
        result = {"symbol": "RELIANCE.NS", "price": 100.0}
        zone = {"bottom": 99.0, "top": 100.0}

        with (
            patch.object(nse_scanner, "MIN_DISTANCE_PCT", 0.25),
            patch.object(nse_scanner, "MAX_DISTANCE_PCT", 0.75),
            patch.object(nse_scanner, "send_alert", return_value=True) as send,
        ):
            self.assertTrue(nse_scanner.process_candidate(state, result, "demand", zone, 0.50, 1000))
            nse_scanner.process_candidate(state, result, "demand", zone, 0.0, 1100)
            self.assertFalse(nse_scanner.process_candidate(state, result, "demand", zone, 0.50, 2000))

        self.assertEqual(send.call_count, 1)


if __name__ == "__main__":
    unittest.main()


class DistanceIsMeasuredToTheEntryEdgeTests(unittest.TestCase):
    """Distance must be measured to the edge price reaches first - the one
    the trade is entered at. Measuring to the far edge put a whole zone
    height between the trigger and the fill, so alerts could arrive with
    price already through the entry.
    """

    def test_demand_distance_is_measured_to_the_zone_top(self):
        # Price 100.30 approaching a demand zone from above. Entry is the
        # top (100.00); the far edge (99.00) is a further 1% away.
        zone = {"bottom": 99.0, "top": 100.0, "active": True}
        _, distance = scanner.nearest_active_zone(100.30, [zone], "demand")
        self.assertAlmostEqual(distance, 0.299, places=2)

    def test_supply_distance_is_measured_to_the_zone_bottom(self):
        # Price 99.70 approaching a supply zone from below. Entry is the
        # bottom (100.00); the top (101.00) is further away.
        zone = {"bottom": 100.0, "top": 101.0, "active": True}
        _, distance = scanner.nearest_active_zone(99.70, [zone], "supply")
        self.assertAlmostEqual(distance, 0.301, places=2)
