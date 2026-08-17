"""Check whether the rating actually predicts real outcomes, or is just noise.

Computes the same kind of stats the crypto ML model bundle self-reports
(win rate by rating bucket, lift vs baseline, sample size) from real
finalized backtest history, so the rating's calibration can be tracked
over time instead of just trusted on faith.
"""
from __future__ import annotations

import argparse
import json

import pandas as pd

import daily_backtest_summary as daily

DECIDED_RESULTS = {"+0.5R", "+1R", "+2R", "SL"}
WIN_RESULTS = {"+0.5R", "+1R", "+2R"}
R_VALUES = {"SL": -1.0, "+0.5R": 0.5, "+1R": 1.0, "+2R": 2.0}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate whether the zone rating actually predicts real outcomes."
    )
    parser.add_argument("--market", choices=["nse", "crypto", "xstock"], default="nse")
    parser.add_argument("--timeframe", choices=sorted(daily.TIMEFRAME_SETTINGS), default="30m")
    parser.add_argument(
        "--min-sample",
        type=int,
        default=20,
        help="Minimum trades in a rating bucket before its win rate is called reliable.",
    )
    return parser.parse_args()


def load_decided_trades(market: str, timeframe: str) -> pd.DataFrame:
    path = daily.FINALIZED_RECORDS_PATH
    if not path.exists():
        return pd.DataFrame()

    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    market_label, _ = daily.MARKET_LABELS.get(market, (market.upper(), "Symbols"))
    frame = frame[
        (frame["market"] == market_label)
        & (frame["timeframe"] == timeframe)
        & (frame["final_result"].isin(DECIDED_RESULTS))
    ].copy()
    frame["rating"] = pd.to_numeric(frame["rating"], errors="coerce")
    frame["win"] = frame["final_result"].isin(WIN_RESULTS)
    # Use the trade's actual realized R (reflects SL fill slippage) rather
    # than the flat per-outcome map, so this report's avg-R figures match
    # what the daily/weekly summaries actually report.
    recorded_r = pd.to_numeric(frame.get("net_realized_r"), errors="coerce")
    frame["r"] = recorded_r.where(recorded_r.notna(), frame["final_result"].map(R_VALUES))
    return frame


def build_report(frame: pd.DataFrame, market: str, timeframe: str, min_sample: int) -> str:
    market_label, _ = daily.MARKET_LABELS.get(market, (market.upper(), "Symbols"))
    header = f"RATING VALIDATION | {market_label} {timeframe}"
    if frame.empty:
        return f"{header}\n\nNo decided trades available yet."

    baseline_n = len(frame)
    baseline_win_rate = frame["win"].mean() * 100
    baseline_avg_r = frame["r"].mean()

    lines = [
        header,
        "",
        f"Sample: {baseline_n} decided trades (win or SL)",
        f"Baseline win rate: {baseline_win_rate:.1f}%",
        f"Baseline avg R: {baseline_avg_r:+.2f}",
        "",
        "BY RATING",
    ]

    bucket_rows = []
    for rating, group in frame.groupby("rating", dropna=False):
        n = len(group)
        win_rate = group["win"].mean() * 100
        avg_r = group["r"].mean()
        lift = win_rate - baseline_win_rate
        bucket_rows.append((rating, n, win_rate, avg_r, lift))

    bucket_rows.sort(key=lambda row: (pd.isna(row[0]), row[0] if pd.notna(row[0]) else 0))

    for rating, n, win_rate, avg_r, lift in bucket_rows:
        label = f"{int(rating)}/10" if pd.notna(rating) else "Unrated"
        confidence = "reliable" if n >= min_sample else "LOW SAMPLE - not reliable"
        lines.append(
            f"{label} - n={n} | win {win_rate:.1f}% | avg R {avg_r:+.2f} | "
            f"lift {lift:+.1f}pp vs baseline | {confidence}"
        )

    rated_rows = [(r, wr) for r, n, wr, ar, lift in bucket_rows if pd.notna(r)]
    if len(rated_rows) >= 2:
        steps = len(rated_rows) - 1
        increases = sum(
            1 for i in range(1, len(rated_rows)) if rated_rows[i][1] >= rated_rows[i - 1][1]
        )
        verdict = "looks calibrated" if increases == steps else "NOT cleanly calibrated"
        lines.extend(
            [
                "",
                f"Monotonicity: win rate rose or held at {increases}/{steps} rating steps "
                f"({verdict})",
            ]
        )

    reliable_buckets = sum(1 for _, n, _, _, _ in bucket_rows if n >= min_sample)
    lines.extend(
        [
            "",
            f"{reliable_buckets}/{len(bucket_rows)} rating buckets have >= {min_sample} trades. "
            + (
                "Treat this report as a preliminary read, not a verdict, until more buckets clear that bar."
                if reliable_buckets < len(bucket_rows)
                else "Sample sizes are large enough to trust these numbers."
            ),
        ]
    )

    if market == "nse":
        criterion_lines = build_criterion_breakdown(frame, baseline_win_rate, min_sample)
        if criterion_lines:
            lines.extend(["", "BY score_wick_zone CRITERION (which one is actually predictive)", *criterion_lines])

    return "\n".join(lines)


# Mirrors zone_scoring.score_wick_zone's own boolean checks, so each one
# can be judged individually against real outcomes rather than only seeing
# the combined, capped 4-10 total (which can hide a criterion that's
# actually counter-predictive behind ones that aren't).
CRITERIA = {
    "wick_to_body >= 2.5": lambda f: f["wick_to_body"] >= 2.5,
    "wick_atr >= 0.5": lambda f: f["wick_atr"] >= 0.5,
    "departure_atr >= 1.5": lambda f: f["departure_atr"] >= 1.5,
    "departure_atr >= 2.5": lambda f: f["departure_atr"] >= 2.5,
    "touch_count == 0": lambda f: f["touch_count"] == 0,
    "touch_count == 1": lambda f: f["touch_count"] == 1,
}


def build_criterion_breakdown(frame: pd.DataFrame, baseline_win_rate: float, min_sample: int) -> list[str]:
    feature_columns = {"wick_to_body", "wick_atr", "departure_atr", "touch_count"}
    if not feature_columns.issubset(frame.columns):
        return []
    typed = frame.copy()
    for column in feature_columns:
        typed[column] = pd.to_numeric(typed[column], errors="coerce")
    typed = typed.dropna(subset=feature_columns)
    if typed.empty:
        return []

    lines = []
    for label, predicate in CRITERIA.items():
        met = typed[predicate(typed)]
        unmet = typed[~predicate(typed)]
        if met.empty or unmet.empty:
            continue
        met_rate = met["win"].mean() * 100
        unmet_rate = unmet["win"].mean() * 100
        confidence = "reliable" if min(len(met), len(unmet)) >= min_sample else "low sample"
        lines.append(
            f"{label}: met n={len(met)} win {met_rate:.1f}% | "
            f"not-met n={len(unmet)} win {unmet_rate:.1f}% | {confidence}"
        )
    return lines


def main() -> None:
    args = parse_args()
    frame = load_decided_trades(args.market, args.timeframe)
    report = build_report(frame, args.market, args.timeframe, args.min_sample)
    print(report)


if __name__ == "__main__":
    main()
