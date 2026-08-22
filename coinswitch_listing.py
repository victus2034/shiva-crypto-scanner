"""Check which watchlist symbols CoinSwitch actually lists as contracts.

A symbol CoinSwitch does not list is not an error you would ever see: the
scanner falls through to the next exchange and builds the zone from a book
you are not charting. This asks CoinSwitch for its instrument list once and
names every watchlist symbol that is missing from it.

    python coinswitch_listing.py
"""
from __future__ import annotations

import argparse

import requests

import scanner as sc
from config import COINSWITCH_API_BASE_URL


# The futures instrument list has moved between paths; try each and use the
# first that answers, so a rename does not silently report everything absent.
# 24h volume for every contract at once, so discovery does not need 1400
# candle requests.
TICKER_PATHS = (
    "/trade/api/v2/futures/ticker24hr",
    "/trade/api/v2/futures/tickers",
    "/trade/api/v2/futures/ticker",
)

LAST_LISTING_PAYLOAD = []

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


def describe_instrument_payload(payload, limit=2):
    """Show what the instrument list carries, in case volume is already there."""
    samples = []

    def walk(node, key_hint=None):
        if len(samples) >= limit:
            return
        if isinstance(node, dict):
            if any(isinstance(node.get(k), str) for k in ("symbol", "s", "name")) or (
                isinstance(key_hint, str) and looks_like_contract(key_hint)
            ):
                samples.append((key_hint, node))
                return
            for key, value in node.items():
                walk(value, key)
        elif isinstance(node, list):
            for item in node:
                walk(item, key_hint)

    walk(payload)
    for key, entry in samples:
        fields = ", ".join(f"{k}={str(v)[:18]}" for k, v in list(entry.items())[:14])
        print(f"  sample {key or ''}: {fields}")


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
                payload = response.json()
                symbols = collect_symbols(payload)
                if symbols:
                    print(f"  {path} {params or '{}'} -> {len(symbols)} contracts")
                    LAST_LISTING_PAYLOAD.append(payload)
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


def collect_volumes(payload):
    """Map contract name to 24h quote volume, however the venue spells it."""
    volumes = {}
    volume_keys = ("quote_volume", "quoteVolume", "volume_24h", "turnover", "volume", "v")

    def walk(node, key_hint=None):
        if isinstance(node, dict):
            name = None
            for key in ("symbol", "s", "name"):
                if isinstance(node.get(key), str):
                    name = node[key].upper()
                    break
            if name is None and isinstance(key_hint, str) and looks_like_contract(key_hint):
                name = key_hint.upper()
            if name:
                for key in volume_keys:
                    if key in node:
                        try:
                            volumes[name] = float(node[key])
                        except (TypeError, ValueError):
                            continue
                        break
            for key, value in node.items():
                walk(value, key)
        elif isinstance(node, list):
            for item in node:
                walk(item, key_hint)

    walk(payload)
    return volumes


def discover(listed):
    """Contracts CoinSwitch trades heavily that the watchlist does not hold."""
    exchange = sc.get_env_or_config("COINSWITCH_EXCHANGE", sc.COINSWITCH_EXCHANGE)
    volumes = {}
    for path in TICKER_PATHS:
        for params in ({"exchange": exchange}, {}):
            try:
                volumes = collect_volumes(coinswitch_get(path, params))
            except Exception as error:
                print(f"  {path} {params or '{}'} -> {str(error)[:60]}")
                continue
            if volumes:
                print(f"  {path} {params or '{}'} -> volume for {len(volumes)} contracts")
                return volumes
            print(f"  {path} {params or '{}'} -> 200 but no volumes parsed")
    return {}


def report_candidates(listed, held_contracts):
    print()
    print("LOOKING FOR HIGH-VOLUME CONTRACTS NOT ON THE WATCHLIST", flush=True)
    volumes = discover(listed)
    if not volumes:
        print("  no bulk ticker endpoint answered; showing what the instrument")
        print("  list itself carries, so the next attempt can use the right field:")
        if LAST_LISTING_PAYLOAD:
            describe_instrument_payload(LAST_LISTING_PAYLOAD[0])
        # The per-symbol ticker exists but rejects an empty query. Ask it for
        # one contract so its shape is on record.
        exchange = sc.get_env_or_config("COINSWITCH_EXCHANGE", sc.COINSWITCH_EXCHANGE)
        try:
            probe = coinswitch_get(
                "/trade/api/v2/futures/ticker", {"exchange": exchange, "symbol": "BTCUSDT"}
            )
            print(f"  single-symbol ticker works: {str(probe)[:300]}")
        except Exception as error:
            print(f"  single-symbol ticker probe -> {str(error)[:90]}")
        return

    candidates = sorted(
        ((name, vol) for name, vol in volumes.items() if name not in held_contracts),
        key=lambda item: item[1],
        reverse=True,
    )
    print()
    print(f"TOP 25 BY 24H VOLUME, NOT CURRENTLY SCANNED ({len(candidates)} candidates)")
    print(f"  {'contract':<20}{'24h volume':>20}")
    for name, vol in candidates[:25]:
        print(f"  {name:<20}{vol:>20,.0f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Also rank contracts the watchlist does not hold.",
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
        report_candidates(listed, {contract for _, contract in present + absent})


if __name__ == "__main__":
    main()
