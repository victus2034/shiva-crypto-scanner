"""Stage pings for zone alerts that were already delivered.

Watches only zones that a real scanner alert already announced, and
reports how price is behaving relative to that alert's own recorded
entry and stop. It never re-derives levels, never scans for new
candidates, and never writes to the alert records the backtest reads.

Stages (one ping each, forward-only):
  1 GET READY     price within APPROACH_THRESHOLD_PCT of entry, entry
                  not yet reached
  2 ENTRY NOW     entry reached, under NEAR_SL_FRACTION of planned risk
                  consumed
  3 LATE/NEAR SL  entry reached, most of the planned risk already gone

Deliberately silent when the trade is no longer worth taking: price has
bounced back past entry into profit (entering now would sit far from the
locked stop), or the stop is already hit.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, time as datetime_time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf


IST = ZoneInfo("Asia/Kolkata")
WEBHOOK_ENV = "DISCORD_ENTRY_CONFIRM_WEBHOOK_URL"
STATE_PATH = Path(__file__).with_name("entry_confirm_state.json")
ALERT_RECORDS = {
    "30m": Path(__file__).with_name("nse_alert_records_30m.jsonl"),
    "4h": Path(__file__).with_name("nse_alert_records.jsonl"),
}
BAR_MINUTES = {"30m": 30, "4h": 240}

# Fire the approach ping while price is still this close to - but has not
# yet reached - the recorded entry. Wide enough to survive the gap between
# scans; the ping is only a cue to place the order at the recorded entry,
# so it never shifts where the trade is actually taken.
APPROACH_THRESHOLD_PCT = 0.10
# Past this share of the planned entry-to-stop distance, the trade is
# reported as late rather than as a clean entry.
NEAR_SL_FRACTION = 0.5
# Matches daily_backtest_summary.ENTRY_WAIT_BARS so a zone stops being
# watched exactly when the backtest stops counting it as fillable.
WATCH_BARS = 3

TRADE_START = datetime_time(9, 15)
# The user stops trading at 15:10, so a ping after that is noise.
TRADE_END = datetime_time(15, 10)

STAGE_READY = 1
STAGE_ENTRY = 2
STAGE_LATE = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeframe", choices=sorted(ALERT_RECORDS), default="30m")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--ignore-session",
        action="store_true",
        help="Skip the market-hours guard (testing only).",
    )
    return parser.parse_args()


def in_trading_session(now: pd.Timestamp) -> bool:
    if now.weekday() >= 5:
        return False
    return TRADE_START <= now.time() <= TRADE_END


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def load_watched_alerts(timeframe: str, now: pd.Timestamp) -> list[dict]:
    """Alerts still inside their fillable window, newest occurrence wins."""
    path = ALERT_RECORDS[timeframe]
    if not path.exists():
        return []

    window = pd.Timedelta(minutes=BAR_MINUTES[timeframe] * WATCH_BARS)
    watched: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("timeframe") != timeframe:
            continue
        delivered = pd.to_datetime(record.get("delivered_at_utc"), errors="coerce", utc=True)
        if pd.isna(delivered):
            continue
        delivered = delivered.tz_convert(IST)
        if now - delivered > window or delivered > now:
            continue
        entry = pd.to_numeric(record.get("planned_entry"), errors="coerce")
        stop = pd.to_numeric(record.get("stop_price"), errors="coerce")
        if pd.isna(entry) or pd.isna(stop) or entry <= 0:
            continue
        record["_entry"] = float(entry)
        record["_stop"] = float(stop)
        record["_delivered"] = delivered
        watched[watch_key(record)] = record
    return list(watched.values())


def watch_key(record: dict) -> str:
    return (
        f"{str(record.get('symbol', '')).upper()}|{record.get('timeframe')}|"
        f"{record.get('side')}|{float(record['_entry']):.4f}|{float(record['_stop']):.4f}"
    )


def fetch_prices(symbols: list[str]) -> dict[str, float]:
    """Latest traded price per symbol, including the forming candle."""
    if not symbols:
        return {}
    try:
        raw = yf.download(
            tickers=" ".join(symbols),
            period="1d",
            interval="15m",
            auto_adjust=False,
            progress=False,
            threads=True,
            group_by="column",
        )
    except Exception as error:
        print(f"price fetch failed: {error}")
        return {}
    if raw is None or raw.empty:
        return {}

    closes = raw["Close"] if "Close" in raw else raw
    if isinstance(closes, pd.Series):
        closes = closes.to_frame(symbols[0])

    prices: dict[str, float] = {}
    for symbol in symbols:
        if symbol not in closes:
            continue
        series = pd.to_numeric(closes[symbol], errors="coerce").dropna()
        if not series.empty:
            prices[symbol] = float(series.iloc[-1])
    return prices


def risk_progress(price: float, entry: float, stop: float, side: str) -> float:
    """Share of the planned entry-to-stop distance already consumed.

    0.0 sits exactly at entry, 1.0 at the stop, and negative means price
    has moved past entry into profit.
    """
    risk = abs(entry - stop)
    if risk <= 0:
        return 0.0
    direction = 1.0 if side == "long" else -1.0
    return -direction * (price - entry) / risk


def classify(price: float, record: dict, reached_entry: bool) -> tuple[int | None, bool]:
    """Return (stage, reached_entry) for the current price."""
    entry = record["_entry"]
    stop = record["_stop"]
    progress = risk_progress(price, entry, stop, record.get("side", "long"))

    if progress >= 1.0:
        return None, True
    if progress >= NEAR_SL_FRACTION:
        return STAGE_LATE, True
    if progress >= 0.0:
        return STAGE_ENTRY, True
    if reached_entry:
        # Bounced back past entry: the locked stop is now far away, so
        # taking it here would risk much more than the alert planned.
        return None, True
    if abs(price - entry) / entry * 100.0 <= APPROACH_THRESHOLD_PCT:
        return STAGE_READY, False
    return None, False


def format_ping(stage: int, price: float, record: dict) -> str:
    entry = record["_entry"]
    stop = record["_stop"]
    side = "BUY" if record.get("side") == "long" else "SELL"
    score = record.get("score")
    score_text = f" | {int(score)}/10" if score is not None else ""
    stop_pct = abs(entry - stop) / entry * 100.0
    progress = risk_progress(price, entry, stop, record.get("side", "long"))
    symbol = display_symbol(record.get("symbol", ""))

    if stage == STAGE_READY:
        away = abs(price - entry) / entry * 100.0
        head = f"👀 GET READY | {symbol} | {side}{score_text}"
        detail = f"Entry {entry:.2f}  ·  now {price:.2f} ({away:.2f}% away)"
        tail = f"SL {stop:.2f} | {stop_pct:.2f}%"
    elif stage == STAGE_ENTRY:
        head = f"🎯 ENTRY NOW | {symbol} | {side}{score_text}"
        detail = f"Entry {entry:.2f}  ·  now {price:.2f}"
        tail = f"SL {stop:.2f} | {stop_pct:.2f}%  ·  {progress * 100:.0f}% of risk used"
    else:
        head = f"⚠️ LATE · NEAR SL | {symbol} | {side}{score_text}"
        detail = f"Entry {entry:.2f}  ·  now {price:.2f}"
        tail = f"SL {stop:.2f} | {stop_pct:.2f}%  ·  {progress * 100:.0f}% of risk used"
    return "\n".join([head, detail, tail])


def display_symbol(symbol: str) -> str:
    text = str(symbol).strip().upper()
    return text[:-3] if text.endswith(".NS") else text


def send_ping(message: str) -> bool:
    webhook = os.getenv(WEBHOOK_ENV, "").strip()
    if not webhook:
        print(f"{WEBHOOK_ENV} is not configured; skipping send.")
        return False
    try:
        response = requests.post(webhook, json={"content": message}, timeout=15)
        response.raise_for_status()
        return True
    except requests.RequestException as error:
        print(f"entry-confirm ping failed: {error}")
        return False


def prune_state(state: dict, active_keys: set[str]) -> dict:
    return {key: value for key, value in state.items() if key in active_keys}


def main() -> None:
    args = parse_args()
    now = pd.Timestamp.now(tz=IST)
    if not args.ignore_session and not in_trading_session(now):
        print(f"Outside trading window ({now:%Y-%m-%d %H:%M} IST); nothing to do.")
        return

    watched = load_watched_alerts(args.timeframe, now)
    if not watched:
        print("No alerts inside their entry window.")
        return

    state = load_state()
    prices = fetch_prices(sorted({record["symbol"] for record in watched}))

    for record in watched:
        key = watch_key(record)
        price = prices.get(record["symbol"])
        if price is None:
            continue

        entry_state = state.get(key, {})
        reached_entry = bool(entry_state.get("reached_entry", False))
        last_stage = int(entry_state.get("stage", 0))

        stage, reached_entry = classify(price, record, reached_entry)
        entry_state["reached_entry"] = reached_entry

        if stage is not None and stage > last_stage:
            message = format_ping(stage, price, record)
            if args.dry_run:
                print(message + "\n")
                entry_state["stage"] = stage
            elif send_ping(message):
                entry_state["stage"] = stage
        state[key] = entry_state

    state = prune_state(state, {watch_key(record) for record in watched})
    if not args.dry_run:
        save_state(state)


if __name__ == "__main__":
    main()
