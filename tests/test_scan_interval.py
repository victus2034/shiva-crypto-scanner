import time
import unittest
from unittest.mock import patch

import nse_scanner
import scanner


class ScanIntervalTests(unittest.TestCase):
    """Every workflow fires twice - repo cron and an external scheduler."""

    def test_a_second_scan_moments_later_stands_down(self):
        for module in (scanner, nse_scanner):
            with self.subTest(module=module.__name__):
                state = {}
                with patch.object(module, "MIN_SCAN_INTERVAL_SECONDS", 480):
                    self.assertFalse(module.scan_too_soon(state))
                    module.mark_scan_started(state)
                    self.assertTrue(module.scan_too_soon(state))

    def test_the_next_real_scan_still_runs(self):
        for module in (scanner, nse_scanner):
            with self.subTest(module=module.__name__):
                state = {}
                with patch.object(module, "MIN_SCAN_INTERVAL_SECONDS", 480):
                    module.mark_scan_started(state)
                    self.assertFalse(module.scan_too_soon(state, time.time() + 9 * 60))

    def test_timeframes_do_not_block_each_other(self):
        # 30m and 4h are separate schedules that happen to share a state file.
        for module in (scanner, nse_scanner):
            with self.subTest(module=module.__name__):
                state = {}
                with patch.object(module, "MIN_SCAN_INTERVAL_SECONDS", 480):
                    with patch.object(module, "TIMEFRAME", "30m"):
                        module.mark_scan_started(state)
                    with patch.object(module, "TIMEFRAME", "4h"):
                        self.assertFalse(module.scan_too_soon(state))

    def test_the_guard_can_be_switched_off(self):
        for module in (scanner, nse_scanner):
            with self.subTest(module=module.__name__):
                state = {}
                with patch.object(module, "MIN_SCAN_INTERVAL_SECONDS", 0):
                    module.mark_scan_started(state)
                    self.assertFalse(module.scan_too_soon(state))

    def test_a_clock_that_jumped_backwards_does_not_wedge_the_scan(self):
        for module in (scanner, nse_scanner):
            with self.subTest(module=module.__name__):
                state = {}
                with patch.object(module, "MIN_SCAN_INTERVAL_SECONDS", 480):
                    module.mark_scan_started(state, time.time() + 3600)
                    self.assertFalse(module.scan_too_soon(state))


if __name__ == "__main__":
    unittest.main()
