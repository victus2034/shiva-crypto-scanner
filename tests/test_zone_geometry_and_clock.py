"""The two v7 fixes ported into the scanner, plus the geometry switch.

Backtest behind these: ZONE_GEOMETRY_BACKTEST_FINDINGS.md.
"""
import unittest
from unittest.mock import patch

import pandas as pd

import scanner


def frame(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"]).assign(
        time=range(len(rows)), volume=1.0
    )


class TrimKeepsTheStrongZone(unittest.TestCase):
    """A full buffer must drop the weakest zone, not the oldest."""

    def zones(self, now):
        # index 0 is oldest and untouched for 500 bars - the strong one.
        # index 1 was touched last bar - the weak one.
        return [
            {"created_idx": 0, "clock": now - 500, "active": True, "id": "old_quiet"},
            {"created_idx": 400, "clock": now - 1, "active": True, "id": "new_busy"},
            {"created_idx": 450, "clock": now, "active": True, "id": "newest"},
        ]

    def test_weakest_first_keeps_the_old_untouched_zone(self):
        now = 600
        zones = self.zones(now)
        with patch.object(scanner, "HISTORY_OF_ZONES_TO_KEEP", 2), \
             patch.object(scanner, "ZONE_EVICT_WEAKEST", True):
            scanner.trim_zone_history(zones, now)
        kept = [z["id"] for z in zones]
        self.assertIn("old_quiet", kept, "the strongest zone was evicted")
        self.assertNotIn("new_busy", kept)

    def test_fifo_still_available_and_drops_the_oldest(self):
        now = 600
        zones = self.zones(now)
        with patch.object(scanner, "HISTORY_OF_ZONES_TO_KEEP", 2), \
             patch.object(scanner, "ZONE_EVICT_WEAKEST", False):
            scanner.trim_zone_history(zones, now)
        self.assertEqual([z["id"] for z in zones], ["new_busy", "newest"])

    def test_the_zone_just_created_is_never_the_victim(self):
        now = 600
        zones = self.zones(now)
        with patch.object(scanner, "HISTORY_OF_ZONES_TO_KEEP", 2), \
             patch.object(scanner, "ZONE_EVICT_WEAKEST", True):
            scanner.trim_zone_history(zones, now)
        self.assertIn("newest", [z["id"] for z in zones])

    def test_broken_zones_go_before_live_ones(self):
        now = 600
        zones = [
            {"created_idx": 0, "clock": now - 900, "active": False, "id": "dead"},
            {"created_idx": 10, "clock": now - 500, "active": True, "id": "live_quiet"},
            {"created_idx": 450, "clock": now, "active": True, "id": "newest"},
        ]
        with patch.object(scanner, "HISTORY_OF_ZONES_TO_KEEP", 2), \
             patch.object(scanner, "ZONE_EVICT_WEAKEST", True):
            scanner.trim_zone_history(zones, now)
        self.assertNotIn("dead", [z["id"] for z in zones])


class ClockRestartsOnTouch(unittest.TestCase):
    """MIN_ZONE_AGE_CANDLES should mean untouched, not merely old."""

    def zone(self):
        return {
            "bottom": 100.0, "top": 101.0, "active": True, "over_touched": False,
            "created_idx": 0, "clock": 0, "last_gap": None,
        }

    def test_old_but_constantly_touched_zone_is_too_young(self):
        z = self.zone()
        with patch.object(scanner, "MIN_ZONE_AGE_CANDLES", 15), \
             patch.object(scanner, "ZONE_CLOCK_RESTARTS_ON_TOUCH", True):
            for i in range(1, 60):                      # touched every bar
                scanner.record_zone_touch(z, 100.5, 100.2, i)
            self.assertTrue(scanner.too_young_to_alert(z, 60))

    def test_old_and_left_alone_zone_qualifies(self):
        z = self.zone()
        with patch.object(scanner, "MIN_ZONE_AGE_CANDLES", 15), \
             patch.object(scanner, "ZONE_CLOCK_RESTARTS_ON_TOUCH", True):
            scanner.record_zone_touch(z, 100.5, 100.2, 5)   # one touch early on
            for i in range(6, 60):                          # then silence
                scanner.record_zone_touch(z, 99.0, 98.0, i)
            self.assertFalse(scanner.too_young_to_alert(z, 60))

    def test_touch_now_is_judged_on_the_silence_it_earned_first(self):
        z = self.zone()
        with patch.object(scanner, "MIN_ZONE_AGE_CANDLES", 15), \
             patch.object(scanner, "ZONE_CLOCK_RESTARTS_ON_TOUCH", True):
            for i in range(1, 40):
                scanner.record_zone_touch(z, 99.0, 98.0, i)  # quiet for 39 bars
            scanner.record_zone_touch(z, 100.5, 100.2, 40)   # touching right now
            # A gap of zero must not disqualify it - it earned 40 quiet bars.
            self.assertFalse(scanner.too_young_to_alert(z, 40))

    def test_flag_off_restores_created_idx_behaviour(self):
        z = self.zone()
        with patch.object(scanner, "MIN_ZONE_AGE_CANDLES", 15), \
             patch.object(scanner, "ZONE_CLOCK_RESTARTS_ON_TOUCH", False):
            for i in range(1, 60):
                scanner.record_zone_touch(z, 100.5, 100.2, i)
            self.assertFalse(scanner.too_young_to_alert(z, 60))


class GeometrySwitch(unittest.TestCase):
    """wick geometry = [low, body bottom] for demand, mirrored for supply."""

    def build(self, geometry):
        rows = [(10.0, 10.2, 9.9, 10.1)] * 12
        # pivot low at index 12: a long lower wick under a green body
        rows.append((9.8, 9.9, 9.0, 9.85))
        rows += [(10.0, 10.2, 9.9, 10.1)] * 12
        df = frame(rows)
        atr_series = scanner.atr(df, 5)
        return scanner.qualify_wick_zone(df, 12, 22, atr_series, "demand", geometry)

    def test_wick_uses_the_body_edge_not_the_close(self):
        z = self.build("wick")
        self.assertAlmostEqual(z["bottom"], 9.0, places=6)
        # green candle: body bottom is the OPEN (9.8), not the close (9.85)
        self.assertLessEqual(z["top"], 9.85)
        self.assertAlmostEqual(z["top"], 9.8, places=6)

    def test_atr_geometry_is_unchanged(self):
        z = self.build("atr")
        self.assertAlmostEqual(z["bottom"], 9.0, places=6)
        self.assertGreater(z["top"], 9.0)
        self.assertEqual(z["geometry"], "atr")

    def test_wick_window_never_reaches_past_confirmation(self):
        rows = [(10.0, 10.2, 9.9, 10.1)] * 30
        df = frame(rows)
        atr_series = scanner.atr(df, 5)
        with patch.object(scanner, "ZONE_BASE_EXTRA", 50):
            z = scanner.qualify_wick_zone(df, 10, 12, atr_series, "demand", "wick")
        self.assertIsNotNone(z)


if __name__ == "__main__":
    unittest.main()


class ShadowNeverDelivers(unittest.TestCase):
    """The shadow stream must be incapable of sending a real alert."""

    def result(self):
        return {
            "symbol": "BTCUSD", "exchange": "delta", "price": 100.0,
            "supply_rating": None, "demand_rating": None,
            "supply_score": None, "demand_score": None,
        }

    def zone(self):
        return {
            "type": "demand", "top": 100.5, "bottom": 99.0, "body_entry": 100.5,
            "active": True, "over_touched": False, "created_idx": 0, "clock": 0,
            "last_gap": None, "atr": 1.0, "geometry": "wick",
            "wick_to_body": 1.0, "wick_atr": 1.0, "departure_atr": 1.0,
            "touch_count": 0,
        }

    def test_shadow_writes_its_own_log_and_never_calls_send_alert(self):
        import json, tempfile
        from pathlib import Path

        def explode(*_args, **_kwargs):
            raise AssertionError("shadow path reached send_alert")

        with tempfile.TemporaryDirectory() as tmp:
            shadow = Path(tmp) / "shadow.jsonl"
            live = Path(tmp) / "live.jsonl"
            with patch.object(scanner, "send_alert", explode), \
                 patch.object(scanner, "SHADOW_ALERT_RECORD_FILE", shadow), \
                 patch.object(scanner, "ALERT_RECORD_FILE", live), \
                 patch.object(scanner, "MIN_DISTANCE_PCT", 0.0), \
                 patch.object(scanner, "MAX_DISTANCE_PCT", 100.0), \
                 patch.object(scanner, "TIMEFRAME", "4h"):
                sent = scanner.process_candidate(
                    {}, self.result(), "demand", self.zone(), 0.5, 1.0, shadow=True
                )
            self.assertTrue(sent)
            self.assertTrue(shadow.exists(), "shadow record was not written")
            self.assertFalse(live.exists(), "shadow leaked into the live log")
            record = json.loads(shadow.read_text(encoding="utf-8").splitlines()[0])
            self.assertTrue(record["shadow"])
            self.assertEqual(record["geometry"], "wick")

    def test_shadow_state_cannot_suppress_a_live_alert(self):
        live_key = scanner.build_state_key("BTCUSD", "demand", self.zone())
        self.assertFalse(live_key.startswith("shadow:"))
