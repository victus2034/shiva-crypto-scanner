import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
            "MSTR | BUY\n"
            "Price: 100.600000 | 0.40%\n"
            "Zone: 100.200000 - 100.336450\n"
            "SL: 100.099800 | 0.24%",
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
        # This fixture's 0.20% stop is genuinely too tight for the +0.5R
        # rule to clear costs, so the warning line belongs here.
        self.assertEqual(
            message,
            "PIDILITIND | SELL\n"
            "Price: 1610.90 | 0.97%\n"
            "Zone: 1624.95 - 1626.60\n"
            "SL: 1628.23 | 0.20%\n"
            "WARNING SL under 0.24% - at +0.5R the move is only 0.101%, "
            "under the 0.1063% round trip, so moving the stop up cannot "
            "protect capital here",
        )

    def test_a_workable_stop_distance_carries_no_warning(self):
        result = {
            "symbol": "PIDILITIND.NS",
            "price": 1610.9,
            "buy_signal": False,
            "sell_signal": False,
        }
        # A ~1% stop sits comfortably clear of the cost floor.
        zone = {"bottom": 1624.95, "top": 1641.20}

        message = nse_scanner.format_alert(result, "supply", zone, 0.97)

        self.assertNotIn("WARNING", message)

    def test_nse_zone_alert_adds_sector_bias_when_available(self):
        result = {
            "symbol": "INFY.NS",
            "price": 100.0,
            "sector": "Technology & Telecom",
            "sector_session_pct": -2.1,
        }
        zone = {"bottom": 99.0, "top": 99.5}

        message = nse_scanner.format_alert(result, "demand", zone, 0.6)

        self.assertEqual(
            message,
            "INFY | BUY\n"
            "Price: 100.00 | 0.60%\n"
            "Zone: 99.00 - 99.50\n"
            "SL: 98.90 | 0.60%\n"
            "Technology & Telecom: -2.10% | Risk",
        )

    def test_nse_sell_alert_sector_bias_supports_down_sector(self):
        result = {
            "symbol": "INFY.NS",
            "price": 100.0,
            "sector": "Technology & Telecom",
            "sector_session_pct": -2.1,
        }
        zone = {"bottom": 101.0, "top": 101.5}

        message = nse_scanner.format_alert(result, "supply", zone, 0.6)

        self.assertIn("Technology & Telecom: -2.10% | Good", message)

    def test_nse_30m_zone_rating_starts_at_four(self):
        result = {"symbol": "TEST.NS", "price": 100.0}
        zone = {"bottom": 99.0, "top": 99.5, "max_touch_streak": 1}
        nse_scanner.TIMEFRAME = "30m"
        nse_scanner.SHOW_ZONE_RATINGS = True
        nse_scanner.MAX_DISTANCE_PCT = 0.75

        message = nse_scanner.format_alert(result, "demand", zone, 0.70)

        self.assertIn("TEST | BUY | 4/10", message)

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

        self.assertTrue(message.startswith("BTC | BUY | 9/10"))
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

        self.assertTrue(message.startswith("NVDA | BUY | 8/10"))
        self.assertNotIn("5/10", message)
        self.assertEqual(message.count("/10"), 1)

    def test_xstock_hybrid_score_is_saved_to_alert_record(self):
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
        with tempfile.TemporaryDirectory() as tmp:
            record_path = Path(tmp) / "crypto_alert_records.jsonl"
            with patch.object(scanner, "ALERT_RECORD_FILE", record_path):
                scanner.record_delivered_zone_alert(
                    result,
                    "demand",
                    zone,
                    0.5,
                    "NVDAXUSD | BUY | 8/10",
                    1_785_000_000,
                )

            record = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual(record["score"], 8)

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


class SymbolNamingTests(unittest.TestCase):
    """Crypto and xStock alerts name the underlying, the way NSE alerts show
    RELIANCE rather than RELIANCE.NS, so the same instrument reads the same
    everywhere it appears.
    """

    def test_alert_names_match_the_nse_convention(self):
        for raw, expected in (
            ("SPYXUSD", "SPY"),
            ("AMZNXUSD", "AMZN"),
            ("MSFT/USDT", "MSFT"),
            ("TQQQUSDT", "TQQQ"),
            ("BTCUSDT", "BTC"),
            # Both end "BUSD", but these are BNB/ARB/LAB quoted in USD -
            # not BN/AR/LA quoted in BUSD.
            ("BNBUSD", "BNB"),
            ("ARBUSD", "ARB"),
            ("LABUSD", "LAB"),
            # These really are quoted in BUSD.
            ("MSTRBUSD", "MSTR"),
            ("SOXLBUSD", "SOXL"),
        ):
            self.assertEqual(scanner.alert_symbol(raw), expected)

    def test_alert_and_report_names_agree(self):
        # The Discord alert and the backtest report must not disagree about
        # what a symbol is called, or trades cannot be matched between them.
        for raw in ("SPYXUSD", "MSFT/USDT", "SLVONUSD", "BTCUSDT"):
            self.assertEqual(scanner.alert_symbol(raw), scanner.display_symbol(raw))
