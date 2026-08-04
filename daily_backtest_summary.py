from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, time as datetime_time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

import nse_scanner


IST = ZoneInfo("Asia/Kolkata")
WEBHOOK_ENV = "DISCORD_DAILY_BACKTEST_WEBHOOK_URL"
TIMEFRAME_SETTINGS = {
    "30m": {
        "records": Path(__file__).with_name("nse_alert_records_30m.jsonl"),
        "source_interval": "15m",
        "source_period": "60d",
    },
    "4h": {
        "records": Path(__file__).with_name("nse_alert_records.jsonl"),
        "source_interval": "1h",
        "source_period": "700d",
    },
}

ENTRY_WAIT_BARS = 3
MAX_HOLD_BARS = 24
NSE_BACKTEST_CLOSE_CUTOFF = datetime_time(15, 10)
FIXED_STOP_PCT = 0.5
TARGET_1_R = 1.0
TARGET_2_R = 2.0
COST_TO_COST_TRIGGER_PCT = 0.25
ROUND_TRIP_COST_PCT = 0.25


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Post a clean daily NSE delivered-alert backtest summary."
    )
    parser.add_argument(
        "--timeframe",
        choices=sorted(TIMEFRAME_SETTINGS),
        default="30m",
        help="Alert timeframe to summarize.",
    )
    parser.add_argument("--date", help="IST date to summarize, YYYY-MM-DD.")
    parser.add_argument("--records", type=Path, help="Override alert-record JSONL path.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def configure_nse_data(timeframe: str) -> Path:
    settings = TIMEFRAME_SETTINGS[timeframe]
    nse_scanner.TIMEFRAME = timeframe
    nse_scanner.SOURCE_INTERVAL = settings["source_interval"]
    nse_scanner.SOURCE_PERIOD = settings["source_period"]
    return settings["records"]


def load_records(path: Path, timeframe_filter: str) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    rows: list[dict] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            timeframe = raw.get("timeframe", timeframe_filter)
            if timeframe != timeframe_filter:
                continue
            event_time = pd.Timestamp(raw["delivered_at_utc"])
            if event_time.tzinfo is None:
                event_time = event_time.tz_localize("UTC")
            event_time = event_time.tz_convert("UTC")
            zone_bottom = float(raw["zone_bottom"])
            zone_top = float(raw["zone_top"])
            if zone_bottom > zone_top:
                zone_bottom, zone_top = zone_top, zone_bottom
            side = str(raw["side"]).lower()
            if side not in {"long", "short"}:
                continue
            rows.append(
                {
                    "event_time": event_time,
                    "event_time_ist": event_time.tz_convert(IST),
                    "symbol": str(raw["symbol"]),
                    "side": side,
                    "distance_pct": float(raw["distance_pct"]),
                    "alert_price": float(raw["alert_price"]),
                    "level": float(raw["level"]),
                    "zone_bottom": zone_bottom,
                    "zone_top": zone_top,
                    "body_entry": parse_optional_float(raw.get("body_entry")),
                    "rating": parse_rating(raw.get("score")),
                    "zone_id": (
                        f"{raw['symbol']}|{side}|{zone_bottom:.8f}|{zone_top:.8f}"
                    ),
                    "source_line": line_number,
                }
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            print(f"Skipping bad alert record line {line_number}: {error}")

    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    return frame.drop_duplicates(
        ["event_time", "symbol", "side", "alert_price", "zone_bottom", "zone_top"],
        keep="first",
    ).sort_values(["event_time", "symbol"]).reset_index(drop=True)


def parse_rating(value) -> float:
    if value is None or value == "":
        return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def parse_optional_float(value) -> float:
    if value is None or value == "":
        return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def select_target_date(records: pd.DataFrame, requested: str | None):
    if requested:
        return pd.Timestamp(requested).date()
    if records.empty:
        return pd.Timestamp.now(tz=IST).date()
    return records["event_time_ist"].dt.date.max()


def fetch_frames(symbols: list[str]) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    frames: dict[str, pd.DataFrame] = {}
    failures: dict[str, str] = {}
    for symbol in symbols:
        try:
            raw = nse_scanner.fetch_stock_ohlcv(symbol)
            frames[symbol] = normalize_frame(raw)
        except Exception as error:
            failures[symbol] = str(error)
    return frames, failures


def normalize_frame(raw: pd.DataFrame) -> pd.DataFrame:
    frame = raw.copy()
    if "Datetime" in frame.columns:
        timestamps = pd.to_datetime(frame.pop("Datetime"))
        frame.index = timestamps
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize(IST)
    else:
        frame.index = frame.index.tz_convert(IST)
    frame.index = pd.DatetimeIndex(frame.index).floor("s")
    return frame[["open", "high", "low", "close", "volume"]].sort_index()


def run_backtest(alerts: pd.DataFrame, frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, int]:
    rows = []
    for alert in alerts.to_dict("records"):
        frame = frames.get(alert["symbol"])
        if frame is None or frame.empty:
            rows.append(unfilled(alert, "data_missing"))
            continue

        event_time = pd.Timestamp(alert["event_time_ist"]).floor("s")
        event_index = int(frame.index.searchsorted(event_time, side="right") - 1)
        if event_index < 0:
            rows.append(unfilled(alert, "alert_before_data"))
            continue

        tracking_end_index, close_window_mature = same_day_tracking_end(frame, event_time)
        if not close_window_mature:
            rows.append(unfilled(alert, "immature"))
            continue
        if tracking_end_index is None or tracking_end_index <= event_index:
            rows.append(unfilled(alert, "zone_not_touched"))
            continue

        rows.append(simulate_alert(frame, alert, event_index, tracking_end_index))

    results = pd.DataFrame(rows)
    return apply_same_day_zone_cooldown(results)


def same_day_tracking_end(
    frame: pd.DataFrame,
    event_time: pd.Timestamp,
) -> tuple[int | None, bool]:
    """Return the last same-day candle allowed for NSE backtest evaluation."""
    event_time = event_time.tz_convert(IST)
    cutoff = pd.Timestamp(
        datetime.combine(event_time.date(), NSE_BACKTEST_CLOSE_CUTOFF),
        tz=IST,
    )
    now_ist = pd.Timestamp.now(tz=IST)
    if event_time.date() == now_ist.date() and now_ist < cutoff:
        return None, False

    same_day = frame.index.normalize() == event_time.normalize()
    before_cutoff = frame.index <= cutoff
    positions = [
        index for index, keep in enumerate(same_day & before_cutoff)
        if keep
    ]
    if not positions:
        return None, True
    return positions[-1], True


def simulate_alert(
    frame: pd.DataFrame,
    alert: dict,
    event_index: int,
    tracking_end_index: int,
) -> dict:
    side = alert["side"]
    direction = 1.0 if side == "long" else -1.0
    entry_price = body_entry_price(frame, alert, event_index)
    entry_index = find_entry(frame, event_index, entry_price, tracking_end_index)
    if entry_index is None:
        return unfilled(alert, "zone_not_touched")

    stop = original_stop_price(alert)
    risk = direction * (entry_price - stop)
    if risk <= 0:
        risk = entry_price * FIXED_STOP_PCT / 100.0
        stop = entry_price - direction * risk
    target_1 = entry_price + direction * risk * TARGET_1_R
    target_2 = entry_price + direction * risk * TARGET_2_R
    fee_cover_offset = min(entry_price * ROUND_TRIP_COST_PCT / 100.0, risk * 0.999)
    fee_cover_stop = entry_price + direction * fee_cover_offset
    cost_to_cost_trigger = (
        entry_price + direction * entry_price * COST_TO_COST_TRIGGER_PCT / 100.0
    )
    cost_r = fee_cover_offset / risk

    end_index = tracking_end_index
    target_1_hit = False
    target_2_hit = False
    stopped = False
    cost_to_cost_active = False
    cost_to_cost_exit = False
    outcome = "timeout"
    exit_index = end_index
    max_favorable_r = 0.0
    max_adverse_r = 0.0

    for index in range(entry_index, end_index + 1):
        high = float(frame["high"].iloc[index])
        low = float(frame["low"].iloc[index])
        favorable = high - entry_price if side == "long" else entry_price - low
        adverse = entry_price - low if side == "long" else high - entry_price
        max_favorable_r = max(max_favorable_r, favorable / risk)
        max_adverse_r = max(max_adverse_r, adverse / risk)

        active_stop = fee_cover_stop if cost_to_cost_active else stop
        stop_hit = low <= active_stop if side == "long" else high >= active_stop
        first_target_hit = high >= target_1 if side == "long" else low <= target_1
        second_target_hit = high >= target_2 if side == "long" else low <= target_2
        trigger_hit = (
            high >= cost_to_cost_trigger if side == "long" else low <= cost_to_cost_trigger
        )

        if stop_hit:
            outcome = "cost_to_cost" if cost_to_cost_active else "stopped"
            cost_to_cost_exit = cost_to_cost_active
            stopped = not cost_to_cost_active
            exit_index = index
            break
        if first_target_hit:
            target_1_hit = True
        if second_target_hit:
            target_1_hit = True
            target_2_hit = True
            outcome = "target_2r"
            exit_index = index
            break
        if trigger_hit:
            cost_to_cost_active = True

    if stopped:
        exit_price = stop
        realized_r = -1.0
    elif cost_to_cost_exit:
        exit_price = fee_cover_stop
        realized_r = (direction * (exit_price - entry_price)) / risk
    elif target_2_hit:
        exit_price = target_2
        realized_r = TARGET_2_R
    else:
        exit_price = float(frame["close"].iloc[exit_index])
        realized_r = (direction * (exit_price - entry_price)) / risk
        if target_1_hit:
            outcome = "target_1_then_timeout"

    result = dict(alert)
    result.update(
        {
            "filled": True,
            "entry_time": frame.index[entry_index],
            "entry_price": entry_price,
            "entry_basis": "body",
            "stop_price": stop,
            "target_1_price": target_1,
            "target_2_price": target_2,
            "exit_time": frame.index[exit_index],
            "exit_price": exit_price,
            "bars_held": exit_index - entry_index + 1,
            "target_1_hit": target_1_hit,
            "target_2_hit": target_2_hit,
            "cost_to_cost_exit": cost_to_cost_exit,
            "outcome": outcome,
            "realized_r": realized_r,
            "net_realized_r": realized_r - cost_r,
            "mfe_r": max_favorable_r,
            "mae_r": max_adverse_r,
            "cooldown_blocked": False,
        }
    )
    return result


def body_entry_price(frame: pd.DataFrame, alert: dict, event_index: int) -> float:
    recorded_body_entry = pd.to_numeric(alert.get("body_entry"), errors="coerce")
    if pd.notna(recorded_body_entry):
        return float(recorded_body_entry)

    matched_body_entry = reconstruct_body_entry(frame, alert, event_index)
    if matched_body_entry is not None:
        return matched_body_entry

    # Fallback for old records when the source zone cannot be reconstructed.
    # This remains the near edge of the recorded zone, not the wick extreme.
    return float(alert["zone_top"] if alert["side"] == "long" else alert["zone_bottom"])


def reconstruct_body_entry(frame: pd.DataFrame, alert: dict, event_index: int) -> float | None:
    history = frame.iloc[: event_index + 1].copy()
    if len(history) < nse_scanner.ATR_PERIOD + nse_scanner.SWING_LENGTH * 2:
        return None

    supply_zones, demand_zones = nse_scanner.build_zones(history)
    zone_type = "demand" if alert["side"] == "long" else "supply"
    zones = demand_zones if zone_type == "demand" else supply_zones
    candidates = [
        zone for zone in zones
        if zone["type"] == zone_type and zones_match_alert(zone, alert)
    ]
    if not candidates:
        return None
    best = min(
        candidates,
        key=lambda zone: abs(float(zone["top"]) - float(alert["zone_top"]))
        + abs(float(zone["bottom"]) - float(alert["zone_bottom"])),
    )
    return float(best["body_entry"])


def zones_match_alert(zone: dict, alert: dict) -> bool:
    top = float(zone["top"])
    bottom = float(zone["bottom"])
    alert_top = float(alert["zone_top"])
    alert_bottom = float(alert["zone_bottom"])
    tolerance = max(abs(alert_top - alert_bottom) * 0.05, abs(alert_top) * 0.00005, 0.01)
    return abs(top - alert_top) <= tolerance and abs(bottom - alert_bottom) <= tolerance


def original_stop_price(alert: dict) -> float:
    return float(alert["level"])


def find_entry(
    frame: pd.DataFrame,
    event_index: int,
    entry_price: float,
    tracking_end_index: int,
) -> int | None:
    end_index = min(event_index + ENTRY_WAIT_BARS, tracking_end_index)
    for index in range(event_index + 1, end_index + 1):
        if float(frame["low"].iloc[index]) <= entry_price <= float(frame["high"].iloc[index]):
            return index
    return None


def unfilled(alert: dict, outcome: str) -> dict:
    result = dict(alert)
    result.update(
        {
            "filled": False,
            "entry_time": pd.NaT,
            "entry_price": float("nan"),
            "stop_price": float("nan"),
            "target_1_price": float("nan"),
            "target_2_price": float("nan"),
            "exit_time": pd.NaT,
            "exit_price": float("nan"),
            "bars_held": 0,
            "target_1_hit": False,
            "target_2_hit": False,
            "cost_to_cost_exit": False,
            "outcome": outcome,
            "realized_r": float("nan"),
            "net_realized_r": float("nan"),
            "mfe_r": float("nan"),
            "mae_r": float("nan"),
            "cooldown_blocked": False,
        }
    )
    return result


def apply_same_day_zone_cooldown(results: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if results.empty:
        return results, 0
    frame = results.copy()
    frame["_order"] = range(len(frame))
    accepted: dict[str, list[dict]] = {}
    blocked = 0
    filled = frame[frame["filled"] == True].sort_values(["entry_time", "_order"])  # noqa: E712

    for index, row in filled.iterrows():
        symbol = str(row["symbol"])
        current = row.to_dict()
        previous_trades = accepted.get(symbol, [])
        conflict = any(same_day_overlap(current, previous) for previous in previous_trades)
        if conflict:
            replacement = unfilled(current, "zone_cooldown")
            replacement["cooldown_blocked"] = True
            for key, value in replacement.items():
                frame.at[index, key] = value
            blocked += 1
        else:
            accepted.setdefault(symbol, []).append(current)

    return frame.sort_values("_order").drop(columns="_order"), blocked


def same_day_overlap(current: dict, previous: dict) -> bool:
    current_day = pd.Timestamp(current["entry_time"]).tz_convert(IST).date()
    previous_day = pd.Timestamp(previous["entry_time"]).tz_convert(IST).date()
    if current_day != previous_day:
        return False
    return max(float(current["zone_bottom"]), float(previous["zone_bottom"])) <= min(
        float(current["zone_top"]), float(previous["zone_top"])
    )


def build_summary(
    records: pd.DataFrame,
    target_date,
    results: pd.DataFrame,
    data_failures: dict[str, str],
    cooldown_blocked: int,
    timeframe: str,
) -> str:
    header = f"NSE {timeframe} BACKTEST | {pd.Timestamp(target_date).strftime('%d %b %Y')}"
    if records.empty:
        return (
            f"{header}\n\n"
            "No alerts recorded."
        )

    side_counts = records["side"].value_counts()
    buy_count = int(side_counts.get("long", 0))
    sell_count = int(side_counts.get("short", 0))
    tradable = int((pd.to_numeric(records["rating"], errors="coerce") >= 5).sum())

    filled = results[results["filled"] == True].copy() if not results.empty else pd.DataFrame()  # noqa: E712
    outcome_counts = results["outcome"].value_counts() if not results.empty else pd.Series(dtype=int)
    completed = len(filled)
    net_r = pd.to_numeric(filled.get("net_realized_r", pd.Series(dtype=float)), errors="coerce").sum()
    wins = int(filled.get("target_1_hit", pd.Series(dtype=bool)).sum()) if not filled.empty else 0
    breakeven = int(outcome_counts.get("cost_to_cost", 0))
    stops = int(outcome_counts.get("stopped", 0))
    immature = int(outcome_counts.get("immature", 0))
    not_touched = int(outcome_counts.get("zone_not_touched", 0))
    duplicates = int(outcome_counts.get("zone_cooldown", 0))
    data_missing = int(outcome_counts.get("data_missing", 0)) + int(outcome_counts.get("alert_before_data", 0))
    touched = completed + duplicates

    lines = [
        header,
        f"Alerts {len(records)} | Stocks {records['symbol'].nunique()} | Tradable {tradable}",
        f"BUY {buy_count} | SELL {sell_count}",
        f"Touch {touched} | No touch {not_touched} | Duplicate {duplicates}",
        "",
        f"Closed {completed} | Result {format_r(net_r) if completed else 'waiting'}",
        f"1R {wins} | BE {breakeven} | SL {stops}",
        "",
        format_rating_table(records, results),
    ]
    if immature:
        lines.append(f"Still open {immature}")
    if data_missing:
        lines.append(f"Data missing {data_missing}")
    if data_failures:
        lines.append(f"Data failures {len(data_failures)}")

    best = best_symbol_line(filled, ascending=False)
    worst = best_symbol_line(filled, ascending=True)
    if best:
        lines.extend(["", f"Best {best}"])
    if worst:
        lines.append(f"Worst {worst}")

    lines.extend(["", f"Verdict: {verdict(completed, net_r, wins, stops)}"])
    return "\n".join(lines)


def format_rating_table(records: pd.DataFrame, results: pd.DataFrame) -> str:
    if records.empty:
        return "Rating table: none"

    records_by_rating = rating_counts(records)
    rows = [rating_table_header()]

    if results.empty:
        for rating in range(4, 11):
            alerts = records_by_rating.get(rating, 0)
            rows.append(rating_table_row(rating, alerts, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "N/A"))
        return "Rating breakdown\n```text\n" + "\n".join(rows) + "\n```"

    result_frame = results.copy()
    result_frame["_rating_bucket"] = pd.to_numeric(
        result_frame["rating"], errors="coerce"
    ).astype("Int64")
    for rating in range(4, 11):
        alerts = records_by_rating.get(rating, 0)
        rating_results = result_frame[result_frame["_rating_bucket"] == rating]
        filled = rating_results[rating_results["filled"] == True]  # noqa: E712
        outcomes = rating_results["outcome"].value_counts()
        duplicates = int(outcomes.get("zone_cooldown", 0))
        no_touch = int(outcomes.get("zone_not_touched", 0))
        entries = len(filled)
        touch = entries + duplicates
        breakeven = int(outcomes.get("cost_to_cost", 0))
        half_r = int((pd.to_numeric(filled.get("mfe_r", pd.Series(dtype=float)), errors="coerce") >= 0.5).sum())
        one_r = int(filled.get("target_1_hit", pd.Series(dtype=bool)).sum()) if not filled.empty else 0
        two_r = int(filled.get("target_2_hit", pd.Series(dtype=bool)).sum()) if not filled.empty else 0
        stops = int(outcomes.get("stopped", 0))
        neither = max(0, entries - one_r - breakeven - stops)
        decided_wr = format_win_rate(one_r, stops)
        rows.append(
            rating_table_row(
                rating,
                alerts,
                touch,
                no_touch,
                duplicates,
                entries,
                breakeven,
                half_r,
                one_r,
                two_r,
                stops,
                neither,
                decided_wr,
            )
        )
    return "Rating breakdown\n```text\n" + "\n".join(rows) + "\n```"


def rating_table_header() -> str:
    return (
        "Rate  Alert Touch NoTouch Dup Entry BE .5R 1R 2R SL Neither WR"
    )


def rating_table_row(
    rating: int,
    alerts: int,
    touch: int,
    no_touch: int,
    duplicate: int,
    entries: int,
    breakeven: int,
    half_r: int,
    one_r: int,
    two_r: int,
    stops: int,
    neither: int,
    decided_wr: str,
) -> str:
    return (
        f"{rating:>2}/10 {alerts:>5} {touch:>5} {no_touch:>7} {duplicate:>3} "
        f"{entries:>5} {breakeven:>2} {half_r:>3} {one_r:>2} {two_r:>2} "
        f"{stops:>2} {neither:>7} {decided_wr:>6}"
    )


def rating_counts(records: pd.DataFrame) -> dict[int, int]:
    ratings = pd.to_numeric(records["rating"], errors="coerce").dropna()
    if ratings.empty:
        return {}
    counts = ratings.astype(int).value_counts()
    return {int(score): int(count) for score, count in counts.items() if 4 <= int(score) <= 10}


def format_win_rate(wins: int, stops: int) -> str:
    decided = wins + stops
    if decided == 0:
        return "N/A"
    return f"{wins / decided * 100:.1f}%"


def format_r(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}R"


def best_symbol_line(filled: pd.DataFrame, ascending: bool) -> str:
    if filled.empty or "net_realized_r" not in filled:
        return ""
    ranked = filled.sort_values("net_realized_r", ascending=ascending).head(3)
    parts = []
    for row in ranked.to_dict("records"):
        parts.append(f"{row['symbol']} {format_r(float(row['net_realized_r']))}")
    return " | ".join(parts)


def verdict(completed: int, net_r: float, wins: int, stops: int) -> str:
    if completed < 5:
        return "wait for mature data"
    if net_r > 0 and wins >= stops:
        return "positive"
    if net_r <= 0:
        return "weak"
    return "mixed"


def send_discord_message(message: str) -> None:
    webhook_url = os.getenv(WEBHOOK_ENV, "").strip()
    if not webhook_url:
        raise RuntimeError(f"{WEBHOOK_ENV} is not configured")
    for attempt in range(6):
        response = requests.post(webhook_url, json={"content": message}, timeout=15)
        if response.status_code != 429:
            response.raise_for_status()
            return
        try:
            retry_after = float(response.json().get("retry_after", 1.0))
        except (TypeError, ValueError, requests.JSONDecodeError):
            retry_after = 1.0
        if attempt == 5:
            response.raise_for_status()
        time.sleep(max(0.25, min(retry_after, 30.0)))


def main() -> None:
    args = parse_args()
    default_records = configure_nse_data(args.timeframe)
    records = load_records(args.records or default_records, args.timeframe)
    target_date = select_target_date(records, args.date)
    day_records = (
        records[records["event_time_ist"].dt.date == target_date].copy()
        if not records.empty
        else records
    )

    frames: dict[str, pd.DataFrame] = {}
    data_failures: dict[str, str] = {}
    cooldown_blocked = 0
    results = pd.DataFrame()
    if not day_records.empty:
        frames, data_failures = fetch_frames(sorted(day_records["symbol"].unique()))
        results, cooldown_blocked = run_backtest(day_records, frames)

    message = build_summary(
        day_records,
        target_date,
        results,
        data_failures,
        cooldown_blocked,
        args.timeframe,
    )
    print(message)
    if not args.dry_run:
        send_discord_message(message)


if __name__ == "__main__":
    main()
