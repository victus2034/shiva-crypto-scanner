"""Forward paper trading against live prices, with no broker and no money.

The daily backtest replays history through the same logic that produced the
alerts, so it can only ever be in-sample. This module runs the same trade
rules forward in real time instead: it opens a virtual position only when
live price actually reaches the alert's recorded entry, carries it under the
locked stop, and squares off at 15:10 like the user does. Comparing its
results against the backtest's for the same day is therefore a genuinely
out-of-sample check on both the edge and the fill assumptions.

Deliberately reuses daily_backtest_summary's constants and
entry_confirm's watch-window logic rather than re-deriving them, so any
divergence in the report reflects reality and not two drifting copies of
the same rules.

  --tick    advance the simulation (schedule this through the session)
  --report  post the day's paper-vs-backtest comparison
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, time as datetime_time, timedelta
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

import daily_backtest_summary as backtest
import entry_confirm


IST = backtest.IST
STATE_PATH = Path(__file__).with_name("paper_trading_state.json")
# Falls back to the daily backtest channel so the comparison lands next to
# the report it is meant to be read against, with no extra setup.
WEBHOOK_ENV = "DISCORD_PAPER_TRADING_WEBHOOK_URL"
FALLBACK_WEBHOOK_ENV = backtest.WEBHOOK_ENV
# 5-minute bars keep same-bar stop/target collisions rare without needing
# the backtest's separate 1-minute resolution fetch. Collisions that do
# happen are reported as ambiguous rather than guessed, matching the
# backtest's own refusal to invent an ordering it cannot see.
BAR_INTERVAL = "5m"
AMBIGUOUS = backtest.DATA_QUALITY_AMBIGUOUS
# Ticks keep running past the 15:10 trading cut-off purely so open
# positions get squared off. The cron fires at 15:10 but the runner needs a
# minute or two to boot, so a guard that stopped at 15:10 would reject the
# very tick that closes the day's remaining positions and leave them open
# forever. Fills and level checks are still capped at 15:10 internally, so
# nothing here lets a trade the user could not have taken into the results.
SQUARE_OFF_GRACE_END = datetime_time(16, 0)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    # Named here rather than borrowed from entry_confirm.ALERT_RECORDS:
    # that dict grew a market layer and silently turned these choices
    # into {crypto, nse}, so every scheduled tick died on its own
    # default. Paper trading follows NSE alerts, hence NSE timeframes.
    parser.add_argument("--timeframe", choices=["30m", "4h"], default="30m")
    # NSE is paused while crypto is measured. The state file keys every
    # trade by market, so the two never mix and NSE can come back without
    # losing its history.
    parser.add_argument(
        "--market", choices=["nse", "crypto", "xstock"], default="crypto"
    )
    parser.add_argument("--tick", action="store_true", help="Advance the simulation.")
    parser.add_argument("--report", action="store_true", help="Post the daily comparison.")
    parser.add_argument("--date", help="IST date for --report, YYYY-MM-DD.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ignore-session", action="store_true")
    return parser.parse_args(argv)


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"open": {}, "closed": [], "handled": {}}
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"open": {}, "closed": [], "handled": {}}
    for key, default in (("open", {}), ("closed", []), ("handled", {})):
        state.setdefault(key, default)
    return state


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def fetch_crypto_bars(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Recent 5m OHLC per symbol, from the scan's own venue chain.

    Imported lazily so the NSE path never pays for ccxt loading, and so a
    crypto venue being unreachable cannot stop an NSE tick.
    """
    if not symbols:
        return {}
    import scanner

    frames: dict[str, pd.DataFrame] = {}
    previous, scanner.TIMEFRAME = scanner.TIMEFRAME, BAR_INTERVAL
    try:
        for symbol in symbols:
            try:
                ohlcv, _ = scanner.fetch_symbol_ohlcv(symbol)
            except Exception as error:
                print(f"{symbol} paper bars unavailable: {str(error)[:70]}")
                continue
            frame = pd.DataFrame(
                ohlcv, columns=["time", "open", "high", "low", "close", "volume"]
            )
            frame.index = pd.to_datetime(
                frame["time"], unit="ms", utc=True
            ).dt.tz_convert(IST)
            frames[symbol] = frame[["open", "high", "low", "close"]].sort_index()
    finally:
        scanner.TIMEFRAME = previous
    return frames


def fetch_bars(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Intraday OHLC per symbol for the current session."""
    if not symbols:
        return {}
    try:
        raw = yf.download(
            tickers=" ".join(symbols),
            period="1d",
            interval=BAR_INTERVAL,
            auto_adjust=False,
            progress=False,
            threads=True,
            group_by="ticker" if len(symbols) > 1 else "column",
        )
    except Exception as error:
        print(f"paper bar fetch failed: {error}")
        return {}
    if raw is None or raw.empty:
        return {}

    frames: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            frame = raw[symbol] if len(symbols) > 1 else raw
        except (KeyError, IndexError):
            continue
        if frame is None or frame.empty:
            continue
        columns = {str(name).lower(): name for name in frame.columns}
        if not {"high", "low", "close"}.issubset(columns):
            continue
        tidy = frame[[columns["high"], columns["low"], columns["close"]]].copy()
        tidy.columns = ["high", "low", "close"]
        index = pd.DatetimeIndex(pd.to_datetime(tidy.index))
        tidy.index = index.tz_localize(IST) if index.tz is None else index.tz_convert(IST)
        frames[symbol] = tidy.dropna().sort_index()
    return frames


def targets_for(entry: float, stop: float, side: str) -> dict[str, float]:
    direction = 1.0 if side == "long" else -1.0
    risk = abs(entry - stop)
    if risk <= 0:
        risk = entry * backtest.FIXED_STOP_PCT / 100.0
    return {
        "risk": risk,
        "half": entry + direction * risk * backtest.HALF_R,
        "one": entry + direction * risk * backtest.TARGET_1_R,
        "two": entry + direction * risk * backtest.TARGET_2_R,
    }


def open_new_positions(
    state: dict,
    watched: list[dict],
    frames: dict[str, pd.DataFrame],
    now: pd.Timestamp,
    market: str = "nse",
) -> list[str]:
    """Fill a virtual limit order only if price genuinely reached entry."""
    opened = []
    for record in watched:
        trade_id = record.get("trade_id") or entry_confirm.watch_key(record)
        if trade_id in state["handled"] or trade_id in state["open"]:
            continue
        frame = frames.get(record["symbol"])
        if frame is None or frame.empty:
            continue

        entry = record["_entry"]
        stop = record["_stop"]
        side = record.get("side", "long")
        # A fill after the user has stopped trading is not a trade they
        # could have taken, so it must not open a position. Crypto has no
        # such cut-off, so only the alert time bounds it.
        after_alert = frame[frame.index > record["_delivered"]]
        if market == "nse":
            square_off = horizon_end(market, record["_delivered"], now)
            after_alert = after_alert[after_alert.index < square_off]
        if after_alert.empty:
            continue

        touched = (
            (after_alert["low"] <= entry) if side == "long" else (after_alert["high"] >= entry)
        )
        if not bool(touched.any()):
            continue

        fill_time = after_alert.index[list(touched).index(True)]
        levels = targets_for(entry, stop, side)
        # Fill at the recorded entry, matching the backtest's assumption, so
        # the comparison isolates whether the fill happened rather than
        # crediting a favourable gap the backtest never modelled.
        state["open"][trade_id] = {
            "symbol": record["symbol"],
            # Stamped so the two markets never mix in one state file and NSE
            # can be paused without losing its history.
            "market": market,
            "side": side,
            "entry": entry,
            "stop": stop,
            "risk": levels["risk"],
            "target_half": levels["half"],
            "target_1": levels["one"],
            "target_2": levels["two"],
            "rating": record.get("score"),
            "alert_time": record["_delivered"].isoformat(),
            "entry_time": fill_time.isoformat(),
            "half_r_hit": False,
        }
        state["handled"][trade_id] = "filled"
        opened.append(trade_id)
    return opened


def evaluate_open_positions(
    state: dict,
    frames: dict[str, pd.DataFrame],
    now: pd.Timestamp,
    market: str = "nse",
) -> list[dict]:
    """Walk each open position forward and close it if a level was hit."""
    closed = []
    for trade_id in list(state["open"]):
        position = state["open"][trade_id]
        frame = frames.get(position["symbol"])
        if frame is None or frame.empty:
            continue

        entry_time = pd.Timestamp(position["entry_time"])
        side = position["side"]
        entry = position["entry"]
        stop = position["stop"]
        risk = position["risk"]
        # Bars are stamped at their start, so a bar opening at 15:10 covers
        # price action the user is already flat for. Anything from the
        # cut-off onwards must not decide the trade. For crypto the same
        # role is played by six hours from entry.
        square_off = horizon_end(market, entry_time, now)
        window = frame[(frame.index >= entry_time) & (frame.index < square_off)]
        if window.empty:
            continue

        outcome = None
        exit_price = None
        exit_time = None
        for timestamp, bar in window.iterrows():
            high = float(bar["high"])
            low = float(bar["low"])
            # Same rule as daily_backtest_summary: +0.5R moves the stop to
            # entry rather than closing the trade, so giving it back exits
            # flat. Diverging here would compare two different strategies
            # rather than test the same one against live prices.
            direction = 1.0 if side == "long" else -1.0
            break_even_stop = (
                entry + direction * entry * backtest.BREAK_EVEN_OFFSET_PCT / 100.0
            )
            # A breakeven stop the wrong side of its own trigger would fill
            # instantly, forcing the trade out at the offset rather than
            # protecting it. Same guard as daily_backtest_summary.
            reachable = direction * (position["target_half"] - break_even_stop) >= 0
            stop_moved = (
                position["half_r_hit"] and backtest.BREAK_EVEN_ENABLED and reachable
            )
            active_stop = break_even_stop if stop_moved else stop
            stop_hit = low <= active_stop if side == "long" else high >= active_stop
            two_hit = high >= position["target_2"] if side == "long" else low <= position["target_2"]
            one_hit = high >= position["target_1"] if side == "long" else low <= position["target_1"]
            half_hit = high >= position["target_half"] if side == "long" else low <= position["target_half"]

            if outcome is None and stop_hit and (two_hit or one_hit or half_hit):
                # Both sides printed inside one bar; the real order is
                # unknowable here, so report it rather than guess.
                outcome, exit_time = AMBIGUOUS, timestamp
                exit_price = float("nan")
                break
            if stop_hit:
                if outcome is None:
                    if stop_moved:
                        outcome, exit_price = backtest.BREAK_EVEN, break_even_stop
                    else:
                        outcome = "SL"
                        exit_price = stop - direction * stop * backtest.SL_FILL_SLIPPAGE_PCT / 100.0
                exit_time = timestamp
                break
            if half_hit:
                position["half_r_hit"] = True
            if one_hit:
                outcome, exit_price, exit_time = "+1R", position["target_1"], timestamp
            if two_hit:
                outcome, exit_price, exit_time = "+2R", position["target_2"], timestamp
                break

        if outcome is None and now >= square_off:
            # The user is flat by 15:10, so an unresolved position exits at
            # the last price before that, priced off the real close the same
            # way the backtest now prices its "Neither" trades.
            exit_price = float(window["close"].iloc[-1])
            exit_time = window.index[-1]
            outcome = "Neither"

        if outcome is None:
            continue

        if outcome == AMBIGUOUS:
            realized_r = float("nan")
        elif outcome in {"+1R", "+2R"}:
            realized_r = backtest.FINAL_RESULT_R[outcome]
        else:
            direction = 1.0 if side == "long" else -1.0
            realized_r = direction * (exit_price - entry) / risk

        # Same charge model as the backtest, so the two totals stay
        # comparable rather than one being gross and the other net.
        cost_r = backtest.round_trip_cost_r(entry, risk, "nse")
        net_r = realized_r - cost_r if pd.notna(realized_r) else realized_r

        record = dict(position)
        record.update(
            {
                "trade_id": trade_id,
                "outcome": outcome,
                "final_result": outcome,
                "exit_price": None if pd.isna(exit_price) else float(exit_price),
                "exit_time": pd.Timestamp(exit_time).isoformat(),
                "realized_r": None if pd.isna(realized_r) else float(realized_r),
                "cost_r": float(cost_r),
                "net_realized_r": None if pd.isna(net_r) else float(net_r),
                "date": pd.Timestamp(position["entry_time"]).date().isoformat(),
                "market": position.get("market", "nse"),
            }
        )
        state["closed"].append(record)
        state["open"].pop(trade_id)
        closed.append(record)
    return closed


def in_paper_window(now: pd.Timestamp) -> bool:
    """Trading hours plus a grace tail for squaring off open positions."""
    if now.weekday() >= 5:
        return False
    return entry_confirm.TRADE_START <= now.time() <= SQUARE_OFF_GRACE_END


def paper_window_open(market: str, now: pd.Timestamp) -> bool:
    """Whether this market is inside the hours it can be traded in.

    Crypto has no session, so it follows the alert window instead - the
    scanner will not raise an alert outside 08:00-01:00 IST, so paper has
    nothing to act on there either.
    """
    if market == "nse":
        return in_paper_window(now)
    return entry_confirm.crypto_alert_window_open(now)


def horizon_end(market: str, entry_time: pd.Timestamp, now: pd.Timestamp) -> pd.Timestamp:
    """When a position stops being judged.

    NSE squares off at 15:10 because the user does. Crypto never closes,
    so it takes the backtest's six hours from entry - diverging here would
    compare two different strategies rather than one strategy against live
    prices, which is the whole point of the comparison.
    """
    if market == "nse":
        return pd.Timestamp(
            datetime.combine(now.date(), backtest.NSE_BACKTEST_CLOSE_CUTOFF), tz=IST
        )
    return pd.Timestamp(entry_time) + timedelta(hours=backtest.CRYPTO_EVALUATION_HOURS)


def run_tick(args: argparse.Namespace) -> None:
    now = pd.Timestamp.now(tz=IST)
    if not args.ignore_session and not paper_window_open(args.market, now):
        print(
            f"{args.market} outside its paper window "
            f"({now:%Y-%m-%d %H:%M} IST); nothing to do."
        )
        return

    state = load_state()
    watched = entry_confirm.load_watched_alerts(args.market, args.timeframe, now)
    symbols = sorted(
        {record["symbol"] for record in watched}
        | {
            position["symbol"]
            for position in state["open"].values()
            if position.get("market", "nse") == args.market
        }
    )
    frames = (
        fetch_bars(symbols) if args.market == "nse" else fetch_crypto_bars(symbols)
    )

    opened = open_new_positions(state, watched, frames, now, args.market)
    closed = evaluate_open_positions(state, frames, now, args.market)

    for trade_id in opened:
        position = state["open"].get(trade_id)
        if position:
            print(
                f"OPEN  {backtest.display_symbol(position['symbol'])} {position['side']} "
                f"@ {position['entry']:.2f} SL {position['stop']:.2f}"
            )
    for record in closed:
        realized = record["realized_r"]
        realized_text = "n/a" if realized is None else f"{realized:+.2f}R"
        print(
            f"CLOSE {backtest.display_symbol(record['symbol'])} {record['outcome']} {realized_text}"
        )
    print(f"open={len(state['open'])} closed_total={len(state['closed'])}")

    if not args.dry_run:
        save_state(state)


def backtest_day_stats(date_iso: str, timeframe: str, market: str = "nse") -> dict | None:
    """Same-day figures from the backtest's own finalized records."""
    path = backtest.FINALIZED_RECORDS_PATH
    if not path.exists():
        return None
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            str(row.get("market", "")).lower() == market.lower()
            and row.get("timeframe") == timeframe
            and row.get("date") == date_iso
            and row.get("filled")
        ):
            rows.append(row)
    if not rows:
        return None
    decided = [r for r in rows if r.get("final_result") in {"SL", "+0.5R", "+1R", "+2R"}]
    wins = sum(1 for r in decided if r.get("final_result") != "SL")
    total_r = sum(float(r.get("net_realized_r") or 0.0) for r in rows)
    return {
        "entries": len(rows),
        "decided": len(decided),
        "wins": wins,
        "total_r": total_r,
    }


MARKETS = [("nse", "NSE"), ("crypto", "CRYPTO"), ("xstock", "XSTOCK")]
TIMEFRAMES = ["30m", "4h"]


def paper_day_stats(state: dict, date_iso: str, market: str, timeframe: str) -> dict | None:
    rows = [
        row for row in state["closed"]
        if row.get("date") == date_iso
        and row.get("market", "nse").lower() == market
        and row.get("timeframe", timeframe) == timeframe
    ]
    if not rows:
        return None
    decided = [r for r in rows if r.get("outcome") in {"SL", "+0.5R", "+1R", "+2R"}]
    wins = sum(1 for r in decided if r.get("outcome") != "SL")
    total = sum(
        (r.get("net_realized_r") if r.get("net_realized_r") is not None else r.get("realized_r")) or 0.0
        for r in rows
    )
    return {"entries": len(rows), "decided": len(decided), "wins": wins, "total_r": total}


def side_text(stats: dict | None) -> str:
    if stats is None:
        return "-"
    rate = f"{stats['wins'] / stats['decided'] * 100:.1f}%" if stats["decided"] else "N/A"
    return f"{stats['entries']} · {rate} · {stats['total_r']:+.2f}R"


def build_report(date_iso: str, timeframe: str, state: dict) -> str:
    """One table for every market, rather than a block each.

    The old report ran twenty-six lines for NSE alone. Nothing here is lost:
    entries, win rate and total for both sides, and the gap between them.
    """
    date_line = pd.Timestamp(date_iso).strftime("%d %b %Y").upper()
    lines = [f"PAPER vs BACKTEST · {date_line}", ""]

    rows = []
    for market, label in MARKETS:
        for frame in TIMEFRAMES:
            paper = paper_day_stats(state, date_iso, market, frame)
            reference = backtest_day_stats(date_iso, frame, market)
            if paper is None and reference is None:
                continue
            gap = (
                f"{paper['total_r'] - reference['total_r']:+.2f}R"
                if paper and reference
                else "-"
            )
            rows.append((f"{label} {frame}", side_text(paper), side_text(reference), gap))

    if not rows:
        return f"PAPER vs BACKTEST · {date_line}\n\nNothing closed on this date."

    width = max(len(r[0]) for r in rows)
    paper_width = max(max(len(r[1]) for r in rows), len("paper"))
    backtest_width = max(max(len(r[2]) for r in rows), len("backtest"))
    lines.append(
        f"{'':<{width}}  {'paper':<{paper_width}}  {'backtest':<{backtest_width}}  gap"
    )
    for name, paper, reference, gap in rows:
        lines.append(
            f"{name:<{width}}  {paper:<{paper_width}}  {reference:<{backtest_width}}  {gap}"
        )

    lines.extend([
        "",
        "Gap is paper minus backtest. Persistent negatives mean the",
        "backtest is optimistic, not that paper was unlucky.",
    ])
    return "\n".join(lines)


def post_report(message: str) -> None:
    webhook = os.getenv(WEBHOOK_ENV, "").strip() or os.getenv(FALLBACK_WEBHOOK_ENV, "").strip()
    if not webhook:
        print(f"Neither {WEBHOOK_ENV} nor {FALLBACK_WEBHOOK_ENV} is configured; skipping send.")
        return
    response = requests.post(webhook, json={"content": message}, timeout=15)
    response.raise_for_status()
    print("Paper trading report posted.")


def run_report(args: argparse.Namespace) -> None:
    date_iso = args.date or pd.Timestamp.now(tz=IST).date().isoformat()
    message = build_report(date_iso, args.timeframe, load_state())
    print(message)
    if not args.dry_run:
        post_report(message)


def main() -> None:
    args = parse_args()
    if args.report:
        run_report(args)
    else:
        run_tick(args)


if __name__ == "__main__":
    main()
