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

Every ping from one run goes out as a single digest. Posted one message
per symbol, a busy run buried the channel under dozens of separate blocks
and the few that mattered were impossible to pick out.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import time as datetime_time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

from config import DELTA_LISTED_SYMBOLS, MAX_DISTANCE_PCT, WATCHLIST

# Only crypto is checked against its watchlist. The NSE side has no
# authoritative one here - nse_config carries a FALLBACK_WATCHLIST used when
# the live universe cannot be fetched, so filtering on it would drop real
# alerts for symbols that are perfectly valid.
CRYPTO_WATCHLIST_SET = {str(symbol).upper() for symbol in WATCHLIST}


IST = ZoneInfo("Asia/Kolkata")
WEBHOOK_ENV = "DISCORD_ENTRY_CONFIRM_WEBHOOK_URL"
STATE_PATH = Path(__file__).with_name("entry_confirm_state.json")
ALERT_RECORDS = {
    "nse": {
        "30m": Path(__file__).with_name("nse_alert_records_30m.jsonl"),
        "4h": Path(__file__).with_name("nse_alert_records.jsonl"),
    },
    "crypto": {
        "30m": Path(__file__).with_name("crypto_alert_records_30m.jsonl"),
        "4h": Path(__file__).with_name("crypto_alert_records.jsonl"),
    },
}
BAR_MINUTES = {"30m": 30, "4h": 240}
# Discord rejects anything longer; the digest is split rather than dropped.
MAX_MESSAGE_CHARS = 1900

# Fire the approach ping while price is still this close to - but has not
# yet reached - the recorded entry. The ping is only a cue to place the
# order at the recorded entry, so it never shifts where the trade is taken.
#
# Matched to the distance that fires an alert in the first place. At 0.10
# against an alert window of 0.20 there was a dead band: an alert would be
# delivered at, say, 0.15% away and then never ping at all unless price
# happened to close to within 0.10%. Crypto lives in that band - it moves
# far enough between polls to step over it - which is why the channel
# carried NSE pings and no crypto ones.
APPROACH_THRESHOLD_PCT = float(
    os.getenv("VICTUS_APPROACH_THRESHOLD_PCT", MAX_DISTANCE_PCT)
)
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


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    # Both by default: the user watches 30m and 4h together, so covering
    # one silently halves the channel.
    parser.add_argument(
        "--timeframe", choices=["30m", "4h", "both"], default="both"
    )
    parser.add_argument(
        "--market",
        choices=["nse", "crypto", "all"],
        default="crypto",
        help="Which alert records to watch. Crypto covers xStocks too.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--ignore-session",
        action="store_true",
        help="Skip the market-hours guard (testing only).",
    )
    return parser.parse_args(argv)


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


def load_watched_alerts(
    market: str, timeframe: str, now: pd.Timestamp, records_path=None
) -> list[dict]:
    """Alerts still inside their fillable window, newest occurrence wins.

    records_path points this at a different log - paper_trading uses it to read
    the shadow-geometry alerts, which are written by the scanner but never sent.
    """
    path = records_path or ALERT_RECORDS[market][timeframe]
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
        # A symbol dropped from the watchlist keeps pinging for as long as its
        # last alert stays fillable - twelve hours on 4h - and broker_label
        # would call it CoinSwitch, because that is what anything outside the
        # Delta list resolves to. Sending someone to the wrong exchange is
        # worse than saying nothing, and the symbol was dropped on purpose.
        if market == "crypto" and str(record.get("symbol", "")).upper() not in CRYPTO_WATCHLIST_SET:
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
        record["_market"] = market
        watched[watch_key(record)] = record
    return list(watched.values())


def watch_key(record: dict) -> str:
    """Identify a zone, not a particular delivery of it.

    The same zone is re-alerted every scan, and its edges drift in the
    far decimals as ATR moves with each new candle: one BANKINDIA level
    came through as 141.17203103 and then 141.17210107. Four fixed
    decimals split those into two keys, so the same trade was watched -
    and pinged - twice in one digest. Six significant figures is a
    thousand times finer than any real zone is wide, so distinct levels
    still get distinct keys.
    """
    symbol = str(record.get("symbol", "")).upper()
    entry = f"{float(record['_entry']):.6g}"
    stop = f"{float(record['_stop']):.6g}"
    return f"{symbol}|{record.get('timeframe')}|{record.get('side')}|{entry}|{stop}"


def price_decimals(value: float, market: str = "crypto") -> int:
    """Crypto runs from 77,000 to 0.00002; two decimals suits neither.

    NSE stays at two throughout - that is how the exchange quotes and how
    the alerts have always read, and varying it by price would make one
    channel print the same kind of instrument three different ways.
    """
    if market == "nse":
        return 2
    value = abs(float(value))
    if value >= 100:
        return 2
    if value >= 1:
        return 3
    if value >= 0.01:
        return 5
    return 8


def fetch_crypto_prices(symbols: list[str]) -> dict[str, float]:
    """Latest crypto price per symbol, from the same venue chain as the scan.

    Imported lazily: the NSE-only path must not pay for ccxt's exchange
    loading, and a crypto venue being unreachable must not stop NSE pings.
    """
    if not symbols:
        return {}
    try:
        import scanner
    except Exception as error:
        print(f"crypto price fetch unavailable: {error}")
        return {}

    prices: dict[str, float] = {}
    for symbol in symbols:
        try:
            ohlcv, exchange_name = scanner.fetch_symbol_ohlcv(symbol)
            candle_close = float(ohlcv[-1][4])
            price, _ = scanner.live_ticker_price(exchange_name, symbol, candle_close)
            prices[symbol] = float(price)
        except Exception as error:
            print(f"{symbol} price unavailable: {str(error)[:80]}")
    return prices


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


STAGE_HEADINGS = {
    STAGE_ENTRY: "🎯 ENTRY NOW",
    STAGE_LATE: "⚠️ LATE · NEAR SL",
    STAGE_READY: "👀 GET READY",
}
# Entry first: it is the only stage that asks for an action right now.
STAGE_ORDER = [STAGE_ENTRY, STAGE_LATE, STAGE_READY]


def broker_label(record: dict) -> str | None:
    """Where to go and place this trade.

    Only crypto has a venue choice: an NSE symbol is not on either book,
    so tagging it would be noise. Delta lists what it lists and everything
    else on the watchlist is reached through CoinSwitch, which is why the
    fallback is unconditional rather than a second lookup.
    """
    if record.get("_market") != "crypto":
        return None
    symbol = str(record.get("symbol", "")).strip().upper()
    return "Delta" if symbol in DELTA_LISTED_SYMBOLS else "CoinSwitch"


def format_line(stage: int, price: float, record: dict) -> str:
    """One line per alert. Three lines each turned a busy run into a wall."""
    entry = record["_entry"]
    stop = record["_stop"]
    side = "BUY" if record.get("side") == "long" else "SELL"
    score = record.get("score")
    score_text = f" {int(score)}/10" if score is not None else ""
    stop_pct = abs(entry - stop) / entry * 100.0
    progress = risk_progress(price, entry, stop, record.get("side", "long"))
    symbol = display_symbol(record.get("symbol", ""))
    places = price_decimals(entry, record.get("_market", "crypto"))

    head = f"`{symbol}` {side}{score_text}"
    levels = f"{entry:.{places}f} → {price:.{places}f}"
    stop_text = f"SL {stop:.{places}f} ({stop_pct:.2f}%)"

    broker = broker_label(record)
    venue = f" · {broker}" if broker else ""

    if stage == STAGE_READY:
        away = abs(price - entry) / entry * 100.0
        return f"{head} · {levels} · {away:.2f}% away · {stop_text}{venue}"
    return f"{head} · {levels} · {stop_text} · {progress * 100:.0f}% risk used{venue}"


def build_digest(pings: list[tuple[int, str]], now: pd.Timestamp) -> list[str]:
    """Group a run's pings into as few messages as Discord allows."""
    if not pings:
        return []

    sections = []
    for stage in STAGE_ORDER:
        lines = [line for stage_id, line in pings if stage_id == stage]
        if lines:
            heading = f"**{STAGE_HEADINGS[stage]}**"
            sections.append(heading + "\n" + "\n".join(lines))

    header = f"__Entry watch · {now:%H:%M} IST__"
    messages, current = [], header
    for section in sections:
        candidate = current + "\n\n" + section
        if len(candidate) > MAX_MESSAGE_CHARS and current != header:
            messages.append(current)
            current = section
        else:
            current = candidate
    messages.append(current)

    # A single section can still outgrow one message on a busy day.
    split: list[str] = []
    for message in messages:
        while len(message) > MAX_MESSAGE_CHARS:
            cut = message.rfind("\n", 0, MAX_MESSAGE_CHARS)
            cut = cut if cut > 0 else MAX_MESSAGE_CHARS
            split.append(message[:cut])
            message = message[cut:].lstrip("\n")
        if message:
            split.append(message)
    return split


def display_symbol(symbol: str) -> str:
    text = str(symbol).strip().upper()
    if text.endswith(".NS"):
        return text[:-3]
    try:
        import scanner

        return scanner.display_symbol(text)
    except Exception:
        return text


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


def crypto_alert_window_open(now: pd.Timestamp) -> bool:
    """Same 08:00-01:00 IST window the crypto scanner alerts in.

    A ping is only useful if the alert behind it could have been
    posted, and following the scanner keeps one rule in one place.
    """
    try:
        import scanner

        return scanner.in_alert_window(now.to_pydatetime())
    except Exception:
        return True


def markets_for(choice: str) -> list[str]:
    return ["nse", "crypto"] if choice == "all" else [choice]


def timeframes_for(choice: str) -> list[str]:
    return ["30m", "4h"] if choice == "both" else [choice]


def main() -> None:
    args = parse_args()
    now = pd.Timestamp.now(tz=IST)

    watched: list[dict] = []
    for market in markets_for(args.market):
        # Crypto never closes, so the 09:15-15:10 guard is an NSE rule and
        # applying it everywhere would silence crypto for most of the day.
        if market == "nse" and not args.ignore_session and not in_trading_session(now):
            print(f"NSE outside trading window ({now:%Y-%m-%d %H:%M} IST); skipping.")
            continue
        if (
            market == "crypto"
            and not args.ignore_session
            and not crypto_alert_window_open(now)
        ):
            print("Crypto outside the 08:00-01:00 IST window; skipping.")
            continue
        for timeframe in timeframes_for(args.timeframe):
            watched.extend(load_watched_alerts(market, timeframe, now))

    if not watched:
        print("No alerts inside their entry window.")
        return

    state = load_state()
    prices = fetch_prices(
        sorted({r["symbol"] for r in watched if r["_market"] == "nse"})
    )
    prices.update(
        fetch_crypto_prices(
            sorted({r["symbol"] for r in watched if r["_market"] == "crypto"})
        )
    )

    pings: list[tuple[int, str]] = []
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

        # Forward-only: a symbol reports each stage once, never on every
        # run, which is what turned a handful of trades into a wall of
        # near-identical messages.
        if stage is not None and stage > last_stage:
            pings.append((stage, format_line(stage, price, record)))
            entry_state["stage"] = stage
        state[key] = entry_state

    messages = build_digest(pings, now)
    if not messages:
        print("Nothing new to report.")
    for message in messages:
        if args.dry_run:
            print(message + "\n")
        elif not send_ping(message):
            # The digest did not land, so nothing in it may be marked sent.
            print("digest not delivered; stages left unmarked for the next run.")
            return

    state = prune_state(state, {watch_key(record) for record in watched})
    if not args.dry_run:
        save_state(state)


if __name__ == "__main__":
    main()
