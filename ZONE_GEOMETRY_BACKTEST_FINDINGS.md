# Should Victus move to v7's zone geometry? — Not on this evidence, but it is closer than the first run said.

> **Superseded 2026-09-06.** The first run scored a v7 that had a bug in it, and
> at a history depth too short to exercise one of the two fixes. Both corrected
> below. The revised answer is at the end.

Run 2026-09-05 with `zone_geometry_backtest.py`. 42 crypto symbols, 30m, up to
3,000 bars each (~62 days), one identical trade simulator across all four arms.

## Result

```
arm       trades    win%    expR   NET R   totNET   stop%  cost/R   age  amb
atr          886    72.5   0.374   0.051     45.4    0.35    0.29    49  151
wick0        894    66.4   0.288   0.036     32.3    0.60    0.17    47   88
wick5        911    66.4   0.284   0.015     13.7    0.55    0.18    47  104
v7full       639    62.8   0.232   0.039     24.9    0.71    0.14    46   40
```

`atr` is production today. `wick0` is the pivot candle's own wick — the version
already reverted. `wick5` is v7's geometry (near edge = closest close within ±5
bars). `v7full` adds v7's other three changes: wick-break, touch-restarting
freshness clock, weakest-first eviction.

NET is after the 0.10% crypto round trip and 0.05% stop slippage that
`daily_backtest_summary` uses. Everything else — pivots, ATR, overlap filter,
history depth, age gate, over-touch veto, entry, stop, exit — is held constant,
so a difference between rows is attributable to what the arm name says.

**The current geometry wins gross and net. v7's geometry is the weakest arm on
net expectancy.**

## The prediction that failed

Before running this I argued that the earlier wick revert failed because
`pine_wick_zones_experimental.pine` used `base_extra = 0`, and that v7's ±5
window would fix it. That was wrong in the way that matters:

* `wick5` vs `wick0` on win rate: **66.4% vs 66.4%** — identical.
* On net expectancy `wick5` is **worse** (0.015 vs 0.036).
* The ±5 window tightened the median stop only 0.60% → 0.55%.

Matching the shape Shiva draws by hand did not improve the alerts. Zone *shape*
and alert *edge* are separate claims and I had been treating them as one.

## The caveat that cuts the other way

`atr`'s lead is not robust to how unresolvable bars are treated. It produces the
most of them — 151 of 886, 17%, versus 40 for `v7full` — because a 0.35% stop and
a 0.35% target both sit inside a single 30m candle far more often.

```
arm       amb  net R (amb=0)  net R (amb=loss)  net R (amb=win)
atr       151          0.051            -0.119            0.222
wick0      88          0.036            -0.062            0.135
wick5     104          0.015            -0.099            0.129
v7full     40          0.039            -0.024            0.102
```

Score every ambiguous bar as a loss and `atr` becomes the **worst** arm and
`v7full` the best. The headline ranking holds only under the neutral and
favourable readings. That is a genuine weakness in the evidence, not a reason to
switch — nothing here makes a case *for* v7 either.

## The finding worth more than the question asked

Costs eat **83–95% of gross edge on every arm**:

```
atr      gross 0.374 -> net 0.051   86% eaten
wick0    gross 0.288 -> net 0.036   87% eaten
wick5    gross 0.284 -> net 0.015   95% eaten
v7full   gross 0.232 -> net 0.039   83% eaten
```

At a 0.35% median stop the round trip alone is **0.29R per trade**. Stop width is
a far bigger lever on net outcome than zone geometry, and `daily_backtest_summary`
already says so in its own comment at line 1269. Widening stops, or targeting
beyond 1R, is where the return on effort is — not in redrawing boxes.

## Decision

**Keep the ATR band in the scanner. v7 stays the chart indicator.**

Two things from v7 are worth porting on their own merits, independent of
geometry, because they are bug fixes rather than changes of opinion:

1. `zones[:] = zones[-HISTORY_OF_ZONES_TO_KEEP:]` in `build_zones` drops the
   **oldest** zone when full — the same FIFO fault v7 fixed. It throws away
   exactly the old untouched zones the strategy says are strongest.
2. The freshness clock (`too_young_to_alert`) measures from `created_idx` only
   and never restarts on a touch, so a zone that price keeps working can still
   qualify once it is old enough.

Neither changes zone shape. Both could be tested with this same harness.

## Limits of this test

* In-sample; every arm scored on the history that shaped it.
* 30m only. `config.TIMEFRAME` is 4h and 4h was **not** tested.
* Bar-resolution fills; same-bar stop+target recorded as ambiguous, not guessed.
* One venue (kucoinfutures), not the live scanner's venue routing.
* Fixed 1R target and 24-bar hold — simpler than the live exit rules, so absolute
  numbers are not live P&L. The comparison between arms is the usable part.
* The `atr` arm was verified to reproduce `scanner.qualify_wick_zone` exactly
  (77 zones on BTC, zero mismatches) before any of this was run.

## Reproducing

```bash
python zone_geometry_backtest.py --bars 3000 --symbols 45 --timeframe 30m
```

Writes `zone_geometry_backtest_results_net.json`. Imports `scanner` and `config`
read-only; touches nothing in the live alert path.


---

# Revision, 2026-09-06

Two things were wrong with the run above.

**1. It scored a buggy v7.** `Shiva_Indicator_v7.pine` used `close` for the zone's
near edge where it should use the body edge, `math.max/min(open, close)`. A wick
ends at the body. Close alone is right only when the pivot candle points the
helpful way, and every reference example coincided except EX1 — a supply pivot on
a red candle, where close sat 368 points below the drawn box. Fixed in the Pine and
added here as the `wick5_close` arm so the cost of the bug is a number.

**2. 62 days could not exercise the eviction fix.** The first harness also dropped
broken zones from its list, while production keeps them (`zones[-60:]`), so the
cap was never reached. Harness now mirrors production, and the run is 187 days.

## Result — 42 symbols, 30m, up to 9,000 bars

```
arm          trades   win%    expR   NET R   totNET   stop%  cost/R   age  amb
atr            1213   72.7   0.374   0.054     65.2    0.35    0.29    50  211
atr_evict      1212   72.7   0.375   0.054     65.6    0.35    0.29    50  210
atr_clock      1157   72.9   0.377   0.058     67.1    0.35    0.29    53  207
atr_both       1156   72.9   0.377   0.058     67.5    0.35    0.29    54  206
wick0          1220   66.6   0.286   0.025     30.2    0.56    0.18    48  142
wick5_close    1232   66.0   0.275   0.014     17.7    0.54    0.18    48  147
wick5          1232   67.5   0.296   0.014     16.9    0.51    0.20    48  168
v7full          855   64.7   0.262   0.055     46.7    0.64    0.16    47   65
```

## Fix 1 — drop the weakest zone, not the oldest: real, but immaterial

Eviction fires and picks a different victim **100% of the time**, yet the result
barely moves: 1213 -> 1212 trades, 65.2 -> 65.6 total net R. The zones it drops are
already spent, so neither choice would have produced a trade. Port it as a
correctness fix — it is what makes old untouched zones survive on the chart — but
expect no P&L change.

## Fix 2 — freshness clock restarts on every touch: a small, consistent win

Net expectancy 0.054 -> 0.058 (+7%), win rate 72.7% -> 72.9%, and it gets there by
**removing** 56 trades rather than adding any. Median age at entry rises 50 -> 53
bars. Held at both 62 and 187 days. Port it.

## Geometry — the answer weakened

`v7full` is now **level with the ATR band on net expectancy** (0.055 vs 0.054) and
it is far more robust, because it does not depend on the one assumption this test
cannot check:

```
arm          trades   amb%  net(amb=0)  net(amb=loss)  net(amb=win)
atr            1213   17.4       0.054         -0.120         0.228
atr_clock      1157   17.9       0.058         -0.121         0.237
wick5          1232   13.6       0.014         -0.123         0.150
v7full          855    7.6       0.055         -0.021         0.131
```

`atr` resolves 17.4% of its trades inside a single candle where the stop and the
target both sit — a 0.35% stop against a 0.35% target. Those are scored neutral and
cannot be checked at bar resolution. `v7full` has 7.6%, less than half, because its
stop is nearly twice as wide.

Score the collisions as losses and `v7full` is the only arm anywhere near break
even (-0.021 against -0.120). Score them neutral or favourably and the ATR family
wins on volume: 1,156 trades for 67.5 total R against 855 for 46.7.

Note the geometry alone is not what does this. `wick5` on its own is the weakest
arm at 0.014. `v7full`'s standing comes from the **wick break rule** killing zones
earlier, plus the freshness clock — not from the box shape.

## Revised decision

* **Port the freshness clock restart.** Small, consistent, free, no geometry change.
* **Port the weakest-first eviction** as a correctness fix, expecting no P&L effect.
* **Leave the geometry alone for now** — but "v7 is worse" is no longer supported.
  It is level per trade, lower in volume, and materially more robust. The way to
  settle that is `paper_trading.py` forward and out-of-sample, not another backtest
  of the same history.
* Costs still eat 83-95% of gross edge everywhere. Stop width remains the biggest
  lever in this system, ahead of any of the above.
