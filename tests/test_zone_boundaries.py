import unittest

import pandas as pd

import nse_scanner
import scanner


def build(module, frame, pivot, confirmation, atr_values, zone_type):
    """Ask for the atr band by name.

    Until 2026-09-06 it was the only construction and the default. Crypto now
    defaults to the wick geometry (ZONE_GEOMETRY in config.py), so these tests
    have to name the band rather than assume it. nse_scanner has no switch and
    still only builds the band.
    """
    if module is scanner:
        return module.qualify_wick_zone(
            frame, pivot, confirmation, atr_values, zone_type, "atr"
        )
    return module.qualify_wick_zone(frame, pivot, confirmation, atr_values, zone_type)


class IndicatorBoundaryTests(unittest.TestCase):
    """The atr band: a fixed atr * (BOX_WIDTH / 10) hung off the pivot extreme.

    Still what NSE runs and still selectable on crypto, so still pinned. The
    wick construction that crypto now defaults to has its own coverage in
    test_zone_geometry_and_clock.py.
    """

    def frame(self):
        return pd.DataFrame(
            {
                "open": [10.0, 10.0, 10.0, 11.0, 11.0],
                "close": [9.8, 9.8, 9.8, 12.0, 12.0],
                "high": [10.1, 10.1, 10.1, 12.1, 12.1],
                "low": [9.0, 9.0, 9.0, 10.5, 10.5],
            }
        )

    def test_demand_band_sits_above_the_pivot_low(self):
        atr_values = pd.Series([2.0] * 5)
        for module in (scanner, nse_scanner):
            band = 2.0 * (module.BOX_WIDTH / 10.0)
            zone = build(module, self.frame(), 2, 3, atr_values, "demand")
            self.assertEqual(zone["bottom"], 9.0)  # the pivot low itself
            self.assertAlmostEqual(zone["top"], 9.0 + band)
            # Price reaches a demand zone from above, so the top is the entry.
            self.assertAlmostEqual(zone["body_entry"], zone["top"])

    def test_supply_band_sits_below_the_pivot_high(self):
        atr_values = pd.Series([2.0] * 5)
        for module in (scanner, nse_scanner):
            band = 2.0 * (module.BOX_WIDTH / 10.0)
            zone = build(module, self.frame(), 2, 3, atr_values, "supply")
            self.assertEqual(zone["top"], 10.1)  # the pivot high itself
            self.assertAlmostEqual(zone["bottom"], 10.1 - band)
            # Price reaches a supply zone from below, so the bottom is entry.
            self.assertAlmostEqual(zone["body_entry"], zone["bottom"])

    def test_band_scales_with_atr_not_with_the_candle(self):
        for module in (scanner, nse_scanner):
            wide = build(module, self.frame(), 2, 3, pd.Series([4.0] * 5), "demand")
            narrow = build(module, self.frame(), 2, 3, pd.Series([1.0] * 5), "demand")
            self.assertAlmostEqual(
                wide["top"] - wide["bottom"], 4.0 * (module.BOX_WIDTH / 10.0)
            )
            self.assertAlmostEqual(
                narrow["top"] - narrow["bottom"], 1.0 * (module.BOX_WIDTH / 10.0)
            )


class NoQualificationFilterTests(unittest.TestCase):
    """The indicator draws a zone at every confirmed pivot, with no wick,
    body-ratio or departure test. Re-adding such filters silently drops
    levels the chart still shows.
    """

    def test_a_wick_free_marubozu_pivot_still_builds_a_zone(self):
        # Body only, effectively no lower wick, and barely any departure -
        # the old filters rejected all three of these.
        data = pd.DataFrame(
            {
                "open": [10.0, 10.0, 9.0, 9.1, 9.1],
                "close": [9.8, 9.8, 10.0, 9.15, 9.15],
                "high": [10.1, 10.1, 10.0, 9.2, 9.2],
                "low": [9.0, 9.0, 9.0, 9.05, 9.05],
            }
        )
        atr_values = pd.Series([2.0] * 5)
        for module in (scanner, nse_scanner):
            zone = module.qualify_wick_zone(data, 2, 3, atr_values, "demand")
            self.assertIsNotNone(zone)

    def test_back_to_back_touches_retire_the_zone(self):
        # Consecutive candles sitting on a level mean price is grinding
        # through it rather than reacting to it - thin volume, no rejection.
        # Deliberately stricter than the indicator, which has no touch veto.
        for module in (scanner, nse_scanner):
            self.assertEqual(module.MAX_CONSECUTIVE_ZONE_TOUCHES, 2)
            zone = {"top": 10.0, "bottom": 9.0, "touch_streak": 0,
                    "touch_count": 0, "max_touch_streak": 0, "over_touched": False}
            module.record_zone_touch(zone, 9.9, 9.1)
            self.assertFalse(zone["over_touched"], "one touch is a normal test")
            module.record_zone_touch(zone, 9.9, 9.1)
            self.assertTrue(zone["over_touched"], "back-to-back retires it")

    def test_a_single_touch_with_a_gap_does_not_retire_the_zone(self):
        # Touch, move away, touch again later: that is a level being
        # respected, not ground through, so the streak resets.
        for module in (scanner, nse_scanner):
            zone = {"top": 10.0, "bottom": 9.0, "touch_streak": 0,
                    "touch_count": 0, "max_touch_streak": 0, "over_touched": False}
            module.record_zone_touch(zone, 9.9, 9.1)   # touch
            module.record_zone_touch(zone, 12.0, 11.0)  # away, streak resets
            module.record_zone_touch(zone, 9.9, 9.1)   # touch again
            self.assertEqual(zone["touch_count"], 2)
            self.assertFalse(zone["over_touched"])


if __name__ == "__main__":
    unittest.main()
