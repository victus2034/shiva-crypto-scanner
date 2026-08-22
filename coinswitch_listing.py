"""Check which watchlist symbols CoinSwitch actually lists as contracts.

A symbol CoinSwitch does not list is not an error you would ever see: the
scanner falls through to the next exchange and builds the zone from a book
you are not charting. This asks CoinSwitch for its instrument list once and
names every watchlist symbol that is missing from it.

With --discover it also ranks the contracts the watchlist does not hold by
24h volume, so symbols worth adding surface the same way thin ones do.

    python coinswitch_listing.py --discover
"""
from __future__ import annotations

import argparse
import time

import requests

import scanner as sc
from config import COINSWITCH_API_BASE_URL


# The futures instrument list has moved between paths; try each and use the
# first that answers, so a rename does not silently report everything absent.
CANDIDATE_PATHS = (
    "/trade/api/v2/futures/instrument_info",
    "/trade/api/v2/futures/instruments",
    "/trade/api/v2/futures/symbols",
    "/trade/api/v2/futures/exchange_info",
)


def looks_like_contract(text):
    upper = str(text).upper()
    return len(upper) >= 5 and upper.isalnum() and ("USD" in upper or "INR" in upper)


def collect_symbols(payload):
    """Pull contract names out of whatever shape the endpoint returns."""
    found = set()

    def walk(node, key_hint=None):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and key.lower() in {"symbol", "base_symbol", "name"}:
                    found.add(value.upper())
                else:
                    walk(value, key)
            # Some responses key the map by the contract name itself. Only
            # keys that read like a contract count, or envelope keys such as
            # "data" would be collected as instruments.
            for key, value in node.items():
                if isinstance(value, dict) and looks_like_contract(key):
                    found.add(key.upper())
        elif isinstance(node, list):
            for item in node:
                walk(item, key_hint)
        elif isinstance(node, str) and key_hint in {"symbols", "data"} and looks_like_contract(node):
            found.add(node.upper())

    walk(payload)
    return found


def fetch_listing():
    exchange = sc.get_env_or_config("COINSWITCH_EXCHANGE", sc.COINSWITCH_EXCHANGE)
    for path in CANDIDATE_PATHS:
        for params in ({"exchange": exchange}, {}):
            try:
                path_query, headers = sc.sign_coinswitch_request("GET", path, params)
                response = requests.get(
                    f"{COINSWITCH_API_BASE_URL}{path_query}", headers=headers, timeout=20
                )
                if response.status_code != 200:
                    print(f"  {path} {params or '{}'} -> HTTP {response.status_code}")
                    continue
                symbols = collect_symbols(response.json())
                if symbols:
                    print(f"  {path} {params or '{}'} -> {len(symbols)} contracts")
                    return symbols
                print(f"  {path} {params or '{}'} -> 200 but no contracts parsed")
            except Exception as error:
                print(f"  {path} {params or '{}'} -> {str(error)[:70]}")
    return set()


def nearby_contracts(base, listed, limit=4):
    """Contracts that look like the same instrument under another name.

    A symbol can be absent because the venue does not trade it at all, or
    because it trades it under a different string. Only the second is worth
    fixing in code, and the two look identical without this.
    """
    base = str(base).upper()
    if len(base) < 3:
        return []
    matches = sorted(c for c in listed if c.startswith(base))
    return matches[:limit]


def coinswitch_get(path, params):
    path_query, headers = sc.sign_coinswitch_request("GET", path, params)
    response = requests.get(
        f"{COINSWITCH_API_BASE_URL}{path_query}", headers=headers, timeout=25
    )
    response.raise_for_status()
    return response.json()


def ticker_quote_volume(symbol, exchange):
    """24h volume in quote currency for one contract, or None."""
    payload = coinswitch_get(
        "/trade/api/v2/futures/ticker", {"exchange": exchange, "symbol": symbol}
    )
    entry = (payload.get("data") or {}).get(exchange) or {}
    if not entry:
        return None
    for key in ("quote_asset_volume_24h", "quote_volume_24h"):
        if entry.get(key) is not None:
            return float(entry[key])
    base = entry.get("base_asset_volume_24h")
    price = entry.get("last_price")
    if base is None or price is None:
        return None
    return float(base) * float(price)


def is_rate_limited(error):
    response = getattr(error, "response", None)
    return getattr(response, "status_code", None) == 429


def discover(candidates, budget_seconds, delay):
    """Rank contracts by 24h volume, within a time budget.

    CoinSwitch has no bulk ticker - two paths 404 and the third rejects a
    query without a symbol - so this walks the list one contract at a time
    and stops when the budget runs out rather than risking the job timeout.

    Pacing adapts to the venue. A fixed delay either wastes the budget by
    being too slow or wastes it on rejections by being too fast, and the
    first sweeps lost more time to 429s than to the requests themselves:
    every rejection cost a pause and still returned nothing. So the delay
    grows on a rejection and eases back down on a run of successes.
    """
    exchange = sc.get_env_or_config("COINSWITCH_EXCHANGE", sc.COINSWITCH_EXCHANGE)
    deadline = time.monotonic() + budget_seconds
    volumes = {}
    failures = limited = 0
    pace, streak = delay, 0
    for symbol in candidates:
        if time.monotonic() > deadline:
            break
        try:
            volume = ticker_quote_volume(symbol, exchange)
        except Exception as error:
            failures += 1
            if is_rate_limited(error):
                limited += 1
                pace = min(pace * 1.5, 4.0)
                streak = 0
                time.sleep(pace)
                continue
            time.sleep(pace)
            continue

        if volume is not None:
            volumes[symbol] = volume
        streak += 1
        if streak >= 25 and pace > delay:
            pace = max(pace * 0.8, delay)
            streak = 0
        time.sleep(pace)

    complete = time.monotonic() <= deadline
    print(f"  measured {len(volumes)} of {len(candidates)} contracts"
          f" ({failures} failed, {limited} rate limited,"
          f" settled at {pace:.2f}s, {'complete' if complete else 'budget reached'})")
    if not complete or failures:
        print("  a partial sweep ranks only what it reached - treat the list as"
              " a sample, not the venue's top end")
    return volumes


def daily_quote_volumes(symbol, exchange, days=30):
    """Quote volume per day for the last `days` sessions."""
    payload = coinswitch_get(
        "/trade/api/v2/futures/klines",
        {"exchange": exchange, "symbol": symbol, "interval": "1440", "limit": days + 2},
    )
    candles = payload.get("data") or []
    candles = sorted(candles, key=lambda candle: candle["start_time"])[-days:]
    return [float(candle.get("volume") or 0) * float(candle["c"]) for candle in candles]


def verify_candidates(names, delay):
    """A day's volume can be one day of noise. A month cannot.

    For each candidate this reports the week and the month behind the 24h
    figure, the quietest single day, and whether the recent week is running
    ahead of or behind the month - a spike and a steady book look identical
    until you look past one day.
    """
    exchange = sc.get_env_or_config("COINSWITCH_EXCHANGE", sc.COINSWITCH_EXCHANGE)
    print()
    print(f"WEEK AND MONTH BEHIND THE TOP {len(names)} CANDIDATES", flush=True)
    print(f"  {'contract':<20}{'7d volume':>16}{'30d volume':>16}"
          f"{'quietest day':>16}{'dead days':>11}{'week vs month':>15}")
    for name in names:
        try:
            daily = daily_quote_volumes(name, exchange)
        except Exception as error:
            print(f"  {name:<20}{str(error)[:60]}")
            time.sleep(delay * 3)
            continue
        if not daily:
            print(f"  {name:<20}no daily candles")
            time.sleep(delay)
            continue

        week, month = sum(daily[-7:]), sum(daily)
        dead = sum(1 for value in daily if value <= 0)
        quietest = min(daily) if daily else 0.0
        week_rate = (week / min(7, len(daily))) if daily else 0.0
        month_rate = (month / len(daily)) if daily else 0.0
        ratio = (week_rate / month_rate) if month_rate else 0.0
        print(f"  {name:<20}{week:>16,.0f}{month:>16,.0f}{quietest:>16,.0f}"
              f"{dead:>6}/{len(daily):<4}{ratio:>14.2f}x")
        time.sleep(delay)


def report_candidates(listed, held_contracts, budget_seconds, delay):
    # Alphabetical, so a partial sweep is a partial alphabet rather than an
    # arbitrary slice - the report says how far it got either way.
    candidates = sorted(c for c in listed if c not in held_contracts)
    print()
    print(f"RANKING {len(candidates)} CONTRACTS THE WATCHLIST DOES NOT HOLD", flush=True)
    volumes = discover(candidates, budget_seconds, delay)
    if not volumes:
        print("  no volumes returned")
        return

    ranked = sorted(volumes.items(), key=lambda item: item[1], reverse=True)
    print()
    print("TOP 30 BY 24H QUOTE VOLUME, NOT CURRENTLY SCANNED")
    print(f"  {'contract':<20}{'24h quote volume':>22}")
    for name, volume in ranked[:30]:
        print(f"  {name:<20}{volume:>22,.0f}")

    verify_candidates([name for name, _ in ranked[:30]], delay)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Also rank contracts the watchlist does not hold.",
    )
    parser.add_argument(
        "--discover-budget",
        type=float,
        default=1800.0,
        help="Seconds to spend ranking before reporting what was measured.",
    )
    parser.add_argument(
        "--discover-delay",
        type=float,
        default=0.75,
        help="Pause between ticker requests.",
    )
    args = parser.parse_args()

    print(f"CoinSwitch configured: {sc.is_coinswitch_configured()}", flush=True)
    if not sc.is_coinswitch_configured():
        print("No credentials visible - cannot check the listing.")
        return

    print("Looking for the instrument list:", flush=True)
    listed = fetch_listing()
    if not listed:
        print()
        print("No instrument list available - falling back to per-symbol candle probes")
        print("is what volume_audit.py already does; use that report instead.")
        return

    watchlist = sc.active_watchlist()
    print()
    print(f"watchlist: {len(watchlist)} symbols")
    print()

    present, absent = [], []
    for symbol in watchlist:
        contract = sc.coinswitch_symbol(symbol)
        (present if contract in listed else absent).append((symbol, contract))

    print(f"LISTED ON COINSWITCH: {len(present)} of {len(watchlist)}")
    print()
    if absent:
        print(f"NOT LISTED ({len(absent)}) - these fall through to another exchange,")
        print("so their zones come from a book you are not charting:")
        print(f"  {'alert name':<12}{'watchlist symbol':<20}{'asked for':<20}{'listed instead as'}")
        for symbol, contract in absent:
            near = nearby_contracts(sc.display_symbol(symbol), listed)
            print(f"  {sc.display_symbol(symbol):<12}{symbol:<20}{contract:<20}"
                  f"{', '.join(near) if near else '-'}")
    else:
        print("Every watchlist symbol is listed on CoinSwitch.")

    if args.discover:
        report_candidates(
            listed,
            {contract for _, contract in present + absent},
            args.discover_budget,
            args.discover_delay,
        )


if __name__ == "__main__":
    main()
