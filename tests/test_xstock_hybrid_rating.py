import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

from xstock_hybrid_rating import (
    BLOCKED_XSTOCK_SYMBOLS,
    UNMAPPED_XSTOCK_SYMBOLS,
    XSTOCK_UNDERLYINGS,
    classify_us_session,
    has_underlying_mapping,
    is_xstock,
    prepare_xstock_contexts,
    rate_xstock_zone,
)


class XStockHybridRatingTests(unittest.TestCase):
    def context(self, session="regular", data_fresh=True):
        return {
            "session": session,
            "data_fresh": data_fresh,
            "underlying_price": 100.0,
            "underlying_30m_pct": 0.20,
            "underlying_4h_pct": 0.50,
            "sector_30m_pct": 0.20,
            "sector_4h_pct": 0.50,
        }

    def test_only_29_direct_matches_are_eligible(self):
        self.assertEqual(len(XSTOCK_UNDERLYINGS), 29)
        self.assertNotIn("OPENAI/USDT:USDT", XSTOCK_UNDERLYINGS)
        self.assertNotIn("SAMSUNG/USDT:USDT", XSTOCK_UNDERLYINGS)

    def test_known_symbol_collisions_are_blocked(self):
        self.assertEqual(
            BLOCKED_XSTOCK_SYMBOLS,
            {"BZ/USDT:USDT", "SLX/USDT:USDT"},
        )
        for symbol in BLOCKED_XSTOCK_SYMBOLS:
            self.assertFalse(is_xstock(symbol))

    def test_xstock_classification_is_separate_from_mapping(self):
        audit_targets = {
            "SPCXXUSD",
            "DRAMBUSD",
            "CBRSBUSD",
            "SKHYNIX/USDT:USDT",
            "OPENAI/USDT:USDT",
            "SAMSUNG/USDT:USDT",
        }
        self.assertEqual(UNMAPPED_XSTOCK_SYMBOLS, audit_targets)
        for symbol in audit_targets:
            with self.subTest(symbol=symbol):
                self.assertTrue(is_xstock(symbol))
                self.assertFalse(has_underlying_mapping(symbol))

    def test_us_session_clock(self):
        self.assertEqual(
            classify_us_session(datetime(2026, 7, 29, 15, 0, tzinfo=timezone.utc)),
            "regular",
        )
        self.assertEqual(
            classify_us_session(datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)),
            "extended",
        )
        self.assertEqual(
            classify_us_session(datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc)),
            "closed",
        )
        self.assertEqual(
            classify_us_session(datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)),
            "closed",
        )

    def test_aligned_underlying_and_sector_raise_demand_score(self):
        rating = rate_xstock_zone(
            "NVDAXUSD",
            "demand",
            5,
            100.0,
            self.context(),
        )

        self.assertEqual(rating["score"], 8)
        self.assertTrue(rating["alert_allowed"])
        self.assertEqual(rating["minimum_score"], 5)

    def test_opposite_direction_lowers_supply_score(self):
        rating = rate_xstock_zone(
            "NVDAXUSD",
            "supply",
            7,
            100.0,
            self.context(),
        )

        self.assertEqual(rating["score"], 4)
        self.assertFalse(rating["alert_allowed"])

    def test_extended_session_uses_five_minimum(self):
        rating = rate_xstock_zone(
            "NVDAXUSD",
            "demand",
            4,
            100.0,
            self.context(session="extended"),
        )

        self.assertEqual(rating["score"], 7)
        self.assertEqual(rating["minimum_score"], 5)
        self.assertTrue(rating["alert_allowed"])

    def test_score_five_passes_both_sessions_and_four_is_blocked(self):
        neutral_context = self.context()
        neutral_context.update(
            {
                "underlying_30m_pct": 0.0,
                "underlying_4h_pct": 0.0,
                "sector_30m_pct": 0.0,
                "sector_4h_pct": 0.0,
            }
        )

        for session in ("regular", "extended"):
            with self.subTest(session=session):
                neutral_context["session"] = session
                passing = rate_xstock_zone(
                    "NVDAXUSD",
                    "demand",
                    5,
                    100.0,
                    neutral_context,
                )
                blocked = rate_xstock_zone(
                    "NVDAXUSD",
                    "demand",
                    4,
                    100.0,
                    neutral_context,
                )

                self.assertEqual(passing["minimum_score"], 5)
                self.assertEqual(passing["score"], 5)
                self.assertTrue(passing["alert_allowed"])
                self.assertEqual(blocked["score"], 4)
                self.assertFalse(blocked["alert_allowed"])

    def test_closed_or_stale_context_keeps_native_alert_decision(self):
        closed = rate_xstock_zone(
            "NVDAXUSD",
            "demand",
            9,
            100.0,
            self.context(session="closed", data_fresh=False),
        )
        stale = rate_xstock_zone(
            "NVDAXUSD",
            "demand",
            9,
            100.0,
            self.context(data_fresh=False),
        )

        self.assertTrue(closed["alert_allowed"])
        self.assertTrue(stale["alert_allowed"])
        self.assertEqual(closed["score"], 9)
        self.assertEqual(stale["score"], 9)
        self.assertEqual(closed["context_status"], "underlying_context_stale")

    def test_unmapped_symbol_keeps_native_base_score(self):
        rating = rate_xstock_zone(
            "SPCXXUSD",
            "demand",
            6,
            100.0,
            None,
        )

        self.assertEqual(rating["score"], 6)
        self.assertTrue(rating["alert_allowed"])
        self.assertEqual(rating["context_status"], "underlying_unmapped")

    def test_large_basis_mismatch_suppresses_alert(self):
        rating = rate_xstock_zone(
            "NVDAXUSD",
            "demand",
            9,
            103.0,
            self.context(),
        )

        self.assertGreater(abs(rating["basis_pct"]), 2.0)
        self.assertFalse(rating["alert_allowed"])

    def test_batch_provider_shape_builds_fresh_context(self):
        index = pd.date_range(
            "2026-07-29 14:30:00+00:00",
            periods=9,
            freq="30min",
        )
        columns = pd.MultiIndex.from_product(
            [["NVDA", "SOXX"], ["Close"]]
        )
        data = pd.DataFrame(
            {
                ("NVDA", "Close"): [190 + value for value in range(9)],
                ("SOXX", "Close"): [300 + value for value in range(9)],
            },
            index=index,
            columns=columns,
        )

        with patch("xstock_hybrid_rating.yf.download", return_value=data):
            contexts = prepare_xstock_contexts(
                ["NVDAXUSD"],
                now=datetime(
                    2026,
                    7,
                    29,
                    19,
                    0,
                    tzinfo=timezone.utc,
                ),
            )

        self.assertIn("NVDAXUSD", contexts)
        self.assertTrue(contexts["NVDAXUSD"]["data_fresh"])
        self.assertEqual(contexts["NVDAXUSD"]["session"], "regular")
        self.assertEqual(contexts["NVDAXUSD"]["underlying_price"], 198.0)


if __name__ == "__main__":
    unittest.main()
