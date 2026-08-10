from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import daily_backtest_summary as daily


WEEKLY_SENT_REPORTS_PATH = Path(__file__).with_name("weekly_backtest_reports_sent.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post weekly NSE backtest summary.")
    parser.add_argument(
        "--timeframe",
        choices=sorted(daily.TIMEFRAME_SETTINGS),
        default="30m",
        help="Alert timeframe to summarize.",
    )
    parser.add_argument("--week-ending", help="IST week-ending date, YYYY-MM-DD.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def select_week_ending(requested: str | None):
    if requested:
        return pd.Timestamp(requested).date()
    today = datetime.now(tz=daily.IST).date()
    days_since_friday = (today.weekday() - 4) % 7
    return today - timedelta(days=days_since_friday)


def week_bounds(week_ending) -> tuple:
    end = pd.Timestamp(week_ending).date()
    start = end - timedelta(days=end.weekday())
    return start, end


def load_finalized_records(path: Path = daily.FINALIZED_RECORDS_PATH) -> pd.DataFrame:
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
    return pd.DataFrame(rows)


def build_weekly_summary(frame: pd.DataFrame, timeframe: str, week_start, week_end) -> str:
    header = (
        f"NSE {timeframe} WEEKLY BACKTEST | "
        f"{pd.Timestamp(week_start).strftime('%d %b').upper()}-"
        f"{pd.Timestamp(week_end).strftime('%d %b %Y').upper()}"
    )
    if frame.empty:
        return f"{header}\n\nNo finalized daily records."

    frame = frame.copy()
    frame["rating"] = pd.to_numeric(frame["rating"], errors="coerce")
    frame["net_realized_r"] = pd.to_numeric(frame["net_realized_r"], errors="coerce")
    side_counts = frame["side"].value_counts()
    filled = frame[frame["filled"] == True].copy()  # noqa: E712
    outcomes = frame["outcome"].value_counts()
    final_counts = filled["final_result"].value_counts() if not filled.empty else pd.Series(dtype=int)
    entries = len(filled)
    duplicates = int(outcomes.get("zone_cooldown", 0))
    touch = entries + duplicates
    no_touch = int(outcomes.get("zone_not_touched", 0))
    net_r = pd.to_numeric(filled.get("net_realized_r", pd.Series(dtype=float)), errors="coerce").sum()

    lines = [
        header,
        "",
        "OVERVIEW",
        daily.metric("Alerts", len(frame)),
        daily.metric("Stocks", frame["symbol"].nunique()),
        daily.metric("BUY", int(side_counts.get("long", 0))),
        daily.metric("SELL", int(side_counts.get("short", 0))),
        "",
        "EXECUTION",
        daily.metric("Touch", touch),
        daily.metric("No Touch", no_touch),
        *([daily.metric("Duplicates", duplicates)] if duplicates else []),
        daily.metric("Entries", entries),
        "",
        "RESULTS",
        *daily.format_outcome_lines(final_counts),
        "",
        "TOTAL RESULT",
        daily.format_r(net_r),
        "",
        "RATING PERFORMANCE",
        format_weekly_rating_blocks(frame),
    ]

    best = daily.best_symbol_lines(filled, best=True)
    worst = daily.best_symbol_lines(filled, best=False)
    if best:
        lines.extend(["", "BEST", best])
    if worst:
        lines.extend(["", "WORST", worst])
    return "\n".join(lines)


def format_weekly_rating_blocks(frame: pd.DataFrame) -> str:
    blocks = []
    no_entry_ratings: list[str] = []
    for rating in range(4, 11):
        rating_rows = frame[frame["rating"].astype("Int64") == rating]
        if rating_rows.empty:
            continue
        filled = rating_rows[rating_rows["filled"] == True]  # noqa: E712
        final_counts = filled["final_result"].value_counts() if not filled.empty else pd.Series(dtype=int)
        entries = len(filled)
        if entries == 0:
            no_entry_ratings.append(f"{rating}/10")
            continue
        half_r = int(final_counts.get("+0.5R", 0))
        one_r = int(final_counts.get("+1R", 0))
        two_r = int(final_counts.get("+2R", 0))
        stops = int(final_counts.get("SL", 0))
        conflicts = int(final_counts.get("Conflict", 0))
        neither = int(final_counts.get("Neither", 0))
        wins = half_r + one_r + two_r
        detail_parts = []
        if conflicts:
            detail_parts.append(f"Conflict {conflicts}")
        if neither:
            detail_parts.append(f"Neither {neither}")
        line = (
            f"{rating}/10 — {entries} entries | "
            f"{wins}W / {stops}L | {daily.format_win_rate(wins, stops)}"
        )
        if detail_parts:
            line += f" | {', '.join(detail_parts)}"
        blocks.append(line)
    if no_entry_ratings:
        blocks.append(f"No Entries — {', '.join(no_entry_ratings)}")
    return "\n".join(blocks) if blocks else "None"


def weekly_report_key(week_end, timeframe: str) -> str:
    return f"NSE|{timeframe}|{pd.Timestamp(week_end).date().isoformat()}"


def load_sent_reports(path: Path = WEEKLY_SENT_REPORTS_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def mark_sent_report(key: str, path: Path = WEEKLY_SENT_REPORTS_PATH) -> None:
    data = load_sent_reports(path)
    data[key] = datetime.now(tz=daily.IST).isoformat()
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    week_end = select_week_ending(args.week_ending)
    week_start, week_end = week_bounds(week_end)
    frame = load_finalized_records()
    if not frame.empty:
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        frame = frame[
            (frame["market"] == "NSE")
            & (frame["timeframe"] == args.timeframe)
            & (frame["date"] >= week_start)
            & (frame["date"] <= week_end)
        ].copy()

    message = build_weekly_summary(frame, args.timeframe, week_start, week_end)
    print(message)
    if args.dry_run:
        return

    key = weekly_report_key(week_end, args.timeframe)
    if not args.force and key in load_sent_reports():
        print(f"Skipped duplicate weekly report: {key}")
        return
    daily.send_discord_message(message)
    mark_sent_report(key)


if __name__ == "__main__":
    main()
