import unittest
from unittest.mock import patch

import nse_scanner
import scanner


def zone(created_idx, bottom, top):
    return {
        "bottom": bottom,
        "top": top,
        "active": True,
        "over_touched": False,
        "created_idx": created_idx,
    }


class ZoneAgeFilterTests(unittest.TestCase):
    def test_zone_confirmed_moments_ago_raises_no_alert(self):
        # The COAI supply zone that prompted this rule: confirmed on the
        # candle before the alert, with price already sitting on it. Nothing
        # had been defended there - it was just the recent high.
        fresh = zone(created_idx=200, bottom=0.2862, top=0.2879)

        for module in (scanner, nse_scanner):
            with self.subTest(module=module.__name__):
                with patch.object(module, "MIN_ZONE_AGE_CANDLES", 15):
                    found, _ = module.nearest_active_zone(
                        0.2863, [fresh], "supply", 201
                    )

                self.assertIsNone(found)

    def test_zone_that_has_stood_long_enough_still_alerts(self):
        held = zone(created_idx=200, bottom=0.2862, top=0.2879)

        for module in (scanner, nse_scanner):
            with self.subTest(module=module.__name__):
                with patch.object(module, "MIN_ZONE_AGE_CANDLES", 15):
                    found, _ = module.nearest_active_zone(
                        0.2863, [held], "supply", 215
                    )

                self.assertIs(found, held)

    def test_a_young_zone_does_not_hide_an_older_one_behind_it(self):
        zones = [
            zone(created_idx=214, bottom=99.0, top=100.0),
            zone(created_idx=100, bottom=95.0, top=96.0),
        ]

        for module in (scanner, nse_scanner):
            with self.subTest(module=module.__name__):
                with patch.object(module, "MIN_ZONE_AGE_CANDLES", 15):
                    found, _ = module.nearest_active_zone(
                        101.0, zones, "demand", 215
                    )

                self.assertIs(found, zones[1])

    def test_the_rule_can_be_switched_off(self):
        fresh = zone(created_idx=200, bottom=99.0, top=100.0)

        for module in (scanner, nse_scanner):
            with self.subTest(module=module.__name__):
                with patch.object(module, "MIN_ZONE_AGE_CANDLES", 0):
                    found, _ = module.nearest_active_zone(
                        101.0, [fresh], "demand", 201
                    )

                self.assertIs(found, fresh)

    def test_callers_without_a_bar_index_are_unaffected(self):
        # Backtest and rating paths call this without a position in the
        # frame; they must not silently lose every zone.
        fresh = zone(created_idx=200, bottom=99.0, top=100.0)

        for module in (scanner, nse_scanner):
            with self.subTest(module=module.__name__):
                with patch.object(module, "MIN_ZONE_AGE_CANDLES", 15):
                    found, _ = module.nearest_active_zone(101.0, [fresh], "demand")

                self.assertIs(found, fresh)


if __name__ == "__main__":
    unittest.main()
