import json
import unittest
from unittest.mock import patch

import pandas as pd

import entry_confirm


def watched(side="long", entry=100.0, stop=98.0, **overrides):
    record = {
        "symbol": "TCS.NS",
        "timeframe": "30m",
        "side": side,
        "score": 8,
        "_entry": entry,
        "_stop": stop,
        "_delivered": pd.Timestamp("2026-08-17 10:00", tz=entry_confirm.IST),
    }
    record.update(overrides)
    return record


class RiskProgressTests(unittest.TestCase):
    def test_progress_is_zero_at_entry_and_one_at_stop(self):
        self.assertAlmostEqual(entry_confirm.risk_progress(100.0, 100.0, 98.0, "long"), 0.0)
        self.assertAlmostEqual(entry_confirm.risk_progress(98.0, 100.0, 98.0, "long"), 1.0)
        self.assertAlmostEqual(entry_confirm.risk_progress(100.0, 100.0, 102.0, "short"), 0.0)
        self.assertAlmostEqual(entry_confirm.risk_progress(102.0, 100.0, 102.0, "short"), 1.0)

    def test_progress_is_negative_when_price_runs_into_profit(self):
        self.assertLess(entry_confirm.risk_progress(101.0, 100.0, 98.0, "long"), 0.0)
        self.assertLess(entry_confirm.risk_progress(99.0, 100.0, 102.0, "short"), 0.0)


class ClassifyTests(unittest.TestCase):
    def test_approach_pings_only_within_threshold(self):
        # 100.09 is 0.09% above a long's entry - still approaching.
        stage, reached = entry_confirm.classify(100.09, watched(), reached_entry=False)
        self.assertEqual(stage, entry_confirm.STAGE_READY)
        self.assertFalse(reached)

        # 100.5 is 0.5% away - too far to be useful yet.
        stage, reached = entry_confirm.classify(100.5, watched(), reached_entry=False)
        self.assertIsNone(stage)
        self.assertFalse(reached)

    def test_entry_stage_while_under_half_the_planned_risk(self):
        stage, reached = entry_confirm.classify(99.5, watched(), reached_entry=False)
        self.assertEqual(stage, entry_confirm.STAGE_ENTRY)
        self.assertTrue(reached)

    def test_late_stage_once_most_of_the_risk_is_gone(self):
        stage, _ = entry_confirm.classify(98.9, watched(), reached_entry=False)
        self.assertEqual(stage, entry_confirm.STAGE_LATE)

    def test_stop_already_hit_is_silent(self):
        stage, _ = entry_confirm.classify(97.9, watched(), reached_entry=True)
        self.assertIsNone(stage)

    def test_bounce_back_into_profit_is_silent(self):
        # Price reached entry earlier, then ran up. Taking it here would sit
        # far from the locked stop, so it must not ping.
        stage, _ = entry_confirm.classify(101.0, watched(), reached_entry=True)
        self.assertIsNone(stage)

    def test_short_side_mirrors_long_side(self):
        short = watched(side="short", entry=100.0, stop=102.0)
        self.assertEqual(
            entry_confirm.classify(99.95, short, reached_entry=False)[0],
            entry_confirm.STAGE_READY,
        )
        self.assertEqual(
            entry_confirm.classify(100.5, short, reached_entry=False)[0],
            entry_confirm.STAGE_ENTRY,
        )
        self.assertEqual(
            entry_confirm.classify(101.5, short, reached_entry=False)[0],
            entry_confirm.STAGE_LATE,
        )
        self.assertIsNone(entry_confirm.classify(99.0, short, reached_entry=True)[0])


class SessionGuardTests(unittest.TestCase):
    def test_window_is_open_during_the_session_and_shut_after_1510(self):
        monday = "2026-08-17"
        self.assertTrue(
            entry_confirm.in_trading_session(pd.Timestamp(f"{monday} 09:20", tz=entry_confirm.IST))
        )
        self.assertFalse(
            entry_confirm.in_trading_session(pd.Timestamp(f"{monday} 09:10", tz=entry_confirm.IST))
        )
        # 15:10 is the user's own cut-off, not the 15:30 exchange close.
        self.assertFalse(
            entry_confirm.in_trading_session(pd.Timestamp(f"{monday} 15:20", tz=entry_confirm.IST))
        )

    def test_weekend_is_closed(self):
        self.assertFalse(
            entry_confirm.in_trading_session(pd.Timestamp("2026-08-15 11:00", tz=entry_confirm.IST))
        )


class WatchWindowTests(unittest.TestCase):
    def _write(self, tmp_path, rows):
        path = tmp_path / "records.jsonl"
        path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
        return path

    def test_only_alerts_inside_the_fillable_window_are_watched(self):
        import tempfile

        now = pd.Timestamp("2026-08-17 12:00", tz=entry_confirm.IST)
        fresh = (now - pd.Timedelta(minutes=30)).tz_convert("UTC").isoformat()
        stale = (now - pd.Timedelta(minutes=200)).tz_convert("UTC").isoformat()
        rows = [
            {
                "delivered_at_utc": fresh,
                "symbol": "TCS.NS",
                "timeframe": "30m",
                "side": "long",
                "planned_entry": 100.0,
                "stop_price": 98.0,
            },
            {
                "delivered_at_utc": stale,
                "symbol": "INFY.NS",
                "timeframe": "30m",
                "side": "long",
                "planned_entry": 50.0,
                "stop_price": 49.0,
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(pd.io.common.Path(tmp), rows)
            with patch.dict(entry_confirm.ALERT_RECORDS, {"30m": path}):
                result = entry_confirm.load_watched_alerts("30m", now)

        self.assertEqual([record["symbol"] for record in result], ["TCS.NS"])


class FormattingTests(unittest.TestCase):
    def test_ping_reports_the_recorded_entry_and_stop_verbatim(self):
        record = watched(entry=4117.10, stop=4131.63, side="short", symbol="BAYERCROP.NS", score=9)
        message = entry_confirm.format_ping(entry_confirm.STAGE_ENTRY, 4120.0, record)

        self.assertIn("BAYERCROP", message)
        self.assertIn("SELL", message)
        self.assertIn("Entry 4117.10", message)
        self.assertIn("SL 4131.63", message)
        self.assertNotIn(".NS", message)


if __name__ == "__main__":
    unittest.main()
