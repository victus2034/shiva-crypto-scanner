"""The zone-quality metrics must survive the whole way to the analysis.

Every one of these fields was computed by the scanners and then dropped
before anything could learn from it: the crypto scanner never wrote them,
and the backtest never carried the NSE copies past load_records. Both gaps
were silent, because a missing key just reads as null.
"""
import json
import unittest

import pandas as pd
from pathlib import Path
import tempfile

import daily_backtest_summary as summary

METRICS = ["wick_to_body", "wick_atr", "departure_atr", "touch_count", "zone_age_candles"]


class ZoneMetricLoggingTests(unittest.TestCase):
    def _record(self, **overrides):
        record = {
            "delivered_at_utc": "2026-08-31T06:00:00+00:00",
            "symbol": "BTC/USDT",
            "timeframe": "30m",
            "side": "long",
            "distance_pct": 0.05,
            "alert_price": 100.0,
            "level": 99.0,
            "zone_bottom": 98.0,
            "zone_top": 99.0,
            "planned_entry": 99.0,
            "stop_price": 97.9,
            "score": 8,
            "wick_to_body": 2.5,
            "wick_atr": 0.42,
            "departure_atr": 3.1,
            "touch_count": 2,
            "zone_age_candles": 37,
        }
        record.update(overrides)
        return record

    def test_load_records_keeps_every_zone_metric(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.jsonl"
            path.write_text(json.dumps(self._record()) + "\n", encoding="utf-8")

            frame = summary.load_records(path, "30m")

        self.assertEqual(len(frame), 1)
        row = frame.iloc[0]
        for name in METRICS:
            self.assertIn(name, frame.columns, f"{name} was dropped by load_records")
            self.assertIsNotNone(row[name], f"{name} arrived empty")
        self.assertAlmostEqual(row["departure_atr"], 3.1)
        self.assertAlmostEqual(row["zone_age_candles"], 37.0)

    def test_a_record_without_the_metrics_still_loads(self):
        # Everything written before 31 Aug 2026 lacks them, so their absence
        # has to stay survivable rather than skipping the line.
        bare = self._record()
        for name in METRICS:
            bare.pop(name)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.jsonl"
            path.write_text(json.dumps(bare) + "\n", encoding="utf-8")

            frame = summary.load_records(path, "30m")

        self.assertEqual(len(frame), 1)
        for name in METRICS:
            # Absent reads as NaN once pandas types the column, not None.
            self.assertTrue(pd.isna(frame.iloc[0][name]), f"{name} should be empty")


class ScannerRecordTests(unittest.TestCase):
    def test_both_scanners_write_the_metrics_and_the_age(self):
        # Guards the asymmetry that caused this: NSE logged the wick inputs
        # from the start while the crypto scanner silently dropped all four.
        for module in ("scanner.py", "nse_scanner.py"):
            source = Path(__file__).resolve().parent.parent.joinpath(module).read_text(encoding="utf-8")
            body = source.split("def record_delivered_zone_alert", 1)[1].split("\ndef ", 1)[0]
            for name in METRICS:
                self.assertIn(
                    f'"{name}": zone.get("{name}")',
                    body,
                    f"{module} does not record {name}",
                )

    def test_the_zone_age_is_stamped_where_the_bar_index_is_known(self):
        for module in ("scanner.py", "nse_scanner.py"):
            source = Path(__file__).resolve().parent.parent.joinpath(module).read_text(encoding="utf-8")
            body = source.split("def nearest_active_zone", 1)[1].split("\ndef ", 1)[0]
            self.assertIn('nearest["zone_age_candles"]', body, f"{module} never stamps the age")


if __name__ == "__main__":
    unittest.main()
