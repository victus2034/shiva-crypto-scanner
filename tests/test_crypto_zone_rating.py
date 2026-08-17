import unittest

import numpy as np
import pandas as pd

import crypto_zone_rating


def candle_frame(count=500):
    close = 100.0 + np.sin(np.arange(count) / 8.0) * 4.0
    return pd.DataFrame(
        {
            "time": pd.date_range(
                "2026-01-01",
                periods=count,
                freq="30min",
                tz="UTC",
            ).astype("int64")
            // 1_000_000,
            "open": close - 0.2,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1000.0 + np.arange(count),
        }
    )


class CryptoZoneRatingTests(unittest.TestCase):
    def test_rating_is_crypto_30m_only(self):
        self.assertTrue(
            crypto_zone_rating.is_rating_eligible("BTCUSD", "30m")
        )
        self.assertFalse(
            crypto_zone_rating.is_rating_eligible("BTCUSD", "4h")
        )
        self.assertFalse(
            crypto_zone_rating.is_rating_eligible("MSTRBUSD", "30m")
        )
        self.assertFalse(
            crypto_zone_rating.is_rating_eligible("HYPEUSD", "30m")
        )

    def test_rating_requires_validated_model_coverage(self):
        self.assertTrue(
            crypto_zone_rating.is_rating_eligible("BTCUSD", "30m")
        )
        self.assertFalse(
            crypto_zone_rating.is_rating_eligible("CBRSBUSD", "30m")
        )

    def test_feature_builder_matches_model_schema(self):
        frame = candle_frame()
        zone = {
            "created_idx": 450,
            "top": 99.0,
            "bottom": 98.5,
            "atr": 2.0,
            "touch_count": 1,
            "max_touch_streak": 1,
        }
        features = crypto_zone_rating.build_rating_features(
            frame,
            "demand",
            zone,
            0.4,
        )
        bundle = crypto_zone_rating.load_rating_bundle()
        self.assertEqual(
            set(features),
            set(bundle["feature_columns"]),
        )
        self.assertTrue(crypto_zone_rating.rated_crypto_symbols())

    def test_model_returns_a_known_rating(self):
        frame = candle_frame()
        zone = {
            "created_idx": 450,
            "top": 99.0,
            "bottom": 98.5,
            "atr": 2.0,
            "touch_count": 1,
            "max_touch_streak": 1,
        }
        result = crypto_zone_rating.rate_crypto_zone(
            frame,
            "BTCUSD",
            "30m",
            "demand",
            zone,
            0.4,
        )
        self.assertIn(result["score"], range(1, 11))


if __name__ == "__main__":
    unittest.main()
