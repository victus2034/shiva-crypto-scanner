"""How far apart do CoinSwitch and KuCoin price the same candle?

CoinSwitch caps 30m history at 751 candles - 15.6 days - and no start_time
reaches past it, so a month-old 30m zone cannot be found on the book the
user actually charts. KuCoin serves 1500 in one request. Splicing KuCoin's
older candles under CoinSwitch's recent ones would reach thirty days, but
only if the two venues agree on price closely enough that a zone built from
one is still in the right place on the other.

The alert distance is 0.20%, so that is the bar: a symbol whose venues
disagree by more than that cannot be spliced without moving its levels.

    python venue_divergence.py
"""
from __future__ import annotations

import time

import ccxt
import pandas as pd

import scanner as sc


def coinswitch_closes(symbol):
    ohlcv = sc.fetch_coinswitch_ohlcv(symbol)
    if not ohlcv:
        return None
    return pd.Series(
        {int(row[0]): float(row[4]) for row in ohlcv}, dtype="float64"
    )


def kucoin_closes(exchange, symbol):
    pair = f"{sc.display_symbol(symbol)}/USDT"
    if pair not in exchange.markets:
        return None
    bars = exchange.fetch_ohlcv(pair, "30m", limit=1500)
    if not bars:
        return None
    return pd.Series({int(b[0]): float(b[4]) for b in bars}, dtype="float64")


def main() -> None:
    if not sc.is_coinswitch_configured():
        print("No CoinSwitch credentials visible; cannot compare venues.")
        return

    sc.TIMEFRAME = "30m"
    exchange = ccxt.kucoin({"enableRateLimit": True, "timeout": 30000})
    exchange.load_markets()

    watchlist = sc.active_watchlist()
    print(f"comparing {len(watchlist)} symbols on 30m closes", flush=True)
    print()

    rows, missing = [], []
    for symbol in watchlist:
        try:
            a = coinswitch_closes(symbol)
        except Exception as error:
            missing.append((symbol, f"coinswitch: {str(error)[:40]}"))
            time.sleep(0.8)
            continue
        if a is None:
            missing.append((symbol, "coinswitch: no candles"))
            time.sleep(0.8)
            continue
        try:
            b = kucoin_closes(exchange, symbol)
        except Exception as error:
            missing.append((symbol, f"kucoin: {str(error)[:40]}"))
            time.sleep(0.8)
            continue
        if b is None:
            missing.append((symbol, "kucoin: not listed"))
            time.sleep(0.8)
            continue

        shared = a.index.intersection(b.index)
        if len(shared) < 50:
            missing.append((symbol, f"only {len(shared)} shared candles"))
            time.sleep(0.8)
            continue

        diff = ((a[shared] - b[shared]).abs() / b[shared] * 100.0)
        rows.append({
            "symbol": sc.display_symbol(symbol),
            "bars": len(shared),
            "median": float(diff.median()),
            "p95": float(diff.quantile(0.95)),
            "worst": float(diff.max()),
        })
        time.sleep(0.8)

    if not rows:
        print("no symbols could be compared")
        return

    frame = pd.DataFrame(rows).sort_values("median", ascending=False)
    alert_distance = sc.MAX_DISTANCE_PCT
    safe = frame[frame["p95"] <= alert_distance]

    print(f"compared {len(frame)} symbols, {len(missing)} could not be")
    print()
    print(f"A zone spliced from KuCoin sits in the right place only if the two")
    print(f"venues agree to within the alert distance of {alert_distance}%.")
    print()
    print(f"  within {alert_distance}% at the 95th percentile: {len(safe)} of {len(frame)}")
    print()
    print("DIVERGENCE DISTRIBUTION (% difference on the same candle)")
    for q in (0.5, 0.75, 0.9, 0.95):
        print(f"  p{int(q * 100):<3} of symbols: median {frame['median'].quantile(q):.4f}%"
              f"   p95 {frame['p95'].quantile(q):.4f}%")
    print()
    print("WORST 20 - these cannot be spliced without moving their levels")
    print(f"  {'symbol':<12}{'bars':>7}{'median %':>12}{'p95 %':>10}{'worst %':>10}")
    for _, r in frame.head(20).iterrows():
        print(f"  {r['symbol']:<12}{int(r['bars']):>7}{r['median']:>12.4f}"
              f"{r['p95']:>10.4f}{r['worst']:>10.4f}")
    print()
    print("BEST 10 - effectively the same book")
    for _, r in frame.tail(10).iloc[::-1].iterrows():
        print(f"  {r['symbol']:<12}{int(r['bars']):>7}{r['median']:>12.4f}"
              f"{r['p95']:>10.4f}{r['worst']:>10.4f}")

    if missing:
        print()
        print(f"NOT COMPARABLE ({len(missing)})")
        for symbol, why in missing[:30]:
            print(f"  {sc.display_symbol(symbol):<12} {why}")


if __name__ == "__main__":
    main()
