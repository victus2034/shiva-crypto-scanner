import json
import unittest
from unittest.mock import patch

import pandas as pd

import config
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
            with patch.dict(entry_confirm.ALERT_RECORDS, {"nse": {"30m": path}}):
                result = entry_confirm.load_watched_alerts("nse", "30m", now)

        self.assertEqual([record["symbol"] for record in result], ["TCS.NS"])


class FormattingTests(unittest.TestCase):
    def test_ping_reports_the_recorded_entry_and_stop_verbatim(self):
        record = watched(entry=4117.10, stop=4131.63, side="short", symbol="BAYERCROP.NS", score=9)
        line = entry_confirm.format_line(entry_confirm.STAGE_ENTRY, 4120.0, record)

        self.assertIn("BAYERCROP", line)
        self.assertIn("SELL", line)
        self.assertIn("4117.10", line)
        self.assertIn("SL 4131.63", line)
        self.assertNotIn(".NS", line)

    def test_each_alert_takes_one_line(self):
        record = watched(entry=100.0, stop=99.0, side="long", symbol="TCS.NS", score=8)
        line = entry_confirm.format_line(entry_confirm.STAGE_ENTRY, 100.2, record)

        self.assertNotIn(chr(10), line)

    def test_a_cheap_coin_keeps_its_precision(self):
        # Two decimals would print this as 0.00 and lose the level entirely.
        record = watched(entry=0.002765, stop=0.002810, side="short", symbol="ZILUSDT")
        line = entry_confirm.format_line(entry_confirm.STAGE_ENTRY, 0.002770, record)

        self.assertIn("0.00276500", line)


class DroppedSymbolTests(unittest.TestCase):
    def test_a_symbol_off_the_watchlist_is_not_watched(self):
        # Its last alert stays fillable for hours after the symbol is cut, and
        # broker_label would call it CoinSwitch simply because it is no longer
        # in the Delta list - pointing at the wrong exchange for a trade that
        # was deliberately dropped.
        import json
        import tempfile
        from pathlib import Path

        import config

        dropped = "DASH/USDT"
        self.assertNotIn(dropped, config.WATCHLIST)
        kept = next(s for s in config.WATCHLIST if s in config.DELTA_LISTED_SYMBOLS)

        now = pd.Timestamp.now(tz=entry_confirm.IST)
        delivered = (now - pd.Timedelta(minutes=10)).tz_convert("UTC").isoformat()
        rows = [
            {"symbol": sym, "timeframe": "4h", "side": "long", "score": 8,
             "planned_entry": 100.0, "stop_price": 98.0, "delivered_at_utc": delivered}
            for sym in (dropped, kept)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.jsonl"
            path.write_text(
                "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
            )
            with patch.dict(entry_confirm.ALERT_RECORDS["crypto"], {"4h": path}):
                watched = entry_confirm.load_watched_alerts("crypto", "4h", now)

        symbols = {r["symbol"] for r in watched}
        self.assertNotIn(dropped, symbols)
        self.assertIn(kept, symbols)


class BrokerLabelTests(unittest.TestCase):
    def test_a_delta_listed_symbol_names_delta(self):
        record = watched(symbol="BTCUSD", _market="crypto")
        self.assertEqual(entry_confirm.broker_label(record), "Delta")
        line = entry_confirm.format_line(entry_confirm.STAGE_READY, 100.1, record)
        self.assertTrue(line.endswith(" · Delta"), line)

    def test_anything_else_on_the_watchlist_falls_to_coinswitch(self):
        record = watched(symbol="CL/USDT", _market="crypto")
        self.assertEqual(entry_confirm.broker_label(record), "CoinSwitch")
        line = entry_confirm.format_line(entry_confirm.STAGE_ENTRY, 99.0, record)
        self.assertTrue(line.endswith(" · CoinSwitch"), line)

    def test_an_nse_symbol_carries_no_venue(self):
        # NSE trades on neither book, so a venue tag there is pure noise.
        record = watched(symbol="RELIANCE.NS", _market="nse")
        self.assertIsNone(entry_confirm.broker_label(record))
        line = entry_confirm.format_line(entry_confirm.STAGE_READY, 100.1, record)
        self.assertNotIn("Delta", line)
        self.assertNotIn("CoinSwitch", line)

    def test_the_venue_map_does_not_drift_from_the_watchlist(self):
        # A symbol dropped from the watchlist but left in the venue map would
        # go unnoticed; one added and forgotten would silently read CoinSwitch.
        self.assertTrue(config.DELTA_LISTED_SYMBOLS <= set(config.WATCHLIST))

    def test_every_scanned_crypto_symbol_gets_a_venue(self):
        import scanner

        for symbol in scanner.active_watchlist():
            label = entry_confirm.broker_label({"symbol": symbol, "_market": "crypto"})
            self.assertIn(label, ("Delta", "CoinSwitch"), symbol)


class DigestTests(unittest.TestCase):
    def test_a_run_posts_one_message_not_one_per_symbol(self):
        now = pd.Timestamp("2026-08-23 11:00", tz=entry_confirm.IST)
        pings = [
            (entry_confirm.STAGE_ENTRY, "`TCS` BUY 8/10 · a"),
            (entry_confirm.STAGE_LATE, "`INFY` SELL 9/10 · b"),
            (entry_confirm.STAGE_READY, "`WIPRO` BUY 6/10 · c"),
            (entry_confirm.STAGE_ENTRY, "`SBIN` BUY 7/10 · d"),
        ]

        messages = entry_confirm.build_digest(pings, now)

        self.assertEqual(len(messages), 1)
        digest = messages[0]
        for symbol in ("TCS", "INFY", "WIPRO", "SBIN"):
            self.assertIn(symbol, digest)
        # Entry first - it is the only stage asking for action right now.
        self.assertLess(digest.index("ENTRY NOW"), digest.index("LATE"))
        self.assertLess(digest.index("LATE"), digest.index("GET READY"))

    def test_nothing_to_report_sends_nothing(self):
        now = pd.Timestamp("2026-08-23 11:00", tz=entry_confirm.IST)

        self.assertEqual(entry_confirm.build_digest([], now), [])

    def test_a_flood_is_split_rather_than_truncated(self):
        now = pd.Timestamp("2026-08-23 11:00", tz=entry_confirm.IST)
        pings = [(entry_confirm.STAGE_ENTRY, f"`SYM{n:03d}` BUY 8/10 · line") for n in range(200)]

        messages = entry_confirm.build_digest(pings, now)

        self.assertGreater(len(messages), 1)
        for message in messages:
            self.assertLessEqual(len(message), entry_confirm.MAX_MESSAGE_CHARS)
        joined = "".join(messages)
        for n in (0, 99, 199):
            self.assertIn(f"SYM{n:03d}", joined)




class WatchKeyTests(unittest.TestCase):
    def test_the_same_zone_re_alerted_gets_one_key(self):
        # A zone's edges drift in the far decimals as ATR moves with each
        # new candle. Fixed decimals split those into separate keys and the
        # same trade was pinged twice in one digest.
        first = watched(entry=141.17203103477016, stop=140.859, symbol="BANKINDIA.NS")
        second = watched(entry=141.17210107412592, stop=140.859, symbol="BANKINDIA.NS")

        self.assertEqual(entry_confirm.watch_key(first), entry_confirm.watch_key(second))

    def test_genuinely_different_levels_stay_apart(self):
        first = watched(entry=141.17, stop=140.859, symbol="BANKINDIA.NS")
        second = watched(entry=141.52, stop=140.859, symbol="BANKINDIA.NS")

        self.assertNotEqual(entry_confirm.watch_key(first), entry_confirm.watch_key(second))

    def test_a_cheap_coin_keeps_its_resolution(self):
        first = watched(entry=0.00276512, stop=0.00281, symbol="ZILUSDT")
        second = watched(entry=0.00276587, stop=0.00281, symbol="ZILUSDT")

        self.assertNotEqual(entry_confirm.watch_key(first), entry_confirm.watch_key(second))


class ApproachBandTests(unittest.TestCase):
    def test_every_delivered_alert_starts_inside_the_approach_band(self):
        # An alert fires within MAX_DISTANCE_PCT of entry. A narrower
        # approach band leaves a dead zone where an alert exists but can
        # never ping - which is where the crypto alerts were going.
        self.assertGreaterEqual(
            entry_confirm.APPROACH_THRESHOLD_PCT, config.MAX_DISTANCE_PCT
        )

    def test_an_alert_at_the_far_edge_of_the_window_still_pings(self):
        record = watched(entry=100.0, stop=99.0, side="long")
        # 0.18% away: inside the alert window, outside the old 0.10 band.
        stage, reached = entry_confirm.classify(100.18, record, False)

        self.assertEqual(stage, entry_confirm.STAGE_READY)
        self.assertFalse(reached)

class ScopeTests(unittest.TestCase):
    def test_it_watches_crypto_over_both_timeframes_by_default(self):
        # NSE was dropped from this job, and covering one timeframe
        # silently halved the channel.
        args = entry_confirm.parse_args([])

        self.assertEqual(args.market, "crypto")
        self.assertEqual(entry_confirm.markets_for(args.market), ["crypto"])
        self.assertEqual(entry_confirm.timeframes_for(args.timeframe), ["30m", "4h"])

    def test_nse_can_still_be_asked_for_explicitly(self):
        # Paused, not deleted - the records and the code still work.
        args = entry_confirm.parse_args(["--market", "nse", "--timeframe", "30m"])

        self.assertEqual(entry_confirm.markets_for(args.market), ["nse"])
        self.assertEqual(entry_confirm.timeframes_for(args.timeframe), ["30m"])



if __name__ == "__main__":
    unittest.main()
