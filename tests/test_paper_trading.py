import unittest

import pandas as pd

import daily_backtest_summary as backtest
import paper_trading


IST = paper_trading.IST
# Mid-session: before the 15:10 cut-off, so fills are allowed.
NOW = pd.Timestamp("2026-08-17 11:00", tz=paper_trading.IST)


def bars(rows, start="2026-08-17 10:00"):
    index = pd.date_range(start, periods=len(rows), freq="5min", tz=IST)
    return pd.DataFrame(rows, index=index, columns=["high", "low", "close"])


def alert(side="long", entry=100.0, stop=98.0, delivered="2026-08-17 09:55", trade_id="t1"):
    return {
        "symbol": "TCS.NS",
        "timeframe": "30m",
        "side": side,
        "score": 8,
        "trade_id": trade_id,
        "_entry": entry,
        "_stop": stop,
        "_delivered": pd.Timestamp(delivered, tz=IST),
    }


def fresh_state():
    return {"open": {}, "closed": [], "handled": {}}


class FillTests(unittest.TestCase):
    def test_position_opens_only_when_price_reaches_entry(self):
        state = fresh_state()
        # Never trades down to 100, so a resting buy limit never fills.
        frames = {"TCS.NS": bars([[101.5, 100.8, 101.0], [101.2, 100.5, 100.9]])}
        self.assertEqual(paper_trading.open_new_positions(state, [alert()], frames, NOW), [])
        self.assertEqual(state["open"], {})

        frames = {"TCS.NS": bars([[101.5, 100.8, 101.0], [101.0, 99.5, 99.8]])}
        opened = paper_trading.open_new_positions(state, [alert()], frames, NOW)
        self.assertEqual(len(opened), 1)
        self.assertAlmostEqual(state["open"]["t1"]["entry"], 100.0)

    def test_bars_before_the_alert_cannot_fill_it(self):
        state = fresh_state()
        # The touch happens at 10:00, but the alert only landed at 10:30.
        frames = {"TCS.NS": bars([[101.0, 99.0, 99.5]])}
        opened = paper_trading.open_new_positions(
            state, [alert(delivered="2026-08-17 10:30")], frames, NOW
        )
        self.assertEqual(opened, [])

    def test_a_filled_alert_is_not_reopened(self):
        state = fresh_state()
        frames = {"TCS.NS": bars([[101.0, 99.5, 99.8]])}
        paper_trading.open_new_positions(state, [alert()], frames, NOW)
        state["open"].clear()  # simulate it having closed
        self.assertEqual(paper_trading.open_new_positions(state, [alert()], frames, NOW), [])


class OutcomeTests(unittest.TestCase):
    def _open(self, side="long", entry=100.0, stop=98.0):
        state = fresh_state()
        frames = {"TCS.NS": bars([[100.5, 99.9, 100.0]])}
        paper_trading.open_new_positions(
            state, [alert(side=side, entry=entry, stop=stop)], frames, NOW
        )
        return state

    def test_stop_closes_with_slippage_worse_than_minus_one_r(self):
        state = self._open()
        frames = {"TCS.NS": bars([[100.2, 97.5, 97.8]])}
        closed = paper_trading.evaluate_open_positions(
            state, frames, pd.Timestamp("2026-08-17 11:00", tz=IST)
        )
        self.assertEqual(closed[0]["outcome"], "SL")
        self.assertLess(closed[0]["realized_r"], -1.0)

    def test_target_two_closes_at_plus_two_r(self):
        state = self._open()
        frames = {"TCS.NS": bars([[104.5, 100.0, 104.0]])}
        closed = paper_trading.evaluate_open_positions(
            state, frames, pd.Timestamp("2026-08-17 11:00", tz=IST)
        )
        self.assertEqual(closed[0]["outcome"], "+2R")
        self.assertAlmostEqual(closed[0]["realized_r"], 2.0)

    def test_stop_and_target_in_one_bar_is_reported_ambiguous(self):
        state = self._open()
        frames = {"TCS.NS": bars([[102.5, 97.5, 100.0]])}
        closed = paper_trading.evaluate_open_positions(
            state, frames, pd.Timestamp("2026-08-17 11:00", tz=IST)
        )
        self.assertEqual(closed[0]["outcome"], backtest.DATA_QUALITY_AMBIGUOUS)
        self.assertIsNone(closed[0]["realized_r"])

    def test_unresolved_position_squares_off_at_1510_not_market_close(self):
        state = self._open()
        frames = {"TCS.NS": bars([[100.4, 99.8, 99.7]], start="2026-08-17 10:00")}
        # Before 15:10 the position must stay open.
        self.assertEqual(
            paper_trading.evaluate_open_positions(
                state, frames, pd.Timestamp("2026-08-17 14:00", tz=IST)
            ),
            [],
        )
        closed = paper_trading.evaluate_open_positions(
            state, frames, pd.Timestamp("2026-08-17 15:10", tz=IST)
        )
        self.assertEqual(closed[0]["outcome"], "Neither")
        # Priced off the real close, so a drift against the position is a
        # small loss rather than a free breakeven.
        self.assertLess(closed[0]["realized_r"], 0.0)

    def test_half_r_is_banked_when_squaring_off_after_touching_it(self):
        state = self._open()
        frames = {"TCS.NS": bars([[101.2, 99.9, 100.1]])}
        closed = paper_trading.evaluate_open_positions(
            state, frames, pd.Timestamp("2026-08-17 15:10", tz=IST)
        )
        self.assertEqual(closed[0]["outcome"], "+0.5R")
        self.assertAlmostEqual(closed[0]["realized_r"], 0.5)

    def test_touching_half_r_banks_it_against_a_later_stop(self):
        # daily_backtest_summary only converts to SL while the outcome is
        # still unresolved, so a milestone already reached survives a later
        # stop. Paper must apply the same rule or the two are measuring
        # different strategies rather than the same one against live prices.
        state = self._open()
        frames = {"TCS.NS": bars([[101.2, 99.9, 100.1], [100.0, 97.0, 97.2]])}
        closed = paper_trading.evaluate_open_positions(
            state, frames, pd.Timestamp("2026-08-17 11:00", tz=IST)
        )
        self.assertEqual(closed[0]["outcome"], "+0.5R")
        self.assertAlmostEqual(closed[0]["realized_r"], 0.5)

    def test_a_stop_before_any_milestone_still_closes_as_sl(self):
        state = self._open()
        frames = {"TCS.NS": bars([[100.2, 97.0, 97.2], [101.5, 100.0, 101.2]])}
        closed = paper_trading.evaluate_open_positions(
            state, frames, pd.Timestamp("2026-08-17 11:00", tz=IST)
        )
        self.assertEqual(closed[0]["outcome"], "SL")

    def test_price_action_after_1510_cannot_decide_the_trade(self):
        # yfinance keeps printing to 15:25, but the user is flat by 15:10 -
        # a stop that only trades after the cut-off never happened to them.
        state = self._open()
        frames = {
            "TCS.NS": pd.DataFrame(
                [[100.4, 99.8, 100.0], [100.2, 97.0, 97.5]],
                index=pd.DatetimeIndex(
                    ["2026-08-17 15:05", "2026-08-17 15:15"], tz=IST
                ),
                columns=["high", "low", "close"],
            )
        }
        state["open"]["t1"]["entry_time"] = "2026-08-17 15:05:00+05:30"
        closed = paper_trading.evaluate_open_positions(
            state, frames, pd.Timestamp("2026-08-17 15:30", tz=IST)
        )
        self.assertEqual(closed[0]["outcome"], "Neither")

    def test_short_side_stop_and_target_mirror_the_long_side(self):
        state = self._open(side="short", entry=100.0, stop=102.0)
        frames = {"TCS.NS": bars([[102.5, 100.0, 102.2]])}
        closed = paper_trading.evaluate_open_positions(
            state, frames, pd.Timestamp("2026-08-17 11:00", tz=IST)
        )
        self.assertEqual(closed[0]["outcome"], "SL")

        state = self._open(side="short", entry=100.0, stop=102.0)
        frames = {"TCS.NS": bars([[100.1, 95.5, 96.0]])}
        closed = paper_trading.evaluate_open_positions(
            state, frames, pd.Timestamp("2026-08-17 11:00", tz=IST)
        )
        self.assertEqual(closed[0]["outcome"], "+2R")


class PaperWindowTests(unittest.TestCase):
    def test_window_stays_open_past_1510_so_square_off_can_run(self):
        # The cron fires at 15:10 but the runner needs a minute or two to
        # boot. A guard that closed at 15:10 would reject the tick that
        # squares off the day's open positions, orphaning them.
        monday = "2026-08-17"
        self.assertTrue(
            paper_trading.in_paper_window(pd.Timestamp(f"{monday} 15:12", tz=IST))
        )
        self.assertTrue(
            paper_trading.in_paper_window(pd.Timestamp(f"{monday} 10:00", tz=IST))
        )
        self.assertFalse(
            paper_trading.in_paper_window(pd.Timestamp(f"{monday} 09:00", tz=IST))
        )
        self.assertFalse(
            paper_trading.in_paper_window(pd.Timestamp(f"{monday} 16:30", tz=IST))
        )

    def test_no_fill_after_1510_even_inside_the_grace_tail(self):
        state = fresh_state()
        frames = {
            "TCS.NS": pd.DataFrame(
                [[101.0, 99.0, 99.5]],
                index=pd.DatetimeIndex(["2026-08-17 15:15"], tz=IST),
                columns=["high", "low", "close"],
            )
        }
        opened = paper_trading.open_new_positions(
            state, [alert()], frames, pd.Timestamp("2026-08-17 15:20", tz=IST)
        )
        self.assertEqual(opened, [])


class ReportTests(unittest.TestCase):
    def test_report_states_plainly_when_nothing_closed(self):
        message = paper_trading.build_report("2026-08-17", "30m", fresh_state())
        self.assertIn("No paper trades closed", message)

    def test_report_shows_paper_outcomes_and_total(self):
        state = fresh_state()
        state["closed"] = [
            {"date": "2026-08-17", "outcome": "+1R", "realized_r": 1.0, "symbol": "TCS.NS"},
            {"date": "2026-08-17", "outcome": "SL", "realized_r": -1.04, "symbol": "INFY.NS"},
            {"date": "2026-08-16", "outcome": "+2R", "realized_r": 2.0, "symbol": "WIPRO.NS"},
        ]
        message = paper_trading.build_report("2026-08-17", "30m", state)

        self.assertIn("Entries - 2", message)  # 16 Aug row excluded
        self.assertIn("+1R - 1", message)
        self.assertIn("SL - 1", message)
        self.assertIn("Win rate - 50.0%", message)
        self.assertIn("-0.04R", message)


if __name__ == "__main__":
    unittest.main()
