"""Check which watchlist symbols CoinSwitch actually lists as contracts.

A symbol CoinSwitch does not list is not an error you would ever see: the
scanner falls through to the next exchange and builds the zone from a book
you are not charting. This asks CoinSwitch for its instrument list once and
names every watchlist symbol that is missing from it.

    python coinswitch_listing.py
"""
from __future__ import annotations

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


def main() -> None:
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


if __name__ == "__main__":
    main()
