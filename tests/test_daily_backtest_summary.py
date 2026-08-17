import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import pandas as pd

import daily_backtest_summary as summary


def base_alert(**overrides):
    alert = {
        "event_time": pd.Timestamp("2026-08-04 10:00", tz=summary.IST),
        "event_time_ist": pd.Timestamp("2026-08-04 10:00", tz=summary.IST),
        "timeframe": "30m",
        "symbol": "TCS.NS",
        "side": "long",
        "distance_pct": 0.5,
        "alert_price": 100.0,
        "level": 99.0,
        "zone_bottom": 99.0,
        "zone_top": 100.0,
        "body_entry": 100.0,
        "rating": 6,
        "zone_id": "TCS.NS|long|99.00000000|100.00000000",
        "source_line": 1,
    }
    alert.update(overrides)
    return alert


def crypto_alert(**overrides):
    alert = base_alert(
        symbol="BTCUSDT",
        event_time=pd.Timestamp("2026-08-04 10:00", tz=summary.IST),
        event_time_ist=pd.Timestamp("2026-08-04 10:00", tz=summary.IST),
        zone_id="BTCUSDT|long|99.00000000|100.00000000",
    )
    alert.update(overrides)
    return alert


def xstock_alert(**overrides):
    alert = crypto_alert(
        symbol="AAPLXUSD",
        zone_id="AAPLXUSD|long|99.00000000|100.00000000",
    )
    alert.update(overrides)
    return alert


def crypto_frame(start="2026-08-04 10:00", rows=None):
    rows = rows or [
        (101.0, 101.2, 100.8, 101.0),
        (100.0, 100.2, 100.0, 100.1),
        (100.1, 100.4, 99.9, 100.2),
        (100.2, 100.6, 100.0, 100.5),
        (100.5, 101.0, 100.3, 100.9),
        (100.9, 102.0, 100.7, 101.8),
        (101.8, 102.2, 101.5, 102.0),
    ]
    index = pd.date_range(start, periods=len(rows), freq="30min", tz=summary.IST)
    return pd.DataFrame(
        {
            "open": [row[0] for row in rows],
            "high": [row[1] for row in rows],
            "low": [row[2] for row in rows],
            "close": [row[3] for row in rows],
            "volume": [1] * len(rows),
        },
        index=index,
    )


class DailyBacktestSummaryTests(unittest.TestCase):

    def test_xstock_backtest_does_not_use_crypto_six_hour_window(self):
        alerts = pd.DataFrame([xstock_alert()])
        frame = crypto_frame()
        with patch.object(summary, "crypto_tracking_end", side_effect=AssertionError):
            results, _ = summary.run_backtest(
                alerts,
                {"AAPLXUSD": frame},
                market="xstock",
            )
        self.assertEqual(len(results), 1)

    def test_nse_tracking_stops_on_same_trading_day(self):
        index = pd.DatetimeIndex(
            [
                "2026-07-22 09:15",
                "2026-07-22 10:15",
                "2026-07-22 11:15",
                "2026-07-23 09:15",
            ],
            tz=summary.IST,
        )
        frame = pd.DataFrame(
            {
                "open": [100.0, 101.0, 102.0, 120.0],
                "high": [102.0, 103.0, 104.0, 130.0],
                "low": [99.0, 100.0, 101.0, 110.0],
                "close": [101.0, 102.0, 103.0, 125.0],
                "volume": [1, 1, 1, 1],
            },
            index=index,
        )

        end_index, mature = summary.same_day_tracking_end(
            frame,
            pd.Timestamp("2026-07-22 10:00", tz=summary.IST),
        )

        self.assertTrue(mature)
        self.assertEqual(end_index, 2)

    def test_infer_bar_duration_uses_minimum_not_median_gap(self):
        # NSE 4h has only ~2 bars/session, split evenly between the short
        # intraday gap (4h) and the long overnight gap (~20h) - the median
        # of alternating 4h/20h diffs is unstable and can land on the
        # overnight side, making every candle appear to "end" almost a day
        # later than it really does. The minimum gap reliably picks the
        # true bar interval since session breaks are always larger.
        index = pd.DatetimeIndex(
            [
                "2026-08-11 09:15",
                "2026-08-11 13:15",
                "2026-08-12 09:15",
                "2026-08-12 13:15",
                "2026-08-13 09:15",
                "2026-08-13 13:15",
            ],
            tz=summary.IST,
        )
        frame = pd.DataFrame(
            {
                "open": [100.0] * 6,
                "high": [101.0] * 6,
                "low": [99.0] * 6,
                "close": [100.5] * 6,
                "volume": [1] * 6,
            },
            index=index,
        )
        self.assertEqual(summary.infer_bar_duration(frame), pd.Timedelta(hours=4))

    def test_same_day_tracking_end_caps_last_candle_at_market_close(self):
        # A 4h candle starting at 13:15 nominally "ends" at 17:15 (start +
        # 4h), but NSE stops trading at 15:30 - the candle is fully settled
        # by then regardless of its nominal duration. Without capping at
        # market close, this candle looks "not yet confirmed" by the
        # close-cutoff buffer and gets excluded even though it's real,
        # final, same-day data.
        index = pd.DatetimeIndex(
            ["2026-08-14 09:15", "2026-08-14 13:15"], tz=summary.IST
        )
        frame = pd.DataFrame(
            {
                "open": [100.0, 101.0],
                "high": [102.0, 103.0],
                "low": [99.0, 100.0],
                "close": [101.0, 102.0],
                "volume": [1, 1],
            },
            index=index,
        )
        ends = summary.candle_ends(frame)
        self.assertEqual(ends[1], pd.Timestamp("2026-08-14 17:15", tz=summary.IST))

    def test_nse_session_tracking_stays_same_day_using_market_close(self):
        # NSE is traded intraday - a position is squared off same-day,
        # never carried overnight, on any timeframe. nse_session_tracking_end
        # must make the day's last (13:15) candle usable via real market
        # close (15:30), not span into a later trading session to find it.
        index = pd.DatetimeIndex(
            [
                "2026-08-14 09:15",
                "2026-08-14 13:15",
                "2026-08-17 09:15",
            ],
            tz=summary.IST,
        )
        frame = pd.DataFrame(
            {
                "open": [100.0] * 3,
                "high": [102.0] * 3,
                "low": [99.0] * 3,
                "close": [101.0] * 3,
                "volume": [1] * 3,
            },
            index=index,
        )
        end_index, mature = summary.nse_session_tracking_end(
            frame, pd.Timestamp("2026-08-14 09:22", tz=summary.IST)
        )
        self.assertTrue(mature)
        self.assertEqual(end_index, 1)  # stays within 14 Aug, never reaches 17 Aug

    def test_nse_4h_alert_resolves_same_day_not_next_session(self):
        alerts = pd.DataFrame([base_alert(timeframe="4h")])
        index = pd.DatetimeIndex(
            [
                "2026-08-04 09:15",
                "2026-08-04 13:15",
                "2026-08-05 09:15",
            ],
            tz=summary.IST,
        )
        # Zone touch happens on the day's own second (13:15) candle - must
        # resolve there, not by looking at the next trading day at all.
        frame = pd.DataFrame(
            {
                "open": [102.0, 100.0, 200.0],
                "high": [103.0, 100.5, 201.0],
                "low": [101.5, 98.5, 199.0],
                "close": [102.5, 99.5, 200.5],
                "volume": [1, 1, 1],
            },
            index=index,
        )
        results, _ = summary.run_backtest(alerts, {"TCS.NS": frame}, market="nse")
        self.assertTrue(bool(results.iloc[0]["filled"]))
        self.assertEqual(results.iloc[0]["entry_time"], index[1])

    def test_half_r_is_kept_if_price_reverses_later(self):
        index = pd.DatetimeIndex(
            ["2026-08-04 10:00", "2026-08-04 10:30", "2026-08-04 11:00"],
            tz=summary.IST,
        )
        frame = pd.DataFrame(
            {
                "open": [101.0, 100.0, 100.1],
                "high": [101.2, 100.6, 100.2],
                "low": [100.8, 100.0, 99.7],
                "close": [101.0, 100.4, 99.9],
                "volume": [1, 1, 1],
            },
            index=index,
        )

        result = summary.simulate_alert(frame, base_alert(), 0, 2)

        self.assertEqual(result["final_result"], "+0.5R")
        self.assertEqual(result["net_realized_r"], 0.5)

    def test_stop_before_half_r_is_sl(self):
        index = pd.DatetimeIndex(["2026-08-04 10:00", "2026-08-04 10:30"], tz=summary.IST)
        frame = pd.DataFrame(
            {
                "open": [101.0, 100.0],
                "high": [101.2, 100.2],
                "low": [100.8, 98.9],
                "close": [101.0, 99.2],
                "volume": [1, 1],
            },
            index=index,
        )

        result = summary.simulate_alert(frame, base_alert(), 0, 1)

        self.assertEqual(result["final_result"], "SL")
        self.assertEqual(result["net_realized_r"], -1.0)
        self.assertAlmostEqual(result["stop_price"], 98.901)

    def test_same_candle_stop_and_target_is_ambiguous_without_resolution_data(self):
        index = pd.DatetimeIndex(["2026-08-04 10:00", "2026-08-04 10:30"], tz=summary.IST)
        frame = pd.DataFrame(
            {
                "open": [101.0, 100.0],
                "high": [101.2, 100.7],
                "low": [100.8, 98.8],
                "close": [101.0, 100.1],
                "volume": [1, 1],
            },
            index=index,
        )

        result = summary.simulate_alert(frame, base_alert(), 0, 1)

        self.assertEqual(result["final_result"], summary.DATA_QUALITY_AMBIGUOUS)
        self.assertTrue(pd.isna(result["net_realized_r"]))
        self.assertFalse(result["half_r_hit"])
        self.assertIsNone(result["time_to_sl"])

    def test_resolution_windows_preserve_exact_ambiguous_interval(self):
        results = pd.DataFrame(
            [
                {
                    "symbol": "BTCUSDT",
                    "final_result": summary.DATA_QUALITY_AMBIGUOUS,
                    "ambiguous_interval_start": pd.Timestamp("2026-08-04 10:30", tz=summary.IST),
                    "ambiguous_interval_end": pd.Timestamp("2026-08-04 11:00", tz=summary.IST),
                }
            ]
        )

        self.assertEqual(
            summary.resolution_windows(results)["BTCUSDT"],
            (
                pd.Timestamp("2026-08-04 10:30", tz=summary.IST),
                pd.Timestamp("2026-08-04 11:00", tz=summary.IST),
            ),
        )

    def test_reconciliation_diagnostics_detects_missing_finalization(self):
        delivered = pd.DataFrame([{"trade_id": "trade-1"}])
        backtested = pd.DataFrame([{"trade_id": "trade-1", "final_result": "+1R"}])

        with tempfile.TemporaryDirectory() as tmp:
            diagnostics = summary.reconciliation_diagnostics(
                delivered,
                backtested,
                Path(tmp) / "finalized.jsonl",
            )

        self.assertIn("backtest_without_finalized=1", diagnostics["issues"])

    def test_same_candle_order_uses_resolution_frame_when_available(self):
        index = pd.DatetimeIndex(["2026-08-04 10:00", "2026-08-04 10:30"], tz=summary.IST)
        frame = pd.DataFrame(
            {
                "open": [101.0, 100.0],
                "high": [101.2, 100.7],
                "low": [100.8, 98.8],
                "close": [101.0, 100.1],
                "volume": [1, 1],
            },
            index=index,
        )
        resolution_index = pd.date_range("2026-08-04 10:30", periods=3, freq="1min", tz=summary.IST)
        resolution_frame = pd.DataFrame(
            {
                "open": [100.0, 100.6, 99.5],
                "high": [100.1, 100.7, 99.6],
                "low": [99.9, 100.2, 98.8],
                "close": [100.0, 100.3, 99.0],
                "volume": [1, 1, 1],
            },
            index=resolution_index,
        )

        result = summary.simulate_alert(frame, base_alert(), 0, 1, resolution_frame)

        self.assertEqual(result["final_result"], "+0.5R")
        self.assertEqual(result["net_realized_r"], 0.5)

    def test_same_candle_resolution_accepts_timezone_naive_fine_data(self):
        index = pd.DatetimeIndex(["2026-08-04 10:00", "2026-08-04 10:30"], tz=summary.IST)
        frame = pd.DataFrame(
            {
                "open": [101.0, 100.0],
                "high": [101.2, 100.7],
                "low": [100.8, 98.8],
                "close": [101.0, 100.1],
                "volume": [1, 1],
            },
            index=index,
        )
        resolution_index = pd.date_range("2026-08-04 10:30", periods=2, freq="1min")
        resolution_frame = pd.DataFrame(
            {
                "open": [100.0, 99.5],
                "high": [100.7, 99.6],
                "low": [100.0, 98.8],
                "close": [100.4, 99.0],
                "volume": [1, 1],
            },
            index=resolution_index,
        )

        result = summary.simulate_alert(frame, base_alert(), 0, 1, resolution_frame)

        self.assertEqual(result["final_result"], "+0.5R")

    def test_mobile_summary_removes_tradable_be_and_verdict(self):
        records = pd.DataFrame(
            [
                base_alert(symbol="BTCUSDT", rating=4),
                base_alert(symbol="SBIN.NS", rating=6, side="short"),
            ]
        )
        results = pd.DataFrame(
            [
                {**records.iloc[0].to_dict(), "filled": True, "outcome": "+2R", "final_result": "+2R", "net_realized_r": 2.0},
                {**records.iloc[1].to_dict(), "filled": False, "outcome": "zone_not_touched", "final_result": "", "net_realized_r": float("nan")},
            ]
        )

        message = summary.build_summary(records, pd.Timestamp("2026-08-04").date(), results, {}, 0, "30m")

        self.assertIn("NSE 30m BACKTEST\n04 AUG 2026", message)
        self.assertIn("OVERVIEW\nAlerts - 2", message)
        self.assertIn("No Touch - 1", message)
        self.assertIn("4/10 - 1 entries | 1W / 0L | 100.0%", message)
        self.assertIn("No Entries - 6/10", message)
        self.assertIn("1. BTC", message)
        self.assertNotIn("Tradable", message)
        self.assertNotIn("BE:", message)
        self.assertNotIn("Verdict", message)

    def test_missing_rating_is_reported_as_unrated_not_rating_four(self):
        records = pd.DataFrame(
            [
                base_alert(symbol="LEGACY.NS", rating=float("nan")),
            ]
        )
        results = pd.DataFrame(
            [
                {
                    **records.iloc[0].to_dict(),
                    "filled": False,
                    "outcome": "zone_not_touched",
                    "final_result": "",
                    "net_realized_r": float("nan"),
                },
            ]
        )

        message = summary.build_summary(records, pd.Timestamp("2026-08-04").date(), results, {}, 0, "30m")

        self.assertIn("No Entries - Unrated/N/A", message)
        self.assertNotIn("4/10", message)

    def test_no_touch_excludes_data_errors(self):
        records = pd.DataFrame(
            [
                base_alert(symbol="A.NS", rating=5),
                base_alert(symbol="B.NS", rating=5),
                base_alert(symbol="C.NS", rating=5),
            ]
        )
        results = pd.DataFrame(
            [
                {**records.iloc[0].to_dict(), "filled": False, "outcome": "zone_not_touched", "final_result": "", "net_realized_r": float("nan")},
                {**records.iloc[1].to_dict(), "filled": False, "outcome": "data_missing", "final_result": "", "net_realized_r": float("nan")},
                {**records.iloc[2].to_dict(), "filled": False, "outcome": "alert_before_data", "final_result": "", "net_realized_r": float("nan")},
            ]
        )

        message = summary.build_summary(records, pd.Timestamp("2026-08-04").date(), results, {}, 0, "30m")

        self.assertIn("No Touch - 1", message)

    def test_report_results_fall_back_to_report_date_when_trade_ids_change(self):
        target = pd.Timestamp("2026-08-04").date()
        records = pd.DataFrame(
            [
                {**base_alert(symbol="A.NS", rating=5), "trade_id": "current-a", "report_date": target},
                {**base_alert(symbol="B.NS", rating=6, side="short"), "trade_id": "current-b", "report_date": target},
            ]
        )
        results = pd.DataFrame(
            [
                {
                    **records.iloc[0].to_dict(),
                    "trade_id": "old-a",
                    "filled": False,
                    "outcome": "zone_not_touched",
                    "final_result": "",
                    "net_realized_r": float("nan"),
                    "report_date": target,
                },
                {
                    **records.iloc[1].to_dict(),
                    "trade_id": "old-b",
                    "filled": True,
                    "outcome": "+1R",
                    "final_result": "+1R",
                    "net_realized_r": 1.0,
                    "report_date": target,
                },
            ]
        )

        filtered = summary.report_results_for_current_day(results, records, target)
        message = summary.build_summary(records, target, filtered, {}, 0, "30m")

        self.assertEqual(len(filtered), 2)
        self.assertIn("Touch - 1", message)
        self.assertIn("No Touch - 1", message)
        self.assertIn("Entries - 1", message)
        self.assertIn("+1R - 1", message)

    def test_discord_payload_uses_embeds_without_truncating_long_reports(self):
        message = "\n".join([f"Line {index}" for index in range(900)])

        payload = summary.discord_payload(message)
        joined = "\n".join(embed["description"] for embed in payload["embeds"])

        self.assertEqual(joined, message)
        self.assertGreater(len(payload["embeds"]), 1)

    def test_discord_wait_url_requests_message_response(self):
        url = "https://discord.com/api/webhooks/123/token?foo=bar"

        self.assertEqual(
            summary.discord_wait_url(url),
            "https://discord.com/api/webhooks/123/token?foo=bar&wait=true",
        )

    def test_report_state_blocks_duplicate_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sent.json"
            key = summary.report_key(pd.Timestamp("2026-08-04").date(), "30m")

            self.assertNotIn(key, summary.load_sent_reports(path))
            summary.mark_sent_report(key, path)
            self.assertIn(key, summary.load_sent_reports(path))

    def test_crypto_report_key_does_not_collide_with_nse(self):
        day = pd.Timestamp("2026-08-04").date()
        self.assertNotEqual(
            summary.report_key(day, "30m", "nse"),
            summary.report_key(day, "30m", "crypto"),
        )

    def test_crypto_report_date_uses_ist_boundary_day(self):
        afternoon = pd.Timestamp("2026-08-04 16:30", tz=summary.IST)
        evening = pd.Timestamp("2026-08-04 23:59", tz=summary.IST)

        self.assertEqual(summary.crypto_report_date(afternoon), pd.Timestamp("2026-08-04").date())
        self.assertEqual(summary.crypto_report_date(evening), pd.Timestamp("2026-08-05").date())

    def test_crypto_default_report_date_uses_completed_bucket(self):
        today = pd.Timestamp.now(tz=summary.IST).date()
        yesterday = today - pd.Timedelta(days=1)
        tomorrow = today + pd.Timedelta(days=1)
        records = pd.DataFrame(
            [
                {"report_date": yesterday},
                {"report_date": today},
                {"report_date": tomorrow},
            ]
        )

        self.assertEqual(summary.select_target_date(records, None, "crypto", "30m"), today)

    def test_crypto_default_report_date_skips_when_no_bucket_is_complete(self):
        today = pd.Timestamp.now(tz=summary.IST).date()
        records = pd.DataFrame([{"report_date": today}])

        self.assertEqual(summary.select_target_date(records, None, "crypto", "4h"), today)

    def test_nse_cutoff_uses_only_bars_ending_before_cutoff(self):
        index = pd.DatetimeIndex(
            [
                "2026-08-04 14:30",
                "2026-08-04 15:00",
            ],
            tz=summary.IST,
        )
        frame = pd.DataFrame(
            {
                "open": [100.0, 100.0],
                "high": [101.0, 130.0],
                "low": [99.0, 80.0],
                "close": [100.0, 100.0],
                "volume": [1, 1],
            },
            index=index,
        )

        end_index, mature = summary.same_day_tracking_end(
            frame,
            pd.Timestamp("2026-08-04 14:00", tz=summary.IST),
        )

        self.assertTrue(mature)
        self.assertEqual(end_index, 0)

    def test_nse_preopen_alert_cannot_fill_before_trade_start(self):
        index = pd.DatetimeIndex(
            [
                "2026-08-04 09:00",
                "2026-08-04 09:05",
                "2026-08-04 09:10",
                "2026-08-04 09:15",
            ],
            tz=summary.IST,
        )
        frame = pd.DataFrame(
            {
                "open": [101.0, 100.0, 100.0, 101.0],
                "high": [101.2, 100.2, 100.2, 101.5],
                "low": [100.8, 99.8, 99.8, 100.8],
                "close": [101.0, 100.1, 100.1, 101.2],
                "volume": [1, 1, 1, 1],
            },
            index=index,
        )

        result = summary.simulate_alert(
            frame,
            base_alert(event_time=index[0], event_time_ist=index[0]),
            0,
            len(frame) - 1,
        )

        self.assertEqual(result["outcome"], "zone_not_touched")

    def test_crypto_sl_before_half_r_is_sl(self):
        frame = crypto_frame(
            rows=[
                (101.0, 101.2, 100.8, 101.0),
                (100.0, 100.2, 98.9, 99.1),
            ]
        )

        result = summary.simulate_alert(frame, crypto_alert(), 0, 1)

        self.assertEqual(result["final_result"], "SL")

    def test_crypto_half_r_is_kept_after_reversal(self):
        frame = crypto_frame(
            rows=[
                (101.0, 101.2, 100.8, 101.0),
                (100.0, 100.6, 100.0, 100.5),
                (100.5, 100.6, 99.7, 99.9),
            ]
        )

        result = summary.simulate_alert(frame, crypto_alert(), 0, 2)

        self.assertEqual(result["final_result"], "+0.5R")
        self.assertEqual(result["net_realized_r"], 0.5)

    def test_crypto_one_r_supersedes_half_r_after_reversal(self):
        frame = crypto_frame(
            rows=[
                (101.0, 101.2, 100.8, 101.0),
                (100.0, 101.2, 100.0, 101.0),
                (101.0, 101.1, 99.7, 99.9),
            ]
        )

        result = summary.simulate_alert(frame, crypto_alert(), 0, 2)

        self.assertEqual(result["final_result"], "+1R")

    def test_crypto_two_r_stops_tracking(self):
        frame = crypto_frame(
            rows=[
                (101.0, 101.2, 100.8, 101.0),
                (100.0, 102.2, 100.0, 102.0),
                (102.0, 102.1, 98.5, 99.0),
            ]
        )

        result = summary.simulate_alert(frame, crypto_alert(), 0, 2)

        self.assertEqual(result["final_result"], "+2R")
        self.assertEqual(result["exit_time"], frame.index[1])

    def test_crypto_expired_without_half_r_is_neither(self):
        frame = crypto_frame(
            rows=[
                (101.0, 101.2, 100.8, 101.0),
                (100.0, 100.3, 100.0, 100.1),
                (100.1, 100.38, 99.8, 100.2),
                (100.2, 100.3, 99.8, 100.1),
                (100.1, 100.2, 99.8, 100.0),
                (100.0, 100.3, 99.8, 100.1),
                (100.1, 100.2, 99.8, 100.0),
                (100.0, 100.2, 99.8, 100.1),
                (100.1, 100.2, 99.8, 100.0),
                (100.0, 100.2, 99.8, 100.1),
                (100.1, 100.2, 99.8, 100.0),
                (100.0, 100.2, 99.8, 100.1),
                (100.1, 100.2, 99.8, 100.0),
                (100.0, 100.2, 99.8, 100.1),
            ]
        )

        result = summary.simulate_alert(frame, crypto_alert(), 0, len(frame) - 1)

        self.assertEqual(result["final_result"], "Neither")

    def test_crypto_open_trade_inside_six_hours_is_pending(self):
        future_start = (pd.Timestamp.now(tz=summary.IST) + pd.Timedelta(hours=1)).floor("30min")
        frame = crypto_frame(
            start=future_start,
            rows=[
                (101.0, 101.2, 100.8, 101.0),
                (100.0, 100.3, 100.0, 100.1),
            ],
        )
        alert = crypto_alert(event_time=frame.index[0], event_time_ist=frame.index[0])

        result = summary.simulate_alert(frame, alert, 0, 1)

        self.assertEqual(result["final_result"], "Pending")

    def test_crypto_no_entry_waits_until_entry_window_closes(self):
        future_start = (pd.Timestamp.now(tz=summary.IST) + pd.Timedelta(hours=1)).floor("30min")
        frame = crypto_frame(
            start=future_start,
            rows=[
                (101.0, 101.2, 100.8, 101.0),
                (101.0, 101.2, 100.8, 101.0),
            ],
        )
        alert = crypto_alert(event_time=frame.index[0], event_time_ist=frame.index[0])

        result = summary.simulate_alert(frame, alert, 0, 1)

        self.assertEqual(result["outcome"], "immature")

    def test_crypto_tracking_is_not_forced_by_midnight(self):
        frame = crypto_frame(
            start="2026-08-04 23:00",
            rows=[
                (101.0, 101.2, 100.8, 101.0),
                (100.0, 100.2, 100.0, 100.1),
                (100.1, 100.2, 99.8, 100.0),
                (100.0, 100.2, 99.8, 100.1),
                (100.1, 100.2, 99.8, 100.0),
                (100.0, 100.2, 99.8, 100.1),
                (100.1, 100.2, 99.8, 100.0),
                (100.0, 100.2, 99.8, 100.1),
                (100.1, 100.2, 99.8, 100.0),
                (100.0, 100.2, 99.8, 100.1),
                (100.1, 100.2, 99.8, 100.0),
                (100.0, 100.2, 99.8, 100.1),
                (100.1, 100.2, 99.8, 100.0),
                (100.0, 100.2, 99.8, 100.1),
            ],
        )

        result = summary.simulate_alert(frame, crypto_alert(event_time=frame.index[0], event_time_ist=frame.index[0]), 0, len(frame) - 1)

        self.assertEqual(result["final_result"], "Neither")
        self.assertGreater(result["exit_time"].date(), frame.index[0].date())

    def test_crypto_candle_starting_at_expiry_cannot_affect_result(self):
        rows = [(101.0, 101.2, 100.8, 101.0), (100.0, 100.2, 100.0, 100.1)]
        rows.extend([(100.1, 100.2, 99.8, 100.0)] * 23)
        rows.append((100.0, 103.0, 99.8, 102.5))
        frame = crypto_frame(start="2026-08-04 10:00", rows=rows)

        result = summary.simulate_alert(frame, crypto_alert(), 0, len(frame) - 1)

        self.assertEqual(result["final_result"], "Neither")
        self.assertLess(result["exit_time"], frame.index[-1])

    def test_xstock_timing_remains_pending_until_policy_is_approved(self):
        frame = crypto_frame(
            rows=[
                (101.0, 101.2, 100.8, 101.0),
                (100.0, 101.2, 100.0, 101.0),
            ]
        )

        result = summary.simulate_alert(frame, xstock_alert(), 0, 1)

        self.assertEqual(result["final_result"], "Pending")
        self.assertEqual(result["timing_status"], "xstock_timing_tbd")

    def test_xstock_open_trade_inside_six_hours_is_pending(self):
        future_start = (pd.Timestamp.now(tz=summary.IST) + pd.Timedelta(hours=1)).floor("30min")
        frame = crypto_frame(
            start=future_start,
            rows=[
                (101.0, 101.2, 100.8, 101.0),
                (100.0, 100.3, 100.0, 100.1),
            ],
        )
        alert = xstock_alert(event_time=frame.index[0], event_time_ist=frame.index[0])

        result = summary.simulate_alert(frame, alert, 0, 1)

        self.assertEqual(result["final_result"], "Pending")

    def test_xstock_candle_starting_at_expiry_cannot_affect_result(self):
        rows = [(101.0, 101.2, 100.8, 101.0), (100.0, 100.2, 100.0, 100.1)]
        rows.extend([(100.1, 100.2, 99.8, 100.0)] * 23)
        rows.append((100.0, 103.0, 99.8, 102.5))
        frame = crypto_frame(start="2026-08-04 10:00", rows=rows)

        result = summary.simulate_alert(frame, xstock_alert(), 0, len(frame) - 1)

        self.assertEqual(result["final_result"], "Pending")
        self.assertEqual(result["timing_status"], "xstock_timing_tbd")

    def test_finalized_records_include_stable_id_and_timing_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.jsonl"
            frame = crypto_frame(
                rows=[
                    (101.0, 101.2, 100.8, 101.0),
                    (100.0, 101.2, 100.0, 101.0),
                ]
            )
            result = summary.simulate_alert(frame, crypto_alert(), 0, 1)
            results = pd.DataFrame([result])

            summary.persist_finalized_records(
                pd.Timestamp("2026-08-04").date(),
                "30m",
                results,
                "crypto",
                path,
            )

            payload = __import__("json").loads(path.read_text(encoding="utf-8").strip())
            self.assertRegex(payload["trade_id"], r"^[0-9a-f]{16}$")
            self.assertEqual(payload["entry_time"], frame.index[1].isoformat())
            self.assertEqual(payload["time_to_half_r"], frame.index[1].isoformat())
            self.assertEqual(payload["time_to_1r"], frame.index[1].isoformat())
            self.assertIsNone(payload["time_to_2r"])
            self.assertEqual(payload["final_resolution_time"], frame.index[1].isoformat())

    def test_neither_resolution_time_uses_last_usable_candle_end(self):
        frame = crypto_frame(
            rows=[
                (101.0, 101.2, 100.8, 101.0),
                (100.0, 100.2, 100.0, 100.1),
                (100.1, 100.2, 99.8, 100.0),
            ]
        )

        result = summary.simulate_alert(frame, crypto_alert(), 0, 2)

        self.assertEqual(result["final_result"], "Neither")
        self.assertEqual(result["final_resolution_time"], frame.index[2] + pd.Timedelta(minutes=30))

    def test_timing_analytics_groups_finalized_trade_durations(self):
        records = pd.DataFrame(
            [
                {
                    **base_alert(symbol="BTCUSDT", side="long", rating=5),
                    "market": "CRYPTO",
                    "timeframe": "30m",
                    "filled": True,
                    "final_result": "+1R",
                    "time_to_resolution_seconds": 1800,
                },
                {
                    **base_alert(symbol="ETHUSDT", side="short", rating=6),
                    "market": "CRYPTO",
                    "timeframe": "30m",
                    "filled": True,
                    "final_result": "Pending",
                    "time_to_resolution_seconds": None,
                },
                {
                    **base_alert(symbol="SOLUSDT", side="long", rating=5),
                    "market": "CRYPTO",
                    "timeframe": "30m",
                    "filled": False,
                    "final_result": "",
                    "time_to_resolution_seconds": None,
                },
            ]
        )

        analytics = summary.build_timing_analytics(records)

        self.assertEqual(len(analytics), 1)
        row = analytics.iloc[0]
        self.assertEqual(row["market"], "CRYPTO")
        self.assertEqual(row["rating"], 5)
        self.assertEqual(row["side"], "long")
        self.assertEqual(row["final_result"], "+1R")
        self.assertEqual(row["trades"], 1)
        self.assertEqual(row["resolved_within_1h_pct"], 100.0)
        self.assertEqual(row["median_resolution_seconds"], 1800.0)

    def test_format_rating_table_handles_no_results_yet(self):
        records = pd.DataFrame([
            {"symbol": "BTCUSDT", "rating": 7},
        ])
        results = pd.DataFrame()

        table = summary.format_rating_table(records, results)

        self.assertIsInstance(table, str)
        self.assertIn("7/10", table)

    def test_display_symbol_simplifies_common_forms(self):
        cases = {
            "TCS.NS": "TCS",
            "AAPL.USD": "AAPL",
            "AAPLXUSD": "AAPL",
            "AVGO/USDT:USDT": "AVGO",
            "BTCUSDT": "BTC",
            "BTC/USD": "BTC",
            "BTC-USD": "BTC",
            "MSTRBUSD": "MSTR",
        }
        for raw, expected in cases.items():
            self.assertEqual(summary.display_symbol(raw), expected)


if __name__ == "__main__":
    unittest.main()
