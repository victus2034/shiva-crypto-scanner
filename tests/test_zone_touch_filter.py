import unittest
from unittest.mock import patch

import nse_scanner
import scanner


class ZoneTouchFilterTests(unittest.TestCase):
    def test_two_consecutive_touches_mark_zone_as_over_tested(self):
        for module in (scanner, nse_scanner):
            with self.subTest(module=module.__name__):
                zone = {"bottom": 100.0, "top": 101.0, "active": True}
                with patch.object(module, "MAX_CONSECUTIVE_ZONE_TOUCHES", 2):
                    module.record_zone_touch(zone, 101.5, 100.5)
                    self.assertFalse(zone.get("over_touched", False))
                    module.record_zone_touch(zone, 100.8, 99.8)

                self.assertTrue(zone["over_touched"])
                self.assertEqual(zone["max_touch_streak"], 2)

    def test_candle_away_resets_consecutive_touch_streak(self):
        for module in (scanner, nse_scanner):
            with self.subTest(module=module.__name__):
                zone = {"bottom": 100.0, "top": 101.0, "active": True}
                with patch.object(module, "MAX_CONSECUTIVE_ZONE_TOUCHES", 2):
                    module.record_zone_touch(zone, 101.5, 100.5)
                    module.record_zone_touch(zone, 103.0, 102.0)
                    module.record_zone_touch(zone, 100.8, 99.8)

                self.assertFalse(zone.get("over_touched", False))
                self.assertEqual(zone["touch_streak"], 1)

    def test_nearest_zone_ignores_over_tested_level(self):
        zones = [
            {"bottom": 99.0, "top": 100.0, "active": True, "over_touched": True},
            {"bottom": 95.0, "top": 96.0, "active": True, "over_touched": False},
        ]

        for module in (scanner, nse_scanner):
            with self.subTest(module=module.__name__):
                zone, _ = module.nearest_active_zone(101.0, zones, "demand")
                self.assertIs(zone, zones[1])


if __name__ == "__main__":
    unittest.main()
