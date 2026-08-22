"""Rank the crypto/xStock watchlist by traded volume, and report coverage.

Read-only: it sends nothing to Discord and changes no config. The point is
to see which symbols are thin enough to be worth dropping, and to confirm
which venue each symbol's data actually comes from - a level built from a
venue you do not chart is a level you cannot trade against.

    python volume_audit.py --timeframe 30m
"""
from __future__ import annotations

import argparse
import time
from statistics import median

import pandas as pd

import scanner as sc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeframe", default="30m", choices=["30m", "4h"])
    parser.add_argument(
        "--bars",
        type=int,
        default=96,
        help="How many recent candles to measure volume over.",
    )
    parser.add_argument("--delay", type=float, default=0.15, help="Pause between symbols.")
    return parser.parse_args()


def coinswitch_only(symbol: str):
    """Fetch strictly from CoinSwitch, so coverage is measured honestly."""
    return sc.require_fresh_ohlcv(sc.fetch_coinswitch_ohlcv(symbol), "CoinSwitch")


def main() -> None:
    args = parse_args()
    sc.TIMEFRAME = args.timeframe

    print(f"CoinSwitch configured: {sc.is_coinswitch_configured()}", flush=True)
    if not sc.is_coinswitch_configured():
        print("No CoinSwitch credentials visible - the audit would only measure fallbacks.")
        return

    watchlist = sc.active_watchlist()
    print(f"watchlist: {len(watchlist)} symbols, timeframe {args.timeframe}", flush=True)
    print(flush=True)

    rows, missing = [], []
    for symbol in watchlist:
        try:
            ohlcv = coinswitch_only(symbol)
        except Exception as error:
            missing.append((symbol, str(error)[:60]))
            time.sleep(args.delay)
            continue

        frame = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])
        recent = frame.tail(args.bars)
        price = float(recent["close"].iloc[-1])
        # Quote volume, so symbols at very different prices are comparable.
        quote = [float(v) * float(c) for v, c in zip(recent["volume"], recent["close"])]
        traded = [v for v in quote if v > 0]
        rows.append({
            "symbol": sc.display_symbol(symbol),
            "raw": symbol,
            "price": price,
            "median_quote_vol": median(traded) if traded else 0.0,
            "zero_vol_bars": int((recent["volume"] <= 0).sum()),
            "bars": len(recent),
        })
        time.sleep(args.delay)

    if not rows:
        print("no symbols returned data from CoinSwitch")
        return

    df = pd.DataFrame(rows).sort_values("median_quote_vol")
    print(f"CoinSwitch served {len(df)} of {len(watchlist)} symbols", flush=True)
    print()
    print("THINNEST 30 BY MEDIAN VOLUME PER CANDLE (quote currency)")
    print(f"{'symbol':<14}{'price':>14}{'med vol/candle':>18}{'empty bars':>12}")
    for _, r in df.head(30).iterrows():
        print(f"{r['symbol']:<14}{r['price']:>14.6f}{r['median_quote_vol']:>18,.0f}"
              f"{r['zero_vol_bars']:>7}/{r['bars']}")

    print()
    print("DISTRIBUTION")
    for q in (0.10, 0.25, 0.50, 0.75, 0.90):
        print(f"  p{int(q*100):<3} median vol/candle: {df['median_quote_vol'].quantile(q):>16,.0f}")

    print()
    print("SYMBOLS WITH DEAD CANDLES (no trades in some bars)")
    dead = df[df["zero_vol_bars"] > 0].sort_values("zero_vol_bars", ascending=False)
    if dead.empty:
        print("  none - every symbol traded in every candle")
    else:
        for _, r in dead.head(25).iterrows():
            pct = r["zero_vol_bars"] / r["bars"] * 100
            print(f"  {r['symbol']:<14} {r['zero_vol_bars']:>3}/{r['bars']} bars empty ({pct:.0f}%)")

    if missing:
        print()
        print(f"NOT SERVED BY COINSWITCH ({len(missing)}) - these fall back to another venue,")
        print("so their zones come from an order book you are not charting:")
        for symbol, error in missing[:40]:
            print(f"  {sc.display_symbol(symbol):<14} {error}")


if __name__ == "__main__":
    main()
