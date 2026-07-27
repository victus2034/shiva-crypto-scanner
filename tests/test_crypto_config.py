import os
import unittest
from unittest.mock import patch


class CryptoConfigTests(unittest.TestCase):
    def test_four_hour_default_distance_is_1_25_percent(self):
        with patch.dict(os.environ, {"SHIVA_TIMEFRAME": "4h"}, clear=True):
            import config

            self.assertEqual(config.MIN_DISTANCE_PCT, 0.25)
            self.assertEqual(config.MAX_DISTANCE_PCT, 1.25)


if __name__ == "__main__":
    unittest.main()
