"""Compare zone GEOMETRIES on the same history, with the same trade rules.

New file. Imports scanner and config read-only and writes nothing they use.
Nothing in the live alert path is touched by running this.

Why this exists: daily_backtest_summary replays *recorded alerts*, so it can
only score the alerts the current geometry actually produced. A different
geometry produces a different set of alerts, so that harness cannot answer
"would v7 have done better". This one rebuilds zones from raw candles under
each geometry, generates the entries each would have fired, and runs both
through one identical trade simulator.

Arms
  atr     production today - a fixed atr * (BOX_WIDTH/10) band on the pivot extreme
  wick0   the pivot candle's own wick and nothing else - what
          pine_wick_zones_experimental.pine did, and what scanner.py's comment
          says was reverted for putting the near edge too far from the level
  wick5   v7 - the wick, with the near edge pulled to the closest close within
          +/- BASE_EXTRA bars of the pivot
  v7full  wick5 plus v7's other three changes: a wick through the far edge kills
          the zone (not a close), the freshness clock restarts on every touch,
          and a full buffer evicts the weakest zone rather than the oldest

Everything else is held constant across arms: pivots, ATR, the overlap filter,
history depth, the minimum-age gate, the over-touch veto, and the entry, stop
and exit rules. Only what is named in each arm differs, so a difference in the
table is attributable.

Honest limits, stated up front:
  * In-sample. Every arm is scored on the same history that shaped it.
  * 30m only. v7 is validated on 30m and nowhere else; config.TIMEFRAME is 4h.
  * Bar-resolution fills. A bar that contains both the stop and the target is
    recorded as ambiguous rather than guessed, matching daily_backtest_summary's
    own refusal to invent an ordering it cannot see.
  * One venue (kucoinfutures) for every symbol, not the venue routing the live
    scanner does.

  python zone_geometry_backtest.py --bars 3000 --symbols 40
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import pandas as pd

import config
import scanner as prod

SWING_LENGTH = config.SWING_LENGTH
ATR_PERIOD = config.ATR_PERIOD
BOX_WIDTH = config.BOX_WIDTH
OVERLAP_ATR = config.OVERLAP_ATR
HISTORY_KEEP = config.HISTORY_OF_ZONES_TO_KEEP
MIN_AGE = config.MIN_ZONE_AGE_CANDLES
MAX_TOUCH_STREAK = config.MAX_CONSECUTIVE_ZONE_TOUCHES
SL_BUFFER_PCT = prod.SL_BUFFER_PCT          # 0.10% beyond the far edge
# Costs matter more than anything else in this comparison. daily_backtest_summary
# says so itself: "the same charge is a much bigger fraction of R on a tight stop
# than a wide one - on these stops it runs near half of R, which is most of the
# gross edge." A geometry that produces tighter stops therefore looks better
# gross and can be worse net, so the headline number here is NET.
try:
    import daily_backtest_summary as _bt
    COST_PCT = _bt.CRYPTO_ROUND_TRIP_COST_PCT
    SLIP_PCT = _bt.SL_FILL_SLIPPAGE_PCT
except Exception:
    COST_PCT, SLIP_PCT = 0.10, 0.05
BASE_EXTRA = 5                              # v7's setting, chosen on chart
MAX_HOLD_BARS = 24                          # daily_backtest_summary's value

def _arm(geometry="atr", base=0, near="body", brk=False, clock=False, evict=False):
    return dict(geometry=geometry, base=base, near=near,
                break_on_wick=brk, clock_restart=clock, keep_weakest=evict)


ARMS = {
    # --- production, and the two v7 bug fixes that do not touch geometry ------
    "atr":         _arm(),
    "atr_evict":   _arm(evict=True),        # drop the weakest zone, not the oldest
    "atr_clock":   _arm(clock=True),        # freshness clock restarts on every touch
    "atr_both":    _arm(evict=True, clock=True),
    # --- geometry ------------------------------------------------------------
    "wick0":       _arm("wick", 0),                     # the version already reverted
    "wick5_close": _arm("wick", 5, near="close"),       # v7 AS SHIPPED - the bug
    "wick5":       _arm("wick", 5, near="body"),        # v7 corrected
    "v7full":      _arm("wick", 5, "body", True, True, True),
}


# ---------------------------------------------------------------- data

def kucoin_symbol(watch_symbol: str) -> str:
    s = watch_symbol.strip().upper()
    if "/" in s:
        base = s.split("/")[0]
    elif s.endswith("USDT"):
        base = s[:-4]
    elif s.endswith("USD"):
        base = s[:-3]
    else:
        base = s
    return f"{base}/USDT:USDT"


CACHE = Path(__file__).with_name(".zone_bt_cache")


def fetch_cached(exchange, symbol, timeframe, want, refresh=False):
    CACHE.mkdir(exist_ok=True)
    key = CACHE / f"{symbol.replace('/', '_').replace(':', '-')}_{timeframe}_{want}.pkl"
    if key.exists() and not refresh:
        try:
            return pd.read_pickle(key)
        except Exception:
            pass
    df = fetch(exchange, symbol, timeframe, want)
    if df is not None:
        df.to_pickle(key)
    return df


def fetch(exchange, symbol: str, timeframe: str, want: int) -> pd.DataFrame | None:
    """Page backwards until `want` bars are in hand or the venue stops giving."""
    ms = exchange.parse_timeframe(timeframe) * 1000
    end = exchange.milliseconds()
    rows: list[list] = []
    for _ in range(40):
        since = end - 1500 * ms
        try:
            batch = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1500)
        except Exception:
            break
        if not batch:
            break
        rows = batch + rows
        end = batch[0][0] - ms
        if len(rows) >= want:
            break
        time.sleep(exchange.rateLimit / 1000.0)
    if len(rows) < 400:
        return None
    seen = {}
    for r in rows:
        seen[r[0]] = r
    rows = [seen[k] for k in sorted(seen)][-want:]
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.reset_index(drop=True)


# ------------------------------------------------------------- geometry

def zone_edges(df, pivot_index, zone_type, geometry, base, pivot_atr, near="body"):
    """Return (top, bottom). The far edge is the extreme either way.

    near="body"  the wick runs from the extreme to max/min(open, close). Correct.
    near="close" what Shiva_Indicator_v7.pine shipped on 2026-09-05. It is right
                 only when the pivot candle happens to point the helpful way - a
                 red candle's close IS its body bottom, so demand survives it and
                 supply does not. EX1's supply pivot is red and close put the near
                 edge 368 points below where the box was actually drawn.
    """
    if geometry == "atr":
        band = float(pivot_atr) * (BOX_WIDTH / 10.0)
        if zone_type == "demand":
            bottom = float(df["low"].iloc[pivot_index])
            return bottom + band, bottom
        top = float(df["high"].iloc[pivot_index])
        return top, top - band

    lo = max(0, pivot_index - base)
    hi = min(len(df) - 1, pivot_index + base)
    window = df.iloc[lo:hi + 1]
    if near == "close":
        body_lo = body_hi = window["close"]
    else:
        body_lo = window[["open", "close"]].min(axis=1)
        body_hi = window[["open", "close"]].max(axis=1)
    if zone_type == "demand":
        bottom = float(window["low"].min())          # far edge  = the extreme
        top = float(body_lo.min())                   # near edge = closest close
        if top <= bottom:
            top = bottom * (1 + 1e-6)
        return top, bottom
    top = float(window["high"].max())
    bottom = float(body_hi.max())
    if bottom >= top:
        bottom = top * (1 - 1e-6)
    return top, bottom


def center(z):
    return (z["top"] + z["bottom"]) / 2.0


def build(df, arm):
    """Rebuild zones bar by bar and emit the entries this arm would have fired.

    Structure mirrors scanner.build_zones so the atr arm reproduces production.
    """
    cfg = ARMS[arm]
    geometry, base, near = cfg["geometry"], cfg["base"], cfg["near"]
    break_on_wick = cfg["break_on_wick"]
    clock_restart = cfg["clock_restart"]
    keep_weakest = cfg["keep_weakest"]
    atr_series = prod.atr(df, ATR_PERIOD)
    if atr_series.isna().all():
        return []
    highs, lows = prod.find_pivots(df, SWING_LENGTH)
    high_set, low_set = set(highs), set(lows)

    live = {"supply": [], "demand": []}
    events = []

    for i in range(SWING_LENGTH, len(df)):
        pivot_index = i - SWING_LENGTH
        zone_type = "supply" if pivot_index in high_set else "demand" if pivot_index in low_set else None
        if zone_type is not None:
            pivot_atr = atr_series.iloc[pivot_index]
            if not pd.isna(pivot_atr):
                top, bottom = zone_edges(df, pivot_index, zone_type, geometry, base, pivot_atr, near)
                new = {
                    "type": zone_type, "top": top, "bottom": bottom,
                    "created_idx": i, "pivot_idx": pivot_index,
                    "atr": float(pivot_atr), "clock": i,
                    "touch_streak": 0, "over_touched": False, "fired": False,
                }
                new["active"] = True
                bucket = live[zone_type]
                thr = float(pivot_atr) * OVERLAP_ATR
                c = center(new)
                # overlap is checked against LIVE zones only, as production does
                if not any(center(z) - thr <= c <= center(z) + thr
                           for z in bucket if z["active"]):
                    bucket.append(new)
                    if len(bucket) > HISTORY_KEEP:
                        if keep_weakest:
                            # weakest = already dead first, then the shortest
                            # untouched run. The zone just created is protected.
                            victim = min(
                                bucket[:-1],
                                key=lambda z: (z["active"], i - z["clock"]),
                            )
                            bucket.remove(victim)
                        else:
                            bucket.pop(0)          # production: drop the oldest

        hi = float(df["high"].iloc[i])
        lo = float(df["low"].iloc[i])
        cl = float(df["close"].iloc[i])

        for zone_type in ("supply", "demand"):
            for z in live[zone_type]:
                if i <= z["created_idx"] or not z["active"]:
                    continue

                far = z["top"] if zone_type == "supply" else z["bottom"]
                if zone_type == "supply":
                    broke = hi >= far if break_on_wick else cl >= far
                else:
                    broke = lo <= far if break_on_wick else cl <= far
                if broke:
                    z["active"] = False      # stays in the list, as production does
                    continue

                touched = hi >= z["bottom"] and lo <= z["top"]
                z["touch_streak"] = z["touch_streak"] + 1 if touched else 0
                if MAX_TOUCH_STREAK > 0 and z["touch_streak"] >= MAX_TOUCH_STREAK:
                    z["over_touched"] = True

                if touched and not z["fired"] and not z["over_touched"]:
                    if i - z["clock"] >= MIN_AGE:
                        z["fired"] = True
                        events.append({
                            "type": zone_type, "idx": i,
                            "top": z["top"], "bottom": z["bottom"],
                            "age": i - z["created_idx"], "atr": z["atr"],
                        })
                if touched and clock_restart:
                    z["clock"] = i

    return events


# ----------------------------------------------------------- simulation

def _net(gross_r, entry, risk, stopped):
    """Gross R minus the round trip, minus stop-fill slippage when stopped."""
    cost_r = (entry * COST_PCT / 100.0) / risk
    slip_r = (entry * SLIP_PCT / 100.0) / risk if stopped else 0.0
    return gross_r - cost_r - slip_r


def simulate(df, ev):
    """One trade, identical rules for every arm. Fill on the touch bar, then
    evaluate from the next bar so nothing inside the fill bar is peeked at."""
    demand = ev["type"] == "demand"
    entry = ev["bottom"] if not demand else ev["top"]
    if demand:
        entry = ev["top"]
        stop = ev["bottom"] * (1 - SL_BUFFER_PCT / 100.0)
    else:
        entry = ev["bottom"]
        stop = ev["top"] * (1 + SL_BUFFER_PCT / 100.0)
    risk = abs(entry - stop)
    if risk <= 0 or entry <= 0:
        return None
    target = entry + risk if demand else entry - risk

    start = ev["idx"] + 1
    end = min(len(df) - 1, ev["idx"] + MAX_HOLD_BARS)
    for j in range(start, end + 1):
        hi = float(df["high"].iloc[j])
        lo = float(df["low"].iloc[j])
        hit_t = hi >= target if demand else lo <= target
        hit_s = lo <= stop if demand else hi >= stop
        if hit_t and hit_s:
            return {"outcome": "ambiguous", "r": 0.0, "net_r": _net(0.0, entry, risk, False),
                    "bars": j - ev["idx"], "stop_pct": risk / entry * 100.0, "age": ev["age"]}
        if hit_t:
            return {"outcome": "win", "r": 1.0, "net_r": _net(1.0, entry, risk, False),
                    "bars": j - ev["idx"], "stop_pct": risk / entry * 100.0, "age": ev["age"]}
        if hit_s:
            return {"outcome": "stop", "r": -1.0, "net_r": _net(-1.0, entry, risk, True),
                    "bars": j - ev["idx"], "stop_pct": risk / entry * 100.0, "age": ev["age"]}
    if end <= start:
        return None
    last = float(df["close"].iloc[end])
    r = (last - entry) / risk if demand else (entry - last) / risk
    return {"outcome": "open", "r": r, "net_r": _net(r, entry, risk, False),
            "bars": end - ev["idx"], "stop_pct": risk / entry * 100.0, "age": ev["age"]}


# --------------------------------------------------------------- report

def summarise(rows):
    if not rows:
        return None
    df = pd.DataFrame(rows)
    decided = df[df["outcome"].isin(["win", "stop"])]
    wins = int((decided["outcome"] == "win").sum())
    stops = int((decided["outcome"] == "stop").sum())
    return {
        "trades": len(df),
        "decided": len(decided),
        "wins": wins,
        "stops": stops,
        "win_rate": (wins / len(decided) * 100.0) if len(decided) else float("nan"),
        "exp_r": float(df["r"].mean()),
        "total_r": float(df["r"].sum()),
        "exp_net_r": float(df["net_r"].mean()),
        "total_net_r": float(df["net_r"].sum()),
        "median_stop_pct": float(df["stop_pct"].median()),
        "median_age": float(df["age"].median()),
        "ambiguous": int((df["outcome"] == "ambiguous").sum()),
        "open": int((df["outcome"] == "open").sum()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=3000)
    ap.add_argument("--symbols", type=int, default=40)
    ap.add_argument("--timeframe", default="30m")
    ap.add_argument("--out", default="zone_geometry_backtest_results.json")
    ap.add_argument("--refresh", action="store_true", help="ignore the on-disk candle cache")
    args = ap.parse_args()

    import ccxt
    exchange = ccxt.kucoinfutures({"enableRateLimit": True})

    watch = list(dict.fromkeys(config.CRYPTO_WATCHLIST))[: args.symbols]
    per_arm = {a: [] for a in ARMS}
    per_symbol = {}
    used, skipped = [], []

    for n, w in enumerate(watch, 1):
        sym = kucoin_symbol(w)
        try:
            df = fetch_cached(exchange, sym, args.timeframe, args.bars, args.refresh)
        except Exception as exc:
            df = None
            print(f"  [{n}/{len(watch)}] {w:12s} fetch error {type(exc).__name__}", flush=True)
        if df is None or len(df) < 400:
            skipped.append(w)
            print(f"  [{n}/{len(watch)}] {w:12s} skipped (no data)", flush=True)
            continue
        used.append(w)
        line = {}
        for arm in ARMS:
            rows = [r for r in (simulate(df, e) for e in build(df, arm)) if r]
            per_arm[arm].extend(rows)
            line[arm] = summarise(rows)
        per_symbol[w] = line
        print(f"  [{n}/{len(watch)}] {w:12s} {len(df):5d} bars  "
              + "  ".join(f"{a}:{(line[a]['trades'] if line[a] else 0):3d}" for a in ARMS), flush=True)

    result = {
        "timeframe": args.timeframe,
        "bars_requested": args.bars,
        "symbols_used": used,
        "symbols_skipped": skipped,
        "settings": {
            "swing_length": SWING_LENGTH, "atr_period": ATR_PERIOD,
            "box_width": BOX_WIDTH, "overlap_atr": OVERLAP_ATR,
            "history_keep": HISTORY_KEEP, "min_age": MIN_AGE,
            "max_touch_streak": MAX_TOUCH_STREAK,
            "sl_buffer_pct": SL_BUFFER_PCT, "base_extra": BASE_EXTRA,
            "max_hold_bars": MAX_HOLD_BARS,
        },
        "overall": {a: summarise(per_arm[a]) for a in ARMS},
        "per_symbol": per_symbol,
    }
    Path(args.out).write_text(json.dumps(result, indent=1), encoding="utf-8")

    print("\n" + "=" * 78)
    print(f"{len(used)} symbols, {args.timeframe}, up to {args.bars} bars each"
          f"   ({len(skipped)} skipped)")
    print("=" * 78)
    hdr = (f"{'arm':8s} {'trades':>7s} {'win%':>7s} {'expR':>7s} {'NET R':>7s} "
           f"{'totNET':>8s} {'stop%':>7s} {'cost/R':>7s} {'age':>5s} {'amb':>4s}")
    print(hdr)
    print("-" * len(hdr))
    for a in ARMS:
        s = result["overall"][a]
        if not s:
            print(f"{a:8s}   no trades")
            continue
        cost_per_r = COST_PCT / s['median_stop_pct']
        print(f"{a:8s} {s['trades']:7d} {s['win_rate']:7.1f} {s['exp_r']:7.3f} "
              f"{s['exp_net_r']:7.3f} {s['total_net_r']:8.1f} {s['median_stop_pct']:7.2f} "
              f"{cost_per_r:7.2f} {s['median_age']:5.0f} {s['ambiguous']:4d}")
    print("\nstop% = median stop distance as % of entry;  age = median bars from")
    print("zone creation to entry;  exp R counts open trades marked to last close.")


if __name__ == "__main__":
    main()
