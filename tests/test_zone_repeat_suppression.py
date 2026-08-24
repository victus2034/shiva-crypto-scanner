import unittest
from unittest.mock import patch

import nse_scanner
import scanner


# Two consecutive deliveries of one BANKINDIA level, taken from the live
# alert records. Only the far decimals differ, because ATR moves a little
# with every new candle and the zone edge moves with it.
FIRST = {"bottom": 140.859, "top": 141.17203103477016}
SECOND = {"bottom": 140.859, "top": 141.17210107412592}
ELSEWHERE = {"bottom": 141.20, "top": 141.52}


class ZoneIdentityTests(unittest.TestCase):
    def test_a_redelivered_zone_keeps_its_identity(self):
        for module in (scanner, nse_scanner):
            with self.subTest(module=module.__name__):
                self.assertEqual(
                    module.exact_zone_identity("BANKINDIA.NS", "demand", FIRST),
                    module.exact_zone_identity("BANKINDIA.NS", "demand", SECOND),
                )

    def test_a_different_level_is_a_different_zone(self):
        for module in (scanner, nse_scanner):
            with self.subTest(module=module.__name__):
                self.assertNotEqual(
                    module.exact_zone_identity("BANKINDIA.NS", "demand", FIRST),
                    module.exact_zone_identity("BANKINDIA.NS", "demand", ELSEWHERE),
                )

    def test_supply_and_demand_at_one_level_stay_apart(self):
        for module in (scanner, nse_scanner):
            with self.subTest(module=module.__name__):
                self.assertNotEqual(
                    module.exact_zone_identity("BANKINDIA.NS", "demand", FIRST),
                    module.exact_zone_identity("BANKINDIA.NS", "supply", FIRST),
                )

    def test_a_thinly_priced_coin_keeps_its_resolution(self):
        near = {"bottom": 0.00276512, "top": 0.00281}
        apart = {"bottom": 0.00279512, "top": 0.00284}

        self.assertNotEqual(
            scanner.exact_zone_identity("ZILUSDT", "demand", near),
            scanner.exact_zone_identity("ZILUSDT", "demand", apart),
        )


class SuppressionWindowTests(unittest.TestCase):
    def test_a_repeat_inside_the_window_is_held_back(self):
        # The whole point: at ten decimals this never fired once, and the
        # same zone alerted every twenty minutes for hours.
        for module in (scanner, nse_scanner):
            with self.subTest(module=module.__name__):
                key = module.exact_zone_identity("BANKINDIA.NS", "demand", FIRST)
                noise_state = {key: 1000.0}
                window = module.ZONE_REPEAT_SUPPRESSION_SECONDS

                later_key = module.exact_zone_identity("BANKINDIA.NS", "demand", SECOND)
                last_success = noise_state.get(later_key, 0.0)
                twenty_minutes_later = 1000.0 + 20 * 60

                self.assertTrue(last_success)
                self.assertLess(twenty_minutes_later - last_success, window)


if __name__ == "__main__":
    unittest.main()
