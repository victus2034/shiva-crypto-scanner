from __future__ import annotations

import argparse
import io
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

import daily_backtest_summary as daily

TRADE_COLUMNS = {
    "date": "Date",
    "display_symbol": "Symbol",
    "side": "Side",
    "rating": "Rating",
    "alert_time": "Alert Time",
    "entry_time": "Entry Time",
    "entry_price": "Entry Price",
    "stop_price": "Stop Price",
    "zone_bottom": "Zone Bottom",
    "zone_top": "Zone Top",
    "outcome": "Outcome",
    "final_result": "Final Result",
    "realized_r": "Realized R",
    "net_realized_r": "Net Realized R",
    "time_to_half_r": "Time to +0.5R",
    "time_to_1r": "Time to +1R",
    "time_to_2r": "Time to +2R",
    "time_to_sl": "Time to SL",
}


WEEKLY_SENT_REPORTS_PATH = Path(__file__).with_name("weekly_backtest_reports_sent.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post weekly backtest summary.")
    parser.add_argument(
        "--market",
        choices=["nse", "crypto", "xstock"],
        default="nse",
        help="Market to summarize.",
    )
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


def expected_nse_sessions(week_start, week_end, now=None) -> set[date]:
    """Return completed NSE sessions that must be represented in a week."""
    now = now or datetime.now(tz=daily.IST)
    last_date = min(pd.Timestamp(week_end).date(), now.date())
    first_date = pd.Timestamp(week_start).date()
    holidays = {
        date.fromisoformat(item.strip())
        for item in os.getenv("NSE_HOLIDAYS", "").split(",")
        if item.strip()
    }
    sessions = set()
    current = first_date
    while current <= last_date:
        if current.weekday() < 5 and current not in holidays:
            if current < now.date() or now.timetz().replace(tzinfo=None) >= daily.NSE_BACKTEST_CLOSE_CUTOFF:
                sessions.add(current)
        current += timedelta(days=1)
    return sessions


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


def build_weekly_summary(
    frame: pd.DataFrame,
    timeframe: str,
    week_start,
    week_end,
    market: str = "nse",
) -> str:
    market_label, asset_label = daily.MARKET_LABELS.get(market, (market.upper(), "Symbols"))
    header = (
        f"{market_label} {timeframe} WEEKLY BACKTEST | "
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
    entries = len(filled)
    duplicates = int(outcomes.get("zone_cooldown", 0))
    touch = entries + duplicates
    no_touch = int(outcomes.get("zone_not_touched", 0))
    # Pending trades (still open - xStock entries never leave this state by
    # design, since outcome resolution isn't built for that market yet) are
    # kept in Touch/Entries but excluded from win/loss RESULTS, shown as
    # "Waiting" instead - matching how the daily report already handles it.
    waiting = int((filled["final_result"] == "Pending").sum()) if not filled.empty else 0
    finalized = (
        filled[~filled["final_result"].isin(["Pending", daily.DATA_QUALITY_AMBIGUOUS])]
        if not filled.empty else filled
    )
    final_counts = finalized["final_result"].value_counts() if not finalized.empty else pd.Series(dtype=int)
    net_r = pd.to_numeric(finalized.get("net_realized_r", pd.Series(dtype=float)), errors="coerce").sum()

    lines = [
        header,
        "",
        "OVERVIEW",
        daily.metric("Alerts", len(frame)),
        daily.metric(asset_label, frame["symbol"].nunique()),
        daily.metric("BUY", int(side_counts.get("long", 0))),
        daily.metric("SELL", int(side_counts.get("short", 0))),
        "",
        "EXECUTION",
        daily.metric("Touch", touch),
        daily.metric("No Touch", no_touch),
        *([daily.metric("Duplicates", duplicates)] if duplicates else []),
        daily.metric("Entries", entries),
        *([daily.metric("Waiting", waiting)] if waiting else []),
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


def weekly_stats_summary(frame: pd.DataFrame, market: str = "nse") -> list[tuple[str, object]]:
    """Overview/execution/results numbers as (label, value) rows for the Excel Summary tab."""
    _, asset_label = daily.MARKET_LABELS.get(market, (market.upper(), "Symbols"))
    if frame.empty:
        return [("Alerts", 0)]
    side_counts = frame["side"].value_counts()
    filled = frame[frame["filled"] == True].copy()  # noqa: E712
    outcomes = frame["outcome"].value_counts()
    entries = len(filled)
    duplicates = int(outcomes.get("zone_cooldown", 0))
    touch = entries + duplicates
    no_touch = int(outcomes.get("zone_not_touched", 0))
    waiting = int((filled["final_result"] == "Pending").sum()) if not filled.empty else 0
    finalized = (
        filled[~filled["final_result"].isin(["Pending", daily.DATA_QUALITY_AMBIGUOUS])]
        if not filled.empty else filled
    )
    final_counts = finalized["final_result"].value_counts() if not finalized.empty else pd.Series(dtype=int)
    net_r = pd.to_numeric(finalized.get("net_realized_r", pd.Series(dtype=float)), errors="coerce").sum()

    rows: list[tuple[str, object]] = [
        ("Alerts", len(frame)),
        (asset_label, int(frame["symbol"].nunique())),
        ("BUY", int(side_counts.get("long", 0))),
        ("SELL", int(side_counts.get("short", 0))),
        ("Touch", touch),
        ("No Touch", no_touch),
        ("Entries", entries),
        ("Total Result", daily.format_r(net_r)),
    ]
    if duplicates:
        rows.insert(5, ("Duplicates", duplicates))
    if waiting:
        rows.append(("Waiting", waiting))
    for label in ["SL", "+0.5R", "+1R", "+2R", "Neither"]:
        count = int(final_counts.get(label, 0))
        if count:
            rows.append((label, count))
    return rows


def build_weekly_workbook(
    frame: pd.DataFrame,
    timeframe: str,
    week_start,
    week_end,
    market: str = "nse",
) -> bytes:
    """Build a two-sheet (Trades, Summary) workbook for the week's entered trades."""
    filled = frame[frame["filled"] == True].copy() if not frame.empty else frame  # noqa: E712
    trades = filled[[column for column in TRADE_COLUMNS if column in filled.columns]].rename(
        columns=TRADE_COLUMNS
    ) if not filled.empty else pd.DataFrame(columns=list(TRADE_COLUMNS.values()))
    if "Date" in trades.columns:
        trades = trades.sort_values(["Date", "Entry Time"], na_position="last")

    summary = pd.DataFrame(weekly_stats_summary(frame, market), columns=["Metric", "Value"])

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        trades.to_excel(writer, sheet_name="Trades", index=False)
        summary.to_excel(writer, sheet_name="Summary", index=False)
    buffer.seek(0)
    return buffer.getvalue()


def weekly_readiness(
    finalized: pd.DataFrame,
    pending: pd.DataFrame,
    week_start,
    week_end,
    market: str = "nse",
    timeframe: str = "30m",
) -> tuple[bool, str]:
    """Prevent a final weekly report while lifecycle rows remain unresolved."""
    unresolved = []
    if not finalized.empty and "final_result" in finalized:
        ambiguous = finalized[finalized["final_result"] == daily.DATA_QUALITY_AMBIGUOUS]
        if not ambiguous.empty:
            unresolved.append(f"data_quality_ambiguous={len(ambiguous)}")

    if market == "nse":
        # NSE trades resolve same-day, so any pending row genuinely means
        # something is still processing (or stuck) - worth withholding for.
        if not pending.empty:
            unresolved.append(f"pending={len(pending)}")
        expected = expected_nse_sessions(week_start, week_end)
        represented = set()
        if not finalized.empty and "date" in finalized:
            represented = {
                pd.Timestamp(value).date()
                for value in finalized["date"].dropna()
            }
        missing_sessions = sorted(expected - represented)
        if missing_sessions:
            unresolved.append(
                "missing_sessions=" + ",".join(item.isoformat() for item in missing_sessions)
            )
    else:
        # Crypto/xstock trade continuously - there's no trading-day session
        # calendar to check against. Readiness just needs the week's final
        # day's report bucket to have closed, mirroring the same 16:30 IST
        # cutoff the daily crypto report already uses.
        if not daily.crypto_report_bucket_ready(week_end, timeframe):
            unresolved.append(f"report_bucket_not_closed={week_end}")

    if unresolved:
        market_label, _ = daily.MARKET_LABELS.get(market, (market.upper(), "Symbols"))
        header = (
            f"{market_label} {pd.Timestamp(week_start).strftime('%d %b').upper()}-"
            f"{pd.Timestamp(week_end).strftime('%d %b %Y').upper()}"
        )
        return False, (
            f"{header} WEEKLY BACKTEST\n\n"
            "INCOMPLETE WEEK - final report withheld.\n"
            f"Unresolved lifecycle rows: {', '.join(unresolved)}.\n"
            "Reconcile pending and ambiguous rows before publishing."
        )
    return True, ""


def format_weekly_rating_blocks(frame: pd.DataFrame) -> str:
    blocks = []
    no_entry_ratings: list[str] = []
    for rating in range(1, 11):
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
        conflicts = int(final_counts.get(daily.DATA_QUALITY_AMBIGUOUS, 0))
        neither = int(final_counts.get("Neither", 0))
        waiting = int(final_counts.get("Pending", 0))
        wins = half_r + one_r + two_r
        detail_parts = []
        if conflicts:
            detail_parts.append(f"Conflict {conflicts}")
        if neither:
            detail_parts.append(f"Neither {neither}")
        if waiting:
            detail_parts.append(f"Waiting {waiting}")
        line = (
            f"{rating}/10 - {entries} entries | "
            f"{wins}W / {stops}L | {daily.format_win_rate(wins, stops)}"
        )
        if detail_parts:
            line += f" | {', '.join(detail_parts)}"
        blocks.append(line)
    if no_entry_ratings:
        blocks.append(f"No Entries - {', '.join(no_entry_ratings)}")
    return "\n".join(blocks) if blocks else "None"


def weekly_report_key(week_end, timeframe: str, market: str = "nse") -> str:
    market_label, _ = daily.MARKET_LABELS.get(market, (market.upper(), "Symbols"))
    return f"{market_label}|{timeframe}|{pd.Timestamp(week_end).date().isoformat()}"


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
    market_label, _ = daily.MARKET_LABELS.get(args.market, (args.market.upper(), "Symbols"))
    week_end = select_week_ending(args.week_ending)
    week_start, week_end = week_bounds(week_end)
    frame = load_finalized_records()
    if not frame.empty:
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        frame = frame[
            (frame["market"] == market_label)
            & (frame["timeframe"] == args.timeframe)
            & (frame["date"] >= week_start)
            & (frame["date"] <= week_end)
        ].copy()

    pending = daily.load_pending_records(
        daily.PENDING_RECORDS_PATH,
        timeframe=args.timeframe,
        market=market_label,
    )
    if not pending.empty and "report_date" in pending:
        pending = pending[
            (pending["report_date"] >= week_start)
            & (pending["report_date"] <= week_end)
        ].copy()

    ready, diagnostic = weekly_readiness(
        frame, pending, week_start, week_end, market=args.market, timeframe=args.timeframe
    )
    if not ready:
        print(diagnostic)
        return

    # Merge still-open trades into the reporting frame so they show as
    # "Waiting" instead of being silently invisible. For NSE this is a
    # no-op in practice (weekly_readiness already withholds the report
    # while any NSE row is pending), but crypto/xstock don't block on
    # pending, so their entered-but-unresolved trades need to be counted.
    combined = pd.concat([frame, pending], ignore_index=True) if not pending.empty else frame

    message = build_weekly_summary(combined, args.timeframe, week_start, week_end, market=args.market)
    print(message)

    workbook_bytes = build_weekly_workbook(
        combined, args.timeframe, week_start, week_end, market=args.market
    )
    filename = (
        f"weekly_backtest_{market_label}_{args.timeframe}_"
        f"{week_start.isoformat()}_to_{week_end.isoformat()}.xlsx"
    )
    print(f"Workbook built: {filename} ({len(workbook_bytes)} bytes)")

    if args.dry_run:
        return

    key = weekly_report_key(week_end, args.timeframe, market=args.market)
    if not args.force and key in load_sent_reports():
        print(f"Skipped duplicate weekly report: {key}")
        return
    daily.send_discord_message_with_attachment(message, filename, workbook_bytes)
    mark_sent_report(key)


if __name__ == "__main__":
    main()
