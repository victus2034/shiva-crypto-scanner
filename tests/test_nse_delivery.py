import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pandas as pd
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
            "demand": {"bottom": 99.0, "top": 99.5},
            "supply": None,
            "buy_signal": True,
            "sell_signal": False,
            "demand_dist": 0.5,
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


class TightStopWarningTests(unittest.TestCase):
    """Reaching +0.5R only moves price half the stop distance. When that is
    smaller than the round-trip charges, moving the stop up at +0.5R still
    locks in a loss, so the capital-protection rule cannot work at all.
    """

    def test_threshold_is_twice_the_break_even_cushion(self):
        self.assertTrue(nse_scanner.stop_is_too_tight(0.20))
        self.assertTrue(nse_scanner.stop_is_too_tight(0.23))
        self.assertFalse(nse_scanner.stop_is_too_tight(0.24))
        self.assertFalse(nse_scanner.stop_is_too_tight(1.01))

    def _alert_for(self, bottom, top):
        result = {"symbol": "TCS.NS", "price": float(top) * 1.004}
        zone = {"bottom": float(bottom), "top": float(top)}
        return nse_scanner.format_alert(result, "demand", zone, 0.5)

    def test_a_tight_stop_alert_carries_the_warning(self):
        # top 100 / bottom 99.9 -> stop 99.80, about 0.20% away.
        message = self._alert_for(99.9, 100.0)
        self.assertIn("WARNING", message)
        self.assertIn("cannot protect capital", message)

    def test_a_workable_stop_alert_is_left_alone(self):
        # top 100 / bottom 99 -> stop 98.90, about 1.10% away.
        message = self._alert_for(99.0, 100.0)
        self.assertNotIn("WARNING", message)


class SessionDataFreshnessTests(unittest.TestCase):
    """has_current_session_data() must not blank the whole scan over one
    missing symbol - a delisted ticker or a transient fetch hiccup for a
    single name previously suppressed alerts for every other symbol too.
    """

    def _frame(self, day_offset):
        now = pd.Timestamp.now(tz=ZoneInfo(nse_scanner.MARKET_TIMEZONE))
        ts = now - pd.Timedelta(days=day_offset)
        return pd.DataFrame({"Datetime": [ts], "close": [100.0]})

    def test_one_missing_symbol_does_not_block_the_scan(self):
        now = pd.Timestamp.now(tz=ZoneInfo(nse_scanner.MARKET_TIMEZONE))
        with patch.object(nse_scanner, "MARKET_DATA", {
            f"SYM{i}": self._frame(0) for i in range(99)
        }):
            watchlist = [f"SYM{i}" for i in range(100)]  # SYM99 has no data at all
            self.assertTrue(nse_scanner.has_current_session_data(watchlist, now))

    def test_majority_stale_data_still_blocks_the_scan(self):
        now = pd.Timestamp.now(tz=ZoneInfo(nse_scanner.MARKET_TIMEZONE))
        data = {f"SYM{i}": self._frame(1) for i in range(90)}
        data.update({f"SYM{i}": self._frame(0) for i in range(90, 100)})
        with patch.object(nse_scanner, "MARKET_DATA", data):
            watchlist = [f"SYM{i}" for i in range(100)]
            self.assertFalse(nse_scanner.has_current_session_data(watchlist, now))

    def test_no_data_at_all_blocks_the_scan(self):
        now = pd.Timestamp.now(tz=ZoneInfo(nse_scanner.MARKET_TIMEZONE))
        with patch.object(nse_scanner, "MARKET_DATA", {}):
            self.assertFalse(nse_scanner.has_current_session_data(["SYM0"], now))


if __name__ == "__main__":
    unittest.main()
