from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta, time as datetime_time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

import nse_scanner
import scanner as crypto_scanner


IST = ZoneInfo("Asia/Kolkata")
WEBHOOK_ENV = "DISCORD_DAILY_BACKTEST_WEBHOOK_URL"
TIMEFRAME_SETTINGS = {
    "30m": {
        "nse_records": Path(__file__).with_name("nse_alert_records_30m.jsonl"),
        "crypto_records": Path(__file__).with_name("crypto_alert_records_30m.jsonl"),
        "source_interval": "15m",
        "source_period": "60d",
    },
    "4h": {
        "nse_records": Path(__file__).with_name("nse_alert_records.jsonl"),
        "crypto_records": Path(__file__).with_name("crypto_alert_records.jsonl"),
        "source_interval": "1h",
        "source_period": "700d",
    },
}

ENTRY_WAIT_BARS = 3
MAX_HOLD_BARS = 24
NSE_BACKTEST_CLOSE_CUTOFF = datetime_time(15, 10)
CRYPTO_EVALUATION_HOURS = 6
FIXED_STOP_PCT = 0.5
TARGET_1_R = 1.0
TARGET_2_R = 2.0
HALF_R = 0.5
FINAL_RESULT_R = {
    "SL": -1.0,
    "+0.5R": 0.5,
    "+1R": 1.0,
    "+2R": 2.0,
    "Neither": 0.0,
}
OUTCOME_ORDER = ["SL", "+0.5R", "+1R", "+2R", "Neither"]
SENT_REPORTS_PATH = Path(__file__).with_name("daily_backtest_reports_sent.json")
FINALIZED_RECORDS_PATH = Path(__file__).with_name("daily_backtest_finalized_records.jsonl")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Post a clean daily delivered-alert backtest summary."
    )
    parser.add_argument(
        "--market",
        choices=["nse", "crypto"],
        default="nse",
        help="Market to summarize.",
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
    parser.add_argument("--force", action="store_true", help="Send even if this report key was already sent.")
    return parser.parse_args()


def configure_nse_data(timeframe: str) -> Path:
    settings = TIMEFRAME_SETTINGS[timeframe]
    nse_scanner.TIMEFRAME = timeframe
    nse_scanner.SOURCE_INTERVAL = settings["source_interval"]
    nse_scanner.SOURCE_PERIOD = settings["source_period"]
    return settings["nse_records"]


def configure_crypto_data(timeframe: str) -> Path:
    crypto_scanner.TIMEFRAME = timeframe
    return TIMEFRAME_SETTINGS[timeframe]["crypto_records"]


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


def fetch_crypto_frames(symbols: list[str]) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    frames: dict[str, pd.DataFrame] = {}
    failures: dict[str, str] = {}
    for symbol in symbols:
        try:
            frames[symbol] = normalize_crypto_frame(crypto_fetch_ohlcv(symbol))
        except Exception as error:
            failures[symbol] = str(error)
    return frames, failures


def crypto_fetch_ohlcv(symbol: str):
    last_error = None
    symbol_for_fallback = crypto_scanner.fallback_symbol(symbol)

    primary_exchange = crypto_scanner.EXCHANGES_BY_ID.get(crypto_scanner.PRIMARY_EXCHANGE_ID)
    if primary_exchange is not None:
        try:
            return crypto_scanner.fetch_exchange_ohlcv(primary_exchange, symbol_for_fallback)
        except Exception as error:
            last_error = error

    for exchange in crypto_scanner.EXCHANGES:
        if exchange.id == crypto_scanner.PRIMARY_EXCHANGE_ID:
            continue
        try:
            return crypto_scanner.fetch_exchange_ohlcv(exchange, symbol_for_fallback)
        except Exception as error:
            last_error = error

    if crypto_scanner.is_coinswitch_configured():
        try:
            return crypto_scanner.fetch_coinswitch_ohlcv(symbol)
        except Exception as error:
            last_error = error

    raise RuntimeError(f"all crypto exchanges failed for {symbol}: {last_error}")


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


def normalize_crypto_frame(raw) -> pd.DataFrame:
    frame = pd.DataFrame(raw, columns=["time", "open", "high", "low", "close", "volume"])
    frame["time"] = pd.to_datetime(frame["time"], unit="ms", utc=True).dt.tz_convert(IST)
    frame = frame.set_index("time")
    frame.index = pd.DatetimeIndex(frame.index).floor("s")
    return frame[["open", "high", "low", "close", "volume"]].sort_index()


def run_backtest(
    alerts: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
    market: str = "nse",
) -> tuple[pd.DataFrame, int]:
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

        if market == "crypto":
            tracking_end_index, window_mature = crypto_tracking_end(frame, event_time)
        else:
            tracking_end_index, window_mature = same_day_tracking_end(frame, event_time)
        if not window_mature:
            rows.append(unfilled(alert, "immature"))
            continue
        if tracking_end_index is None or tracking_end_index <= event_index:
            rows.append(unfilled(alert, "zone_not_touched"))
            continue

        rows.append(simulate_alert(frame, alert, event_index, tracking_end_index))

    results = pd.DataFrame(rows)
    return apply_same_day_zone_cooldown(results, market)


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


def crypto_tracking_end(
    frame: pd.DataFrame,
    event_time: pd.Timestamp,
) -> tuple[int | None, bool]:
    """Return a provisional crypto search window after alert time.

    Actual final evaluation is limited to 6 hours after entry. This provisional
    window only gives the entry finder enough future candles to locate entry.
    """
    event_time = event_time.tz_convert(IST)
    provisional_expiry = event_time + timedelta(hours=CRYPTO_EVALUATION_HOURS + 1)
    positions = [
        index for index, timestamp in enumerate(frame.index)
        if timestamp <= provisional_expiry
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

    if is_crypto_symbol(alert.get("symbol", "")):
        crypto_end_index, crypto_window_mature = crypto_entry_tracking_end(frame, entry_index)
        if crypto_end_index is None or crypto_end_index < entry_index:
            return pending_trade(alert, frame, entry_index, entry_price)
        tracking_end_index = min(tracking_end_index, crypto_end_index)
        if not crypto_window_mature:
            return pending_trade(alert, frame, entry_index, entry_price)

    stop = original_stop_price(alert)
    risk = direction * (entry_price - stop)
    if risk <= 0:
        risk = entry_price * FIXED_STOP_PCT / 100.0
        stop = entry_price - direction * risk
    target_half = entry_price + direction * risk * HALF_R
    target_1 = entry_price + direction * risk * TARGET_1_R
    target_2 = entry_price + direction * risk * TARGET_2_R

    end_index = tracking_end_index
    half_r_hit = False
    target_1_hit = False
    target_2_hit = False
    outcome = "Neither"
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

        stop_hit = low <= stop if side == "long" else high >= stop
        half_target_hit = high >= target_half if side == "long" else low <= target_half
        first_target_hit = high >= target_1 if side == "long" else low <= target_1
        second_target_hit = high >= target_2 if side == "long" else low <= target_2

        if outcome == "Neither" and stop_hit:
            outcome = "SL"
            exit_index = index
            break
        if half_target_hit:
            half_r_hit = True
            if outcome == "Neither":
                outcome = "+0.5R"
        if first_target_hit:
            half_r_hit = True
            target_1_hit = True
            outcome = "+1R"
        if second_target_hit:
            half_r_hit = True
            target_1_hit = True
            target_2_hit = True
            outcome = "+2R"
            exit_index = index
            break

    if outcome == "SL":
        exit_price = stop
    elif outcome == "+0.5R":
        exit_price = target_half
    elif outcome == "+1R":
        exit_price = target_1
    elif outcome == "+2R":
        exit_price = target_2
    else:
        exit_price = float(frame["close"].iloc[exit_index])
    realized_r = FINAL_RESULT_R[outcome]

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
            "half_r_hit": half_r_hit,
            "target_1_hit": target_1_hit,
            "target_2_hit": target_2_hit,
            "outcome": outcome,
            "final_result": outcome,
            "realized_r": realized_r,
            "net_realized_r": realized_r,
            "mfe_r": max_favorable_r,
            "mae_r": max_adverse_r,
            "cooldown_blocked": False,
        }
    )
    return result


def crypto_entry_tracking_end(
    frame: pd.DataFrame,
    entry_index: int,
) -> tuple[int | None, bool]:
    expiry = pd.Timestamp(frame.index[entry_index]) + timedelta(hours=CRYPTO_EVALUATION_HOURS)
    mature = pd.Timestamp.now(tz=IST) >= expiry
    positions = [
        index for index, timestamp in enumerate(frame.index)
        if entry_index <= index and timestamp <= expiry
    ]
    if not positions:
        return None, mature
    return positions[-1], mature


def pending_trade(
    alert: dict,
    frame: pd.DataFrame,
    entry_index: int,
    entry_price: float,
) -> dict:
    result = unfilled(alert, "Pending")
    result.update(
        {
            "filled": True,
            "entry_time": frame.index[entry_index],
            "entry_price": entry_price,
            "entry_basis": "body",
            "outcome": "Pending",
            "final_result": "Pending",
            "bars_held": 0,
            "cooldown_blocked": False,
        }
    )
    return result


def is_crypto_symbol(symbol: str) -> bool:
    return not str(symbol).upper().endswith(".NS")


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
            "half_r_hit": False,
            "target_1_hit": False,
            "target_2_hit": False,
            "outcome": outcome,
            "final_result": "",
            "realized_r": float("nan"),
            "net_realized_r": float("nan"),
            "mfe_r": float("nan"),
            "mae_r": float("nan"),
            "cooldown_blocked": False,
        }
    )
    return result


def apply_same_day_zone_cooldown(
    results: pd.DataFrame,
    market: str = "nse",
) -> tuple[pd.DataFrame, int]:
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
        conflict = any(
            zone_cooldown_overlap(current, previous, market)
            for previous in previous_trades
        )
        if conflict:
            replacement = unfilled(current, "zone_cooldown")
            replacement["cooldown_blocked"] = True
            for key, value in replacement.items():
                frame.at[index, key] = value
            blocked += 1
        else:
            accepted.setdefault(symbol, []).append(current)

    return frame.sort_values("_order").drop(columns="_order"), blocked


def zone_cooldown_overlap(current: dict, previous: dict, market: str) -> bool:
    if market == "crypto":
        current_time = pd.Timestamp(current["entry_time"]).tz_convert(IST)
        previous_time = pd.Timestamp(previous["entry_time"]).tz_convert(IST)
        if current_time - previous_time > timedelta(hours=12):
            return False
    else:
        current_day = pd.Timestamp(current["entry_time"]).tz_convert(IST).date()
        previous_day = pd.Timestamp(previous["entry_time"]).tz_convert(IST).date()
        if current_day != previous_day:
            return False
    return zones_overlap(current, previous)


def same_day_overlap(current: dict, previous: dict) -> bool:
    current_day = pd.Timestamp(current["entry_time"]).tz_convert(IST).date()
    previous_day = pd.Timestamp(previous["entry_time"]).tz_convert(IST).date()
    if current_day != previous_day:
        return False
    return max(float(current["zone_bottom"]), float(previous["zone_bottom"])) <= min(
        float(current["zone_top"]), float(previous["zone_top"])
    )


def zones_overlap(current: dict, previous: dict) -> bool:
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
    market: str = "nse",
) -> str:
    market_label = "CRYPTO" if market == "crypto" else "NSE"
    asset_label = "Coins" if market == "crypto" else "Stocks"
    header = f"{market_label} {timeframe} BACKTEST | {pd.Timestamp(target_date).strftime('%d %b %Y').upper()}"
    if records.empty:
        return (
            f"{header}\n\n"
            "No alerts recorded."
        )

    side_counts = records["side"].value_counts()
    buy_count = int(side_counts.get("long", 0))
    sell_count = int(side_counts.get("short", 0))

    filled = results[results["filled"] == True].copy() if not results.empty else pd.DataFrame()  # noqa: E712
    outcome_counts = results["outcome"].value_counts() if not results.empty else pd.Series(dtype=int)
    duplicates = int(outcome_counts.get("zone_cooldown", 0))
    entries = len(filled)
    touched = entries + duplicates
    no_touch = max(0, len(records) - touched)
    finalized = filled[filled["final_result"] != "Pending"] if not filled.empty else filled
    pending_count = int((filled["final_result"] == "Pending").sum()) if not filled.empty else 0
    net_r = pd.to_numeric(
        finalized.get("net_realized_r", pd.Series(dtype=float)), errors="coerce"
    ).sum()
    final_counts = finalized["final_result"].value_counts() if not finalized.empty else pd.Series(dtype=int)

    lines = [
        header,
        "",
        metric("Alerts", len(records)),
        metric(asset_label, records["symbol"].nunique()),
        metric("BUY", buy_count),
        metric("SELL", sell_count),
        "",
        metric("Touch", touched),
        metric("No Touch", no_touch),
        metric("Duplicates", duplicates),
        metric("Entries", entries),
        "",
        "RESULTS",
        *format_outcome_lines(final_counts),
        *([metric("Pending", pending_count)] if pending_count else []),
        metric("Total Result", format_r(net_r)),
        "",
        "RATING PERFORMANCE",
        format_rating_table(records, results),
    ]

    best = best_symbol_lines(filled, best=True)
    worst = best_symbol_lines(filled, best=False)
    if best:
        lines.extend(["", "BEST", best])
    if worst:
        lines.extend(["", "WORST", worst])

    return "\n".join(lines)


def format_rating_table(records: pd.DataFrame, results: pd.DataFrame) -> str:
    if records.empty:
        return "None"

    records_by_rating = rating_counts(records)
    result_frame = results.copy()
    if not result_frame.empty:
        result_frame["_rating_bucket"] = pd.to_numeric(
            result_frame["rating"], errors="coerce"
        ).astype("Int64")

    blocks: list[str] = []
    for rating in range(4, 11):
        alerts = records_by_rating.get(rating, 0)
        if alerts == 0:
            continue
        rating_results = (
            result_frame[result_frame["_rating_bucket"] == rating]
            if not result_frame.empty
            else pd.DataFrame()
        )
        filled = rating_results[rating_results["filled"] == True]  # noqa: E712
        outcomes = rating_results["outcome"].value_counts() if not rating_results.empty else pd.Series(dtype=int)
        final_counts = filled["final_result"].value_counts() if not filled.empty else pd.Series(dtype=int)
        duplicates = int(outcomes.get("zone_cooldown", 0))
        entries = len(filled)
        touch = entries + duplicates
        no_touch = max(0, alerts - touch)
        block_lines = [
            f"{rating}/10",
            metric("Alerts", alerts),
            metric("Touch", touch),
            metric("No Touch", no_touch),
            metric("Duplicates", duplicates),
            metric("Entries", entries),
            *format_outcome_lines(final_counts),
        ]
        blocks.append("\n".join(block_lines))
    return "\n\n".join(blocks) if blocks else "None"


def format_outcome_lines(counts: pd.Series) -> list[str]:
    lines: list[str] = []
    for outcome in OUTCOME_ORDER:
        count = int(counts.get(outcome, 0))
        if count:
            lines.append(metric(outcome, count))
    return lines


def metric(label: str, value) -> str:
    return f"{label} - {value}"


def display_symbol(symbol: str) -> str:
    text = str(symbol).strip().upper()
    for separator in (":", "/", "-", "."):
        if separator in text:
            text = text.split(separator, 1)[0]
    for suffix in ("USDT", "BUSD", "USD", "INR"):
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


def best_symbol_lines(filled: pd.DataFrame, best: bool) -> str:
    if filled.empty:
        return ""
    frame = filled.copy()
    frame["_result_r"] = frame["final_result"].map(FINAL_RESULT_R)
    if best:
        frame = frame[frame["final_result"].isin(["+0.5R", "+1R", "+2R"])]
        frame = frame.sort_values(["_result_r", "rating"], ascending=[False, False])
    else:
        frame = frame[frame["final_result"] == "SL"]
        frame = frame.sort_values(["_result_r", "rating"], ascending=[True, True])
    if frame.empty:
        return ""
    lines = []
    for index, row in enumerate(frame.head(3).to_dict("records"), start=1):
        rating = int(row["rating"]) if pd.notna(row.get("rating")) else "N/A"
        lines.append(
            f"{index}. {display_symbol(row['symbol'])} - Rating {rating}/10 - {row['final_result']}"
        )
    return "\n".join(lines)


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


def report_key(target_date, timeframe: str, market: str = "nse") -> str:
    return f"{market.upper()}|{timeframe}|{pd.Timestamp(target_date).date().isoformat()}"


def load_sent_reports(path: Path = SENT_REPORTS_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def mark_sent_report(key: str, path: Path = SENT_REPORTS_PATH) -> None:
    data = load_sent_reports(path)
    data[key] = datetime.now(tz=IST).isoformat()
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def persist_finalized_records(
    target_date,
    timeframe: str,
    results: pd.DataFrame,
    market: str = "nse",
    path: Path = FINALIZED_RECORDS_PATH,
) -> None:
    day = pd.Timestamp(target_date).date().isoformat()
    retained: list[str] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("market") == market.upper() and row.get("timeframe") == timeframe and row.get("date") == day:
                continue
            retained.append(json.dumps(row, sort_keys=True))

    new_rows: list[str] = []
    if not results.empty:
        for row in results.to_dict("records"):
            payload = {
                "market": market.upper(),
                "timeframe": timeframe,
                "date": day,
                "symbol": str(row.get("symbol", "")),
                "display_symbol": display_symbol(row.get("symbol", "")),
                "side": row.get("side", ""),
                "rating": parse_optional_float(row.get("rating")),
                "filled": bool(row.get("filled", False)),
                "outcome": row.get("outcome", ""),
                "final_result": row.get("final_result", ""),
                "realized_r": parse_optional_float(row.get("realized_r")),
                "net_realized_r": parse_optional_float(row.get("net_realized_r")),
                "cooldown_blocked": bool(row.get("cooldown_blocked", False)),
                "zone_id": row.get("zone_id", ""),
                "source_line": int(row.get("source_line", 0) or 0),
            }
            new_rows.append(json.dumps(payload, sort_keys=True))

    all_rows = retained + new_rows
    path.write_text(("\n".join(all_rows) + "\n") if all_rows else "", encoding="utf-8")


def main() -> None:
    args = parse_args()
    default_records = (
        configure_crypto_data(args.timeframe)
        if args.market == "crypto"
        else configure_nse_data(args.timeframe)
    )
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
        if args.market == "crypto":
            frames, data_failures = fetch_crypto_frames(sorted(day_records["symbol"].unique()))
        else:
            frames, data_failures = fetch_frames(sorted(day_records["symbol"].unique()))
        results, cooldown_blocked = run_backtest(day_records, frames, args.market)

    message = build_summary(
        day_records,
        target_date,
        results,
        data_failures,
        cooldown_blocked,
        args.timeframe,
        args.market,
    )
    print(message)
    if not args.dry_run:
        key = report_key(target_date, args.timeframe, args.market)
        if not args.force and key in load_sent_reports():
            print(f"Skipped duplicate report: {key}")
            return
        send_discord_message(message)
        mark_sent_report(key)
        persist_finalized_records(target_date, args.timeframe, results, args.market)


if __name__ == "__main__":
    main()
