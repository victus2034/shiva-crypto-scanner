import unittest
from unittest.mock import Mock, patch

import requests

import nse_scanner


class NseDeliveryTests(unittest.TestCase):
    def test_discord_rate_limit_is_retried(self):
        limited = Mock(status_code=429)
        limited.json.return_value = {"retry_after": 0.25}
        success = Mock(status_code=204)

        with (
            patch.object(nse_scanner, "get_env_or_config", return_value="https://example.test/webhook"),
            patch.object(nse_scanner.requests, "post", side_effect=[limited, success]) as post,
            patch.object(nse_scanner.time, "sleep") as sleep,
        ):
            nse_scanner.send_discord_message("test")

        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(0.25)
        success.raise_for_status.assert_called_once()

    def test_failed_alert_is_not_copied_to_status_webhook(self):
        with patch.object(
            nse_scanner,
            "send_discord_message",
            side_effect=requests.HTTPError("429 Too Many Requests"),
        ) as send:
            sent = nse_scanner.send_alert("RELIANCE.NS test alert")

        self.assertFalse(sent)
        self.assertEqual(send.call_count, 1)

    def test_failed_zone_alert_is_not_retried_before_cooldown(self):
        state = {}
        result = {
            "symbol": "RELIANCE.NS",
            "price": 100.4,
            "buy_signal": False,
            "sell_signal": False,
        }
        zone = {"bottom": 100.0, "top": 100.2}

        with (
            patch.object(nse_scanner, "MAX_DISTANCE_PCT", 0.5),
            patch.object(nse_scanner, "ALERT_COOLDOWN_SECONDS", 1200),
            patch.object(nse_scanner, "send_alert", return_value=False) as send,
        ):
            nse_scanner.process_candidate(state, result, "demand", zone, 0.4, 1000)
            nse_scanner.process_candidate(state, result, "demand", zone, 0.4, 1100)

        self.assertEqual(send.call_count, 1)

    def test_failed_signal_alert_is_not_retried_before_cooldown(self):
        state = {}
        result = {
            "symbol": "RELIANCE.NS",
            "price": 100.4,
            "buy_signal": True,
            "sell_signal": False,
            "demand_dist": 1.0,
            "supply_dist": 2.0,
        }

        with (
            patch.object(nse_scanner, "ALERT_RANGE_FILTER_SIGNALS", True),
            patch.object(nse_scanner, "SIGNAL_ALERT_COOLDOWN_SECONDS", 1200),
            patch.object(nse_scanner, "send_alert", return_value=False) as send,
        ):
            nse_scanner.process_signal_candidate(state, result, "buy", 2000)
            nse_scanner.process_signal_candidate(state, result, "buy", 2100)

        self.assertEqual(send.call_count, 1)


if __name__ == "__main__":
    unittest.main()
