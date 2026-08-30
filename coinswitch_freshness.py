"""Why some CoinSwitch symbols come back with stale candles.

require_fresh_ohlcv rejects a 30m candle older than 65 minutes, and a
handful of symbols - ETH, XRP, DOGE among them - keep tripping it, so the
scanner quietly falls back to an exchange the user does not chart. This
prints what the venue actually returns for those symbols next to symbols
that are fine, so the cause is read rather than guessed.

    python coinswitch_freshness.py
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

import scanner as sc
from config import COINSWITCH_API_BASE_URL

IST = sc.ZoneInfo("Asia/Kolkata")

# The ones that keep failing, then a control group that does not.
SUSPECT = ["ETHUSD", "XRPUSD", "DOGE/USDT", "BCHUSD", "STORJ/USDT", "GOOGLXUSD"]
CONTROL = ["BTCUSDT", "SOLUSD", "AAPLXUSD"]


def signed_get(path, params):
    path_query, headers = sc.sign_coinswitch_request("GET", path, params)
    response = requests.get(
        f"{COINSWITCH_API_BASE_URL}{path_query}", headers=headers, timeout=25
    )
    response.raise_for_status()
    return response.json()


def as_ist(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(IST)


def describe(symbol, exchange):
    contract = sc.coinswitch_symbol(symbol)
    print(f"{symbol}  ->  {contract}")

    for interval, label in (("30", "30m"), ("1", "1m")):
        try:
            payload = signed_get(
                "/trade/api/v2/futures/klines",
                {"exchange": exchange, "symbol": contract,
                 "interval": interval, "limit": 5},
            )
            # The venue sends start_time as a string, so coerce before
            # sorting or comparing - "9" sorts after "10" otherwise.
            candles = sorted(
                payload.get("data") or [], key=lambda c: int(c["start_time"])
            )
        except Exception as error:
            print(f"    {label} klines: {str(error)[:70]}")
            continue

        if not candles:
            print(f"    {label} klines: none returned")
            continue

        newest = candles[-1]
        newest_ms = int(newest["start_time"])
        age = (time.time() * 1000 - newest_ms) / 60000
        print(f"    {label} klines: {len(candles)} candles, newest starts "
              f"{as_ist(newest_ms):%H:%M:%S} IST ({age:.1f} min ago), "
              f"volume {newest.get('volume')}")
        starts = [as_ist(int(c["start_time"])).strftime("%H:%M") for c in candles]
        print(f"    {label} starts: {' '.join(starts)}")

    try:
        payload = signed_get(
            "/trade/api/v2/futures/ticker", {"exchange": exchange, "symbol": contract}
        )
        entry = (payload.get("data") or {}).get(exchange) or {}
        stamp = entry.get("timestamp")
        stamp = int(stamp) if stamp is not None else None
        when = f"{as_ist(stamp):%H:%M:%S} IST" if stamp else "no timestamp"
        lag = f"{(time.time() * 1000 - stamp) / 60000:.1f} min" if stamp else "?"
        print(f"    ticker: last {entry.get('last_price')} at {when} (lag {lag})")
    except Exception as error:
        print(f"    ticker: {str(error)[:70]}")
    print()


def show_top_up(symbol, timeframe="30m"):
    """What the scanner actually ends up with, after the rebuild.

    Pins the timeframe: scanner.TIMEFRAME defaults to 4h, so without
    this the line reported a 4h series while everything above it was
    30m, which made the comparison meaningless.
    """
    previous, sc.TIMEFRAME = sc.TIMEFRAME, timeframe
    try:
        candles = sc.fetch_coinswitch_ohlcv(symbol)
    except Exception as error:
        print(f"    scanner sees: {str(error)[:70]}")
        return
    finally:
        sc.TIMEFRAME = previous
    if not candles:
        print("    scanner sees: nothing")
        return
    newest = int(candles[-1][0])
    age = (time.time() * 1000 - newest) / 60000
    tail = " ".join(as_ist(int(c[0])).strftime("%H:%M") for c in candles[-4:])
    print(f"    scanner sees: {len(candles)} candles, newest "
          f"{as_ist(newest):%H:%M} IST ({age:.1f} min ago) [{tail}]")


def main() -> None:
    if not sc.is_coinswitch_configured():
        print("No CoinSwitch credentials visible.")
        return

    exchange = sc.get_env_or_config("COINSWITCH_EXCHANGE", sc.COINSWITCH_EXCHANGE)
    now = datetime.now(IST)
    print(f"exchange {exchange}, local clock {now:%Y-%m-%d %H:%M:%S} IST")
    # The lookback is only real if the venue honours the limit we ask for.
    for want in (500, 1500):
        try:
            payload = signed_get(
                "/trade/api/v2/futures/klines",
                {"exchange": exchange, "symbol": "BTCUSDT",
                 "interval": "30", "limit": want},
            )
            got = len(payload.get("data") or [])
            span = got * 30 / 60 / 24
            print(f"  asked {want} 30m candles, served {got} ({span:.1f} days)")
        except Exception as error:
            print(f"  asked {want}: {str(error)[:70]}")
        time.sleep(1.0)
    print(f"require_fresh_ohlcv rejects a 30m candle older than "
          f"{(sc.TIMEFRAME_SECONDS['30m'] * 2 + 300) / 60:.0f} minutes")
    print()

    print("SUSPECT - these keep failing the freshness check")
    print()
    for symbol in SUSPECT:
        describe(symbol, exchange)
        show_top_up(symbol)
        print()
        time.sleep(0.8)

    print("CONTROL - these do not")
    print()
    for symbol in CONTROL:
        describe(symbol, exchange)
        show_top_up(symbol)
        print()
        time.sleep(0.8)


if __name__ == "__main__":
    main()
