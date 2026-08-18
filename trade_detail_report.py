"""Full per-trade export and breakdowns, for deciding what to change.

The daily Discord summary is deliberately short. This is the opposite: it
replays every delivered alert through the backtest and writes the whole
trade ledger plus the cuts that actually drive decisions - stop width,
time of day, rating, how far price ran before resolving, and what the
round-trip charges did to each bucket.

    python trade_detail_report.py --timeframe 30m
    python trade_detail_report.py --timeframe 30m --output my_report.xlsx
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

import daily_backtest_summary as backtest


DEFAULT_OUTPUT = Path(__file__).with_name("trade_detail_report.xlsx")
# Bucket edges chosen around the economics rather than round numbers:
# below 0.24% the +0.5R rule cannot clear costs at all, and cost as a share
# of R roughly halves at each step above it.
STOP_BUCKETS = [0.0, 0.24, 0.35, 0.50, 0.75, 1.00, 99.0]
STOP_LABELS = [
    "<0.24 (unprotectable)",
    "0.24-0.35",
    "0.35-0.50",
    "0.50-0.75",
    "0.75-1.00",
    ">1.00",
]
WINS = {"+1R", "+2R"}
DECIDED = {"SL", "+1R", "+2R", backtest.BREAK_EVEN}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeframe", choices=sorted(backtest.TIMEFRAME_SETTINGS), default="30m")
    parser.add_argument("--market", choices=["nse", "crypto", "xstock"], default="nse")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--date", help="Limit to one IST date, YYYY-MM-DD.")
    return parser.parse_args()


def collect(timeframe: str, market: str, only_date: str | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replay every day of delivered alerts, returning filled and unfilled."""
    if market == "nse":
        records_path = backtest.configure_nse_data(timeframe)
    else:
        records_path = backtest.configure_crypto_data(timeframe)
    records = backtest.load_records(records_path, timeframe)
    wanted = {"nse": backtest.MARKET_NSE, "crypto": backtest.MARKET_CRYPTO,
              "xstock": backtest.MARKET_XSTOCK}[market]
    records = records[records["market_class"] == wanted].copy()
    if records.empty:
        return pd.DataFrame(), pd.DataFrame()

    records["date"] = pd.to_datetime(records["event_time_ist"]).dt.date
    if only_date:
        records = records[records["date"] == pd.Timestamp(only_date).date()]

    filled_parts, unfilled_parts = [], []
    for day in sorted(records["date"].unique()):
        day_records = records[records["date"] == day]
        symbols = sorted(day_records["symbol"].unique())
        frames, failures = (
            backtest.fetch_frames(symbols) if market == "nse"
            else backtest.fetch_crypto_frames(symbols)
        )
        if failures:
            print(f"  {day}: {len(failures)} symbols failed to fetch")
        results, duplicates = backtest.run_backtest(day_records, frames, market=market)
        results["date"] = day
        results["duplicates_blocked_that_day"] = duplicates
        filled_parts.append(results[results["filled"] == True])  # noqa: E712
        unfilled_parts.append(results[results["filled"] != True])  # noqa: E712
        print(f"  {day}: {len(day_records)} alerts -> {int((results['filled'] == True).sum())} entries", flush=True)  # noqa: E712

    filled = pd.concat(filled_parts, ignore_index=True) if filled_parts else pd.DataFrame()
    unfilled = pd.concat(unfilled_parts, ignore_index=True) if unfilled_parts else pd.DataFrame()
    return filled, unfilled


def enrich(filled: pd.DataFrame) -> pd.DataFrame:
    if filled.empty:
        return filled
    frame = filled.copy()
    alert_time = pd.to_datetime(frame["event_time_ist"])
    entry_time = pd.to_datetime(frame["entry_time"])
    exit_time = pd.to_datetime(frame["exit_time"])

    frame["display_symbol"] = frame["symbol"].map(backtest.display_symbol)
    frame["alert_hour"] = alert_time.dt.strftime("%H:00")
    frame["entry_hour"] = entry_time.dt.strftime("%H:00")
    frame["mins_alert_to_entry"] = (entry_time - alert_time).dt.total_seconds() / 60
    frame["mins_held"] = (exit_time - entry_time).dt.total_seconds() / 60
    frame["stop_pct"] = (
        (frame["entry_price"] - frame["stop_price"]).abs() / frame["entry_price"] * 100
    )
    frame["stop_bucket"] = pd.cut(
        frame["stop_pct"], bins=STOP_BUCKETS, labels=STOP_LABELS, right=False
    )
    for column, target in (("mins_to_1r", "time_to_1r"), ("mins_to_2r", "time_to_2r")):
        stamps = pd.to_datetime(frame[target], errors="coerce")
        frame[column] = (stamps - entry_time).dt.total_seconds() / 60
    frame["is_win"] = frame["final_result"].isin(WINS)
    frame["is_decided"] = frame["final_result"].isin(DECIDED)
    return frame


def summarise(group: pd.DataFrame) -> dict:
    decided = group[group["is_decided"]]
    wins = int(group["is_win"].sum())
    losses = int((group["final_result"] == "SL").sum())
    gross = pd.to_numeric(group["realized_r"], errors="coerce").sum()
    net = pd.to_numeric(group["net_realized_r"], errors="coerce").sum()
    return {
        "trades": len(group),
        "SL": losses,
        "BE": int((group["final_result"] == backtest.BREAK_EVEN).sum()),
        "+1R": int((group["final_result"] == "+1R").sum()),
        "+2R": int((group["final_result"] == "+2R").sum()),
        "Neither": int((group["final_result"] == "Neither").sum()),
        "Ambiguous": int((group["final_result"] == backtest.DATA_QUALITY_AMBIGUOUS).sum()),
        "win_rate_%": round(wins / len(decided) * 100, 1) if len(decided) else None,
        "gross_R": round(gross, 2),
        "cost_R": round(pd.to_numeric(group.get("cost_r"), errors="coerce").sum(), 2),
        "net_R": round(net, 2),
        "net_R_per_trade": round(net / len(group), 3) if len(group) else None,
        "avg_cost_R": round(pd.to_numeric(group.get("cost_r"), errors="coerce").mean(), 3),
        "avg_MFE_R": round(pd.to_numeric(group.get("mfe_r"), errors="coerce").mean(), 2),
        "avg_MAE_R": round(pd.to_numeric(group.get("mae_r"), errors="coerce").mean(), 2),
        "avg_mins_to_entry": round(group["mins_alert_to_entry"].mean(), 1),
        "avg_mins_held": round(group["mins_held"].mean(), 1),
    }


def breakdown(frame: pd.DataFrame, column: str, label: str) -> pd.DataFrame:
    if frame.empty or column not in frame:
        return pd.DataFrame()
    rows = []
    for key, group in frame.groupby(column, dropna=False, observed=False):
        if not len(group):
            continue
        rows.append({label: key, **summarise(group)})
    out = pd.DataFrame(rows)
    return out.sort_values(label) if not out.empty else out


TRADE_COLUMNS = [
    "date", "display_symbol", "symbol", "side", "rating", "final_result",
    "alert_hour", "event_time_ist", "entry_hour", "entry_time", "exit_time",
    "mins_alert_to_entry", "mins_held",
    "alert_price", "entry_price", "stop_price", "stop_pct", "stop_bucket",
    "target_1_price", "target_2_price", "exit_price",
    "half_r_hit", "target_1_hit", "target_2_hit", "mins_to_1r", "mins_to_2r",
    "mfe_r", "mae_r", "realized_r", "cost_r", "net_realized_r",
    "distance_pct", "zone_bottom", "zone_top",
    "wick_to_body", "wick_atr", "departure_atr", "touch_count",
]


def strip_timezones(frame: pd.DataFrame) -> pd.DataFrame:
    """Excel rejects tz-aware timestamps; times are all IST anyway."""
    out = frame.copy()
    for column in out.columns:
        values = out[column]
        if isinstance(values.dtype, pd.DatetimeTZDtype):
            out[column] = values.dt.tz_localize(None)
        elif values.dtype == object:
            # Object columns can still hold tz-aware Timestamps one by one.
            sample = values.dropna()
            if sample.empty:
                continue
            first = sample.iloc[0]
            if isinstance(first, pd.Timestamp) and first.tzinfo is not None:
                out[column] = values.map(
                    lambda v: v.tz_localize(None)
                    if isinstance(v, pd.Timestamp) and v.tzinfo is not None
                    else v
                )
    return out


def build_workbook(filled: pd.DataFrame, unfilled: pd.DataFrame, output: Path) -> None:
    trades = strip_timezones(filled[[c for c in TRADE_COLUMNS if c in filled.columns]].copy())
    sheets = {
        "Trades": trades.sort_values(["date", "entry_time"]),
        "By Stop Width": breakdown(filled, "stop_bucket", "stop_width"),
        "By Alert Hour": breakdown(filled, "alert_hour", "alert_hour"),
        "By Entry Hour": breakdown(filled, "entry_hour", "entry_hour"),
        "By Rating": breakdown(filled, "rating", "rating"),
        "By Side": breakdown(filled, "side", "side"),
        "By Day": breakdown(filled, "date", "date"),
        "By Symbol": breakdown(filled, "display_symbol", "symbol"),
        "Overall": pd.DataFrame([summarise(filled)]),
    }
    if not unfilled.empty:
        reasons = unfilled["outcome"].value_counts().rename_axis("reason").reset_index(name="count")
        sheets["Unfilled"] = reasons

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, sheet in sheets.items():
            if sheet is None or sheet.empty:
                continue
            strip_timezones(sheet).to_excel(writer, sheet_name=name[:31], index=False)


def print_summary(filled: pd.DataFrame) -> None:
    overall = summarise(filled)
    print()
    print("OVERALL")
    for key, value in overall.items():
        print(f"  {key:<20} {value}")
    for column, title in (
        ("stop_bucket", "BY STOP WIDTH"),
        ("alert_hour", "BY ALERT HOUR"),
        ("rating", "BY RATING"),
        ("side", "BY SIDE"),
    ):
        table = breakdown(filled, column, column)
        if table.empty:
            continue
        print()
        print(title)
        columns = [column, "trades", "SL", "BE", "+1R", "+2R", "win_rate_%",
                   "gross_R", "cost_R", "net_R", "net_R_per_trade"]
        print(table[[c for c in columns if c in table]].to_string(index=False))


def main() -> None:
    args = parse_args()
    print(f"Replaying {args.market} {args.timeframe} alerts...")
    filled, unfilled = collect(args.timeframe, args.market, args.date)
    if filled.empty:
        print("No filled trades found.")
        return
    filled = enrich(filled)
    print_summary(filled)
    build_workbook(filled, unfilled, args.output)
    print()
    print(f"Wrote {args.output} ({len(filled)} trades)")


if __name__ == "__main__":
    main()
