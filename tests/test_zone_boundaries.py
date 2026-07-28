import unittest

import pandas as pd

import nse_scanner
import scanner


class RawWickBoundaryTests(unittest.TestCase):
    def test_crypto_and_nse_use_raw_wick_boundaries_by_default(self):
        data = pd.DataFrame(
            {
                "open": [10.0, 10.0, 10.0, 11.0, 11.0],
                "close": [9.8, 9.8, 9.8, 12.0, 12.0],
                "high": [10.1, 10.1, 10.1, 12.1, 12.1],
                "low": [9.0, 9.0, 9.0, 10.5, 10.5],
            }
        )
        atr_values = pd.Series([2.0] * len(data))

        for module in (scanner, nse_scanner):
            self.assertEqual(module.ZONE_PADDING_ATR, 0.0)
            zone = module.qualify_wick_zone(data, 2, 3, atr_values, "demand")
            self.assertEqual(zone["bottom"], 9.0)
            self.assertEqual(zone["top"], 9.8)


if __name__ == "__main__":
    unittest.main()
