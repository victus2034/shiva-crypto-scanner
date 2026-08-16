from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, time as datetime_time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

import nse_scanner
import scanner as crypto_scanner
from xstock_hybrid_rating import XSTOCK_UNDERLYINGS, is_xstock


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
NSE_TRADE_START = datetime_time(9, 15)
CRYPTO_EVALUATION_HOURS = 6
CRYPTO_REPORT_BOUNDARY = datetime_time(16, 30)
FIXED_STOP_PCT = 0.5
SL_BUFFER_PCT = 0.10
TARGET_1_R = 1.0
TARGET_2_R = 2.0
HALF_R = 0.5
DATA_QUALITY_AMBIGUOUS = "data_quality_ambiguous"
FINAL_RESULT_R = {
    "SL": -1.0,
    DATA_QUALITY_AMBIGUOUS: float("nan"),
    "+0.5R": 0.5,
    "+1R": 1.0,
    "+2R": 2.0,
    "Neither": 0.0,
}
OUTCOME_ORDER = ["SL", DATA_QUALITY_AMBIGUOUS, "+0.5R", "+1R", "+2R", "Neither"]
MARKET_NSE = "NSE"
MARKET_CRYPTO = "CRYPTO"
MARKET_XSTOCK = "XSTOCK"
MARKET_OTHER = "OTHER"
SENT_REPORTS_PATH = Path(__file__).with_name("daily_backtest_reports_sent.json")
FINALIZED_RECORDS_PATH = Path(__file__).with_name("daily_backtest_finalized_records.jsonl")
PENDING_RECORDS_PATH = Path(__file__).with_name("daily_backtest_pending_records.jsonl")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Post a clean daily delivered-alert backtest summary."
    )
    parser.add_argument(
        "--market",
        choices=["nse", "crypto", "xstock", "other"],
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
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
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
            symbol = str(raw["symbol"])
            row = {
                    "event_time": event_time,
                    "event_time_ist": event_time.tz_convert(IST),
                    "timeframe": timeframe,
                    "symbol": symbol,
                    "side": side,
                    "distance_pct": float(raw["distance_pct"]),
                    "alert_price": float(raw["alert_price"]),
                    "level": float(raw["level"]),
                    "zone_bottom": zone_bottom,
                    "zone_top": zone_top,
                    "body_entry": parse_optional_float(raw.get("body_entry")),
                    "planned_entry": parse_optional_float(raw.get("planned_entry")),
                    "stop_price": parse_optional_float(raw.get("stop_price")),
                    "stop_distance_pct": parse_optional_float(raw.get("stop_distance_pct")),
                    "rating": parse_rating(raw.get("score")),
                    "market_class": market_class(symbol),
                    "zone_id": (
                        f"{raw['symbol']}|{side}|{zone_bottom:.8f}|{zone_top:.8f}"
                    ),
                    "source_line": line_number,
                }
            row["trade_id"] = raw.get("trade_id") or stable_trade_id(row)
            rows.append(row)
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


def json_optional_float(value):
    parsed = parse_optional_float(value)
    return None if pd.isna(parsed) else float(parsed)


def format_optional_timestamp(value) -> str | None:
    if value is None or value == "":
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return pd.Timestamp(value).isoformat()
    except (TypeError, ValueError):
        return None


def assign_report_dates(records: pd.DataFrame, market: str) -> pd.DataFrame:
    if records.empty:
        return records
    frame = records.copy()
    if market in {"crypto", "xstock", "other"}:
        frame["report_date"] = frame["event_time_ist"].apply(crypto_report_date)
    else:
        frame["report_date"] = frame["event_time_ist"].dt.date
    return frame


def normalized_report_date(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError):
        return None


def report_results_for_current_day(
    results: pd.DataFrame,
    current_day_records: pd.DataFrame,
    target_date,
) -> pd.DataFrame:
    """Return result rows for the report without silently dropping valid results."""
    if results.empty:
        return results.copy()
    if current_day_records.empty:
        return results.iloc[0:0].copy()

    if "trade_id" in results:
        current_ids = set(
            current_day_records.get("trade_id", pd.Series(dtype=str)).dropna().astype(str)
        )
        if current_ids:
            matched = results[results["trade_id"].astype(str).isin(current_ids)].copy()
            if not matched.empty:
                return matched

    # Trade IDs are derived from evolving alert fields. If old runtime rows were
    # produced before an ID-shape change, fall back to the already-assigned
    # report_date so the summary does not show fake zero execution.
    if "report_date" in results:
        target = pd.Timestamp(target_date).date()
        result_dates = results["report_date"].apply(normalized_report_date)
        matched = results[result_dates == target].copy()
        if not matched.empty:
            return matched

    return results.iloc[0:0].copy()


def crypto_report_date(event_time_ist) -> object:
    timestamp = pd.Timestamp(event_time_ist).tz_convert(IST)
    if timestamp.time() > CRYPTO_REPORT_BOUNDARY:
        return (timestamp + pd.Timedelta(days=1)).date()
    return timestamp.date()


def select_target_date(
    records: pd.DataFrame,
    requested: str | None,
    market: str = "nse",
    timeframe: str = "30m",
):
    if requested:
        return pd.Timestamp(requested).date()
    if records.empty:
        return pd.Timestamp.now(tz=IST).date()
    if "report_date" in records:
        if market in {"crypto", "xstock", "other"}:
            completed_dates = [
                date for date in records["report_date"].dropna().unique()
                if crypto_report_bucket_ready(date, timeframe)
            ]
            if completed_dates:
                return max(completed_dates)
            return None
        return records["report_date"].max()
    return records["event_time_ist"].dt.date.max()


def crypto_report_bucket_ready(report_date, timeframe: str) -> bool:
    report_day = pd.Timestamp(report_date).date()
    report_time = pd.Timestamp(
        datetime.combine(report_day, CRYPTO_REPORT_BOUNDARY),
        tz=IST,
    )
    return pd.Timestamp.now(tz=IST) >= report_time


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


def normalize_yfinance_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize yfinance output, including single-ticker MultiIndex frames."""
    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = [str(column[0]) for column in frame.columns]
    columns = {str(column).lower(): column for column in frame.columns}
    required = {name: columns.get(name) for name in ("open", "high", "low", "close", "volume")}
    if any(value is None for value in required.values()):
        raise ValueError("fine-resolution data missing OHLCV columns")
    frame = frame[[required[name] for name in required]].copy()
    frame.columns = list(required)
    index = pd.DatetimeIndex(pd.to_datetime(frame.index))
    if index.tz is None:
        index = index.tz_localize(IST)
    else:
        index = index.tz_convert(IST)
    frame.index = index.floor("s")
    return frame.dropna().sort_index()


def _as_ist_timestamp(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize(IST) if timestamp.tzinfo is None else timestamp.tz_convert(IST)


def crypto_fetch_resolution_ohlcv(symbol: str, start=None, end=None):
    """Fetch only the 1-minute window needed to resolve an ambiguous candle."""
    fallback = crypto_scanner.fallback_symbol(symbol)
    last_error = None
    exchanges = []
    primary = crypto_scanner.EXCHANGES_BY_ID.get(crypto_scanner.PRIMARY_EXCHANGE_ID)
    if primary is not None:
        exchanges.append(primary)
    exchanges.extend(exchange for exchange in crypto_scanner.EXCHANGES if exchange not in exchanges)
    for exchange in exchanges:
        for candidate in crypto_scanner.exchange_symbol_candidates(fallback):
            try:
                if start is None or end is None:
                    return exchange.fetch_ohlcv(candidate, timeframe="1m", limit=1000)

                start_ms = int(_as_ist_timestamp(start).tz_convert("UTC").timestamp() * 1000)
                end_ms = int(_as_ist_timestamp(end).tz_convert("UTC").timestamp() * 1000)
                cursor = start_ms
                rows = []
                while cursor < end_ms:
                    batch = exchange.fetch_ohlcv(
                        candidate,
                        timeframe="1m",
                        since=cursor,
                        limit=min(1000, max(2, int((end_ms - cursor) / 60000) + 2)),
                    )
                    if not batch:
                        break
                    rows.extend(row for row in batch if int(row[0]) < end_ms)
                    next_cursor = int(batch[-1][0]) + 60000
                    if next_cursor <= cursor:
                        break
                    cursor = next_cursor
                    if len(batch) < 1000:
                        break
                if rows:
                    return rows
                raise RuntimeError("no 1-minute candles in requested resolution window")
            except Exception as error:
                last_error = error
    raise RuntimeError(f"all crypto 1m exchanges failed for {symbol}: {last_error}")


def fetch_resolution_frames(
    symbols: list[str],
    market: str,
    windows: dict[str, tuple[pd.Timestamp, pd.Timestamp]] | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    """Fetch fine candles only for coarse-candle conflicts."""
    frames: dict[str, pd.DataFrame] = {}
    failures: dict[str, str] = {}
    for symbol in symbols:
        try:
            if market == "nse":
                start, end = (windows or {}).get(symbol, (None, None))
                download_kwargs = {
                    "interval": "1m",
                    "auto_adjust": False,
                    "progress": False,
                    "threads": False,
                }
                if start is not None and end is not None:
                    download_kwargs.update({
                        "start": _as_ist_timestamp(start).to_pydatetime(),
                        "end": _as_ist_timestamp(end).to_pydatetime(),
                    })
                else:
                    download_kwargs["period"] = "7d"
                raw = yf.download(
                    symbol,
                    **download_kwargs,
                )
                frames[symbol] = normalize_yfinance_frame(raw)
            elif market == "crypto":
                start, end = (windows or {}).get(symbol, (None, None))
                frames[symbol] = normalize_crypto_frame(
                    crypto_fetch_resolution_ohlcv(symbol, start=start, end=end)
                )
            else:
                failures[symbol] = "fine-resolution timing is TBD for xStocks"
        except Exception as error:
            failures[symbol] = str(error)
    return frames, failures


CRYPTO_FETCH_DEBUG = os.getenv("SHIVA_BACKTEST_DEBUG_EXCHANGE", "").strip().lower() in {"1", "true", "yes"}
CRYPTO_FETCH_SOURCE_COUNTS: dict[str, int] = {}


def _log_crypto_fetch_source(symbol: str, source: str, ohlcv) -> None:
    CRYPTO_FETCH_SOURCE_COUNTS[source] = CRYPTO_FETCH_SOURCE_COUNTS.get(source, 0) + 1
    if not CRYPTO_FETCH_DEBUG:
        return
    try:
        first_ts = pd.Timestamp(ohlcv[0][0], unit="ms", tz="UTC") if ohlcv else None
        last_ts = pd.Timestamp(ohlcv[-1][0], unit="ms", tz="UTC") if ohlcv else None
    except Exception:
        first_ts = last_ts = None
    print(
        f"[backtest-exchange-debug] {symbol} <- {source} "
        f"candles={len(ohlcv) if ohlcv else 0} range={first_ts}..{last_ts}",
        file=sys.stderr,
    )


def crypto_fetch_ohlcv(symbol: str):
    last_error = None
    symbol_for_fallback = crypto_scanner.fallback_symbol(symbol)

    primary_exchange = crypto_scanner.EXCHANGES_BY_ID.get(crypto_scanner.PRIMARY_EXCHANGE_ID)
    if primary_exchange is not None:
        try:
            ohlcv = crypto_scanner.require_fresh_ohlcv(
                crypto_scanner.fetch_exchange_ohlcv(primary_exchange, symbol_for_fallback),
                primary_exchange.id,
            )
            _log_crypto_fetch_source(symbol, primary_exchange.id, ohlcv)
            return ohlcv
        except Exception as error:
            last_error = error
            if CRYPTO_FETCH_DEBUG:
                print(f"[backtest-exchange-debug] {symbol} primary({primary_exchange.id}) failed: {error}", file=sys.stderr)

    for exchange in crypto_scanner.EXCHANGES:
        if exchange.id == crypto_scanner.PRIMARY_EXCHANGE_ID:
            continue
        try:
            ohlcv = crypto_scanner.require_fresh_ohlcv(
                crypto_scanner.fetch_exchange_ohlcv(exchange, symbol_for_fallback),
                exchange.id,
            )
            _log_crypto_fetch_source(symbol, exchange.id, ohlcv)
            return ohlcv
        except Exception as error:
            last_error = error
            if CRYPTO_FETCH_DEBUG:
                print(f"[backtest-exchange-debug] {symbol} fallback({exchange.id}) failed: {error}", file=sys.stderr)

    if crypto_scanner.is_coinswitch_configured():
        try:
            ohlcv = crypto_scanner.require_fresh_ohlcv(
                crypto_scanner.fetch_coinswitch_ohlcv(symbol), "coinswitch"
            )
            _log_crypto_fetch_source(symbol, "coinswitch", ohlcv)
            return ohlcv
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
    resolution_frames: dict[str, pd.DataFrame] | None = None,
) -> tuple[pd.DataFrame, int]:
    rows = []
    resolution_frames = resolution_frames or {}
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
        elif market == "xstock":
            # xStocks have no approved fixed evaluation horizon yet.  Do not
            # silently apply crypto's six-hour provisional window to them.
            tracking_end_index, window_mature = all_available_tracking_end(frame)
        elif market == "other":
            tracking_end_index, window_mature = crypto_tracking_end(frame, event_time)
        else:
            tracking_end_index, window_mature = same_day_tracking_end(frame, event_time)
        if not window_mature:
            rows.append(unfilled(alert, "immature"))
            continue
        if tracking_end_index is None or tracking_end_index <= event_index:
            rows.append(unfilled(alert, "zone_not_touched"))
            continue

        rows.append(
            simulate_alert(
                frame,
                alert,
                event_index,
                tracking_end_index,
                resolution_frames.get(alert["symbol"]),
                market,
            )
        )

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
    before_cutoff = candle_ends(frame) <= cutoff
    positions = [
        index for index, keep in enumerate(same_day & before_cutoff)
        if keep
    ]
    if not positions:
        return None, True
    return positions[-1], True


def candle_ends(frame: pd.DataFrame) -> pd.DatetimeIndex:
    if frame.empty:
        return frame.index
    duration = infer_bar_duration(frame)
    return pd.DatetimeIndex(frame.index + duration)


def infer_bar_duration(frame: pd.DataFrame) -> pd.Timedelta:
    if len(frame.index) < 2:
        return pd.Timedelta(0)
    diffs = pd.Series(frame.index[1:] - frame.index[:-1])
    positive = diffs[diffs > pd.Timedelta(0)]
    if positive.empty:
        return pd.Timedelta(0)
    return positive.median()


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


def all_available_tracking_end(frame: pd.DataFrame) -> tuple[int | None, bool]:
    """Use all currently available bars when no fixed horizon is approved."""
    if frame.empty:
        return None, True
    return len(frame.index) - 1, True


def simulate_alert(
    frame: pd.DataFrame,
    alert: dict,
    event_index: int,
    tracking_end_index: int,
    resolution_frame: pd.DataFrame | None = None,
    market: str | None = None,
) -> dict:
    side = alert["side"]
    direction = 1.0 if side == "long" else -1.0
    entry_price = body_entry_price(frame, alert, event_index)
    entry_index = find_entry(
        frame,
        event_index,
        entry_price,
        tracking_end_index,
        alert.get("symbol", ""),
    )
    if entry_index is None:
        if uses_six_hour_evaluation(alert.get("symbol", "")) and not entry_search_mature(
            frame,
            event_index,
            tracking_end_index,
        ):
            return unfilled(alert, "immature")
        return unfilled(alert, "zone_not_touched")

    if market_class(alert.get("symbol", "")) == MARKET_XSTOCK:
        return pending_trade(
            alert,
            frame,
            entry_index,
            entry_price,
            timing_status="xstock_timing_tbd",
        )

    if uses_six_hour_evaluation(alert.get("symbol", "")):
        six_hour_end_index, six_hour_window_mature = six_hour_entry_tracking_end(frame, entry_index)
        if six_hour_end_index is None or six_hour_end_index < entry_index:
            return pending_trade(alert, frame, entry_index, entry_price)
        tracking_end_index = min(tracking_end_index, six_hour_end_index)
        if not six_hour_window_mature:
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
    time_to_half_r = None
    time_to_1r = None
    time_to_2r = None
    time_to_sl = None
    outcome = "Neither"
    exit_index = end_index
    max_favorable_r = 0.0
    max_adverse_r = 0.0
    ambiguous_interval_start = None
    ambiguous_interval_end = None

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

        target_hit_this_candle = half_target_hit or first_target_hit or second_target_hit
        if outcome == "Neither" and stop_hit and target_hit_this_candle:
            resolution = resolve_same_candle_order(
                resolution_frame,
                frame,
                index,
                side,
                stop,
                target_half,
                target_1,
                target_2,
                market=market,
            )
            if resolution == "SL":
                outcome = "SL"
                exit_index = index
                time_to_sl = frame.index[index]
                break
            if resolution == DATA_QUALITY_AMBIGUOUS:
                outcome = DATA_QUALITY_AMBIGUOUS
                exit_index = index
                ambiguous_interval_start = frame.index[index]
                bar_duration = infer_bar_duration(frame)
                ambiguous_interval_end = frame.index[index] + bar_duration
                break
            if resolution in {"+0.5R", "+1R", "+2R"}:
                if resolution in {"+0.5R", "+1R", "+2R"}:
                    half_r_hit = True
                    if time_to_half_r is None:
                        time_to_half_r = frame.index[index]
                    outcome = "+0.5R"
                if resolution in {"+1R", "+2R"}:
                    target_1_hit = True
                    if time_to_1r is None:
                        time_to_1r = frame.index[index]
                    outcome = "+1R"
                if resolution == "+2R":
                    target_2_hit = True
                    if time_to_2r is None:
                        time_to_2r = frame.index[index]
                    outcome = "+2R"
                    exit_index = index
                    break
                continue
        if outcome == "Neither" and stop_hit:
            outcome = "SL"
            exit_index = index
            time_to_sl = frame.index[index]
            break
        if half_target_hit:
            half_r_hit = True
            if time_to_half_r is None:
                time_to_half_r = frame.index[index]
            if outcome == "Neither":
                outcome = "+0.5R"
        if first_target_hit:
            half_r_hit = True
            target_1_hit = True
            if time_to_half_r is None:
                time_to_half_r = frame.index[index]
            if time_to_1r is None:
                time_to_1r = frame.index[index]
            outcome = "+1R"
        if second_target_hit:
            half_r_hit = True
            target_1_hit = True
            target_2_hit = True
            if time_to_half_r is None:
                time_to_half_r = frame.index[index]
            if time_to_1r is None:
                time_to_1r = frame.index[index]
            if time_to_2r is None:
                time_to_2r = frame.index[index]
            outcome = "+2R"
            exit_index = index
            break

    if outcome == "SL":
        exit_price = stop
    elif outcome == DATA_QUALITY_AMBIGUOUS:
        exit_price = float("nan")
    elif outcome == "+0.5R":
        exit_price = target_half
    elif outcome == "+1R":
        exit_price = target_1
    elif outcome == "+2R":
        exit_price = target_2
    else:
        exit_price = float(frame["close"].iloc[exit_index])
    realized_r = FINAL_RESULT_R[outcome]
    evaluation_end_time = candle_ends(frame)[exit_index]
    final_resolution_time = resolution_time_for_outcome(
        outcome,
        evaluation_end_time,
        time_to_half_r,
        time_to_1r,
        time_to_2r,
        time_to_sl,
    )
    best_secured_time = best_secured_milestone_time(time_to_half_r, time_to_1r, time_to_2r)

    result = dict(alert)
    result.update(
        {
            "trade_id": stable_trade_id(alert),
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
            "time_to_half_r": time_to_half_r,
            "time_to_1r": time_to_1r,
            "time_to_2r": time_to_2r,
            "time_to_sl": time_to_sl,
            "final_resolution_time": final_resolution_time,
            "time_to_resolution_seconds": duration_seconds(frame.index[entry_index], final_resolution_time),
            "time_to_best_secured_milestone_seconds": duration_seconds(frame.index[entry_index], best_secured_time),
            "cooldown_blocked": False,
            "ambiguous_interval_start": ambiguous_interval_start,
            "ambiguous_interval_end": ambiguous_interval_end,
        }
    )
    return result


def resolution_time_for_outcome(
    outcome: str,
    fallback_time,
    time_to_half_r,
    time_to_1r,
    time_to_2r,
    time_to_sl,
):
    if outcome == "+2R":
        return time_to_2r
    if outcome == "+1R":
        return time_to_1r
    if outcome == "+0.5R":
        return time_to_half_r
    if outcome == "SL":
        return time_to_sl
    return fallback_time


def resolve_same_candle_order(
    resolution_frame: pd.DataFrame | None,
    frame: pd.DataFrame,
    index: int,
    side: str,
    stop: float,
    target_half: float,
    target_1: float,
    target_2: float,
    market: str | None = None,
) -> str:
    """Use finer candles to resolve an otherwise ambiguous SL/target candle."""
    if resolution_frame is None or resolution_frame.empty:
        return DATA_QUALITY_AMBIGUOUS

    start = pd.Timestamp(frame.index[index])
    duration = infer_bar_duration(frame)
    end = start + duration if duration > pd.Timedelta(0) else start
    fine = resolution_frame.copy()
    fine_index = pd.DatetimeIndex(fine.index)
    fine.index = fine_index.tz_localize(IST) if fine_index.tz is None else fine_index.tz_convert(IST)
    if end > start:
        fine = fine[(fine.index >= start) & (fine.index < end)]
    else:
        fine = fine[fine.index == start]
    if fine.empty:
        return DATA_QUALITY_AMBIGUOUS

    if market == "nse":
        cutoff = pd.Timestamp(
            datetime.combine(start.date(), NSE_BACKTEST_CLOSE_CUTOFF),
            tz=IST,
        )
        fine = fine[candle_ends(fine) <= cutoff]
        if fine.empty:
            return DATA_QUALITY_AMBIGUOUS

    for _, candle in fine.iterrows():
        high = float(candle["high"])
        low = float(candle["low"])
        stop_hit = low <= stop if side == "long" else high >= stop
        half_hit = high >= target_half if side == "long" else low <= target_half
        one_hit = high >= target_1 if side == "long" else low <= target_1
        two_hit = high >= target_2 if side == "long" else low <= target_2
        target_hit = half_hit or one_hit or two_hit
        if stop_hit and target_hit:
            return DATA_QUALITY_AMBIGUOUS
        if stop_hit:
            return "SL"
        if two_hit:
            return "+2R"
        if one_hit:
            return "+1R"
        if half_hit:
            return "+0.5R"

    return DATA_QUALITY_AMBIGUOUS


def best_secured_milestone_time(time_to_half_r, time_to_1r, time_to_2r):
    for value in (time_to_2r, time_to_1r, time_to_half_r):
        if not pd.isna(value):
            return value
    return pd.NaT


def duration_seconds(start, end) -> float | None:
    if pd.isna(start) or pd.isna(end):
        return None
    return float((pd.Timestamp(end) - pd.Timestamp(start)).total_seconds())


def six_hour_entry_tracking_end(
    frame: pd.DataFrame,
    entry_index: int,
) -> tuple[int | None, bool]:
    expiry = pd.Timestamp(frame.index[entry_index]) + timedelta(hours=CRYPTO_EVALUATION_HOURS)
    mature = pd.Timestamp.now(tz=IST) >= expiry
    ends = candle_ends(frame)
    positions = [
        index for index, timestamp in enumerate(ends)
        if entry_index <= index and timestamp <= expiry
    ]
    if not positions:
        return None, mature
    return positions[-1], mature


def uses_six_hour_evaluation(symbol: str) -> bool:
    return market_class(symbol) == MARKET_CRYPTO


def pending_trade(
    alert: dict,
    frame: pd.DataFrame,
    entry_index: int,
    entry_price: float,
    timing_status: str = "pending",
) -> dict:
    result = unfilled(alert, "Pending")
    result.update(
        {
            "trade_id": stable_trade_id(alert),
            "filled": True,
            "entry_time": frame.index[entry_index],
            "entry_price": entry_price,
            "entry_basis": "body",
            "outcome": "Pending",
            "final_result": "Pending",
            "timing_status": timing_status,
            "bars_held": 0,
            "cooldown_blocked": False,
        }
    )
    return result


def is_crypto_symbol(symbol: str) -> bool:
    return market_class(symbol) == MARKET_CRYPTO


def is_xstock_symbol(symbol: str) -> bool:
    return is_xstock(str(symbol).upper())


def market_class(symbol: str) -> str:
    text = str(symbol).strip().upper()
    if text.endswith(".NS"):
        return MARKET_NSE
    if is_xstock_symbol(text):
        return MARKET_XSTOCK
    normalized = display_symbol(text)
    if normalized in {"PAXG", "SLVON"}:
        return MARKET_OTHER
    return MARKET_CRYPTO


def body_entry_price(frame: pd.DataFrame, alert: dict, event_index: int) -> float:
    recorded_planned_entry = pd.to_numeric(alert.get("planned_entry"), errors="coerce")
    if pd.notna(recorded_planned_entry):
        return float(recorded_planned_entry)

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
    """Buffered far-side zone stop used by alerts and backtest."""
    recorded_stop = pd.to_numeric(alert.get("stop_price"), errors="coerce")
    if pd.notna(recorded_stop):
        return float(recorded_stop)

    if alert["side"] == "long":
        return float(alert["zone_bottom"]) * (1 - SL_BUFFER_PCT / 100.0)
    return float(alert["zone_top"]) * (1 + SL_BUFFER_PCT / 100.0)


def find_entry(
    frame: pd.DataFrame,
    event_index: int,
    entry_price: float,
    tracking_end_index: int,
    symbol: str = "",
) -> int | None:
    end_index = min(event_index + ENTRY_WAIT_BARS, tracking_end_index)
    for index in range(event_index + 1, end_index + 1):
        timestamp = pd.Timestamp(frame.index[index]).tz_convert(IST)
        if is_nse_symbol(symbol) and timestamp.time() < NSE_TRADE_START:
            continue
        if float(frame["low"].iloc[index]) <= entry_price <= float(frame["high"].iloc[index]):
            return index
    return None


def entry_search_mature(
    frame: pd.DataFrame,
    event_index: int,
    tracking_end_index: int,
) -> bool:
    """A no-entry result is only final after the full entry window has closed."""
    required_index = min(event_index + ENTRY_WAIT_BARS, len(frame.index) - 1)
    if tracking_end_index < required_index:
        return False
    ends = candle_ends(frame)
    if required_index >= len(ends):
        return False
    required_end = pd.Timestamp(ends[required_index]).tz_convert(IST)
    return pd.Timestamp.now(tz=IST) >= required_end


def is_nse_symbol(symbol: str) -> bool:
    return str(symbol).upper().endswith(".NS")


def unfilled(alert: dict, outcome: str) -> dict:
    result = dict(alert)
    result.update(
        {
            "trade_id": stable_trade_id(alert),
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
            "time_to_half_r": pd.NaT,
            "time_to_1r": pd.NaT,
            "time_to_2r": pd.NaT,
            "time_to_sl": pd.NaT,
            "final_resolution_time": pd.NaT,
            "time_to_resolution_seconds": None,
            "time_to_best_secured_milestone_seconds": None,
            "cooldown_blocked": False,
            "timing_status": "",
        }
    )
    return result


def stable_trade_id(alert: dict) -> str:
    event_time = first_present_value(alert.get("event_time_ist"), alert.get("event_time"), "")
    if not isinstance(event_time, str):
        try:
            event_time = pd.Timestamp(event_time).isoformat()
        except (TypeError, ValueError):
            event_time = str(event_time)
    raw = "|".join(
        [
            str(alert.get("symbol", "")).upper(),
            str(alert.get("timeframe", "")),
            str(alert.get("side", "")),
            str(alert.get("zone_id", "")),
            str(event_time),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def first_present_value(*values):
    for value in values:
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        return value
    return None


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
    if current.get("side") != previous.get("side"):
        # A long and a short zone that happen to overlap in price are two
        # genuinely distinct trades, not duplicate deliveries of the same
        # setup - never merge them.
        return False
    if market in {"crypto", "xstock"}:
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


MARKET_LABELS = {
    "nse": ("NSE", "Stocks"),
    "crypto": ("CRYPTO", "Coins"),
    "xstock": ("XSTOCK", "xStocks"),
    "other": ("OTHER", "Contracts"),
}


def build_summary(
    records: pd.DataFrame,
    target_date,
    results: pd.DataFrame,
    data_failures: dict[str, str],
    cooldown_blocked: int,
    timeframe: str,
    market: str = "nse",
) -> str:
    market_label, asset_label = MARKET_LABELS.get(market, (market.upper(), "Symbols"))
    header = f"{market_label} {timeframe} BACKTEST"
    date_line = pd.Timestamp(target_date).strftime("%d %b %Y").upper()
    if records.empty:
        return (
            f"{header}\n"
            f"{date_line}\n\n"
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
    no_touch = int(outcome_counts.get("zone_not_touched", 0))
    waiting = int(outcome_counts.get("immature", 0))
    data_issues = int(outcome_counts.get("data_missing", 0)) + int(outcome_counts.get("alert_before_data", 0))
    finalized = filled[filled["final_result"] != "Pending"] if not filled.empty else filled
    pending_count = int((filled["final_result"] == "Pending").sum()) if not filled.empty else 0
    waiting += pending_count
    net_r = pd.to_numeric(
        finalized.get("net_realized_r", pd.Series(dtype=float)), errors="coerce"
    ).sum()
    final_counts = finalized["final_result"].value_counts() if not finalized.empty else pd.Series(dtype=int)

    lines = [
        header,
        date_line,
        "",
        "OVERVIEW",
        metric("Alerts", len(records)),
        metric(asset_label, records["symbol"].nunique()),
        metric("BUY", buy_count),
        metric("SELL", sell_count),
        "",
        "EXECUTION",
        metric("Touch", touched),
        metric("No Touch", no_touch),
        *([metric("Duplicates", duplicates)] if duplicates else []),
        metric("Entries", entries),
        *([metric("Waiting", waiting)] if waiting else []),
        *([metric("Data Issues", data_issues)] if data_issues else []),
        "",
        "RESULTS",
        *format_outcome_lines(final_counts),
        "",
        "TOTAL RESULT",
        format_r(net_r),
        "",
        "RATING PERFORMANCE",
        format_rating_table(records, results),
    ]

    hourly_lines = hourly_breakdown_lines(results)
    if hourly_lines:
        lines.extend(["", "HOURLY BREAKDOWN (IST, by alert time)", *hourly_lines])

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

    record_ratings = pd.to_numeric(records.get("rating", pd.Series(dtype=float)), errors="coerce")
    records_by_rating = rating_counts(records)
    result_frame = results.copy()
    if not result_frame.empty:
        result_frame["_rating_bucket"] = pd.to_numeric(
            result_frame["rating"], errors="coerce"
        ).astype("Int64")

    rows: list[str] = []
    no_entry_ratings: list[str] = []
    for rating in range(1, 11):
        alerts = records_by_rating.get(rating, 0)
        if alerts == 0:
            continue
        rating_results = (
            result_frame[result_frame["_rating_bucket"] == rating]
            if not result_frame.empty
            else pd.DataFrame()
        )
        filled = (
            rating_results[rating_results["filled"] == True]  # noqa: E712
            if not rating_results.empty
            else pd.DataFrame()
        )
        outcomes = rating_results["outcome"].value_counts() if not rating_results.empty else pd.Series(dtype=int)
        finalized = filled[filled["final_result"] != "Pending"] if not filled.empty else filled
        final_counts = finalized["final_result"].value_counts() if not finalized.empty else pd.Series(dtype=int)
        duplicates = int(outcomes.get("zone_cooldown", 0))
        entries = len(filled)
        half_r = int(final_counts.get("+0.5R", 0))
        one_r = int(final_counts.get("+1R", 0))
        two_r = int(final_counts.get("+2R", 0))
        stops = int(final_counts.get("SL", 0))
        ambiguous = int(final_counts.get(DATA_QUALITY_AMBIGUOUS, 0))
        neither = int(final_counts.get("Neither", 0))
        waiting = int(outcomes.get("immature", 0))
        waiting += int((filled["final_result"] == "Pending").sum()) if not filled.empty else 0
        wins = half_r + one_r + two_r
        if entries == 0:
            no_entry_ratings.append(f"{rating}/10")
            continue
        detail_parts = []
        if ambiguous:
            detail_parts.append(f"Ambiguous {ambiguous}")
        if neither:
            detail_parts.append(f"Neither {neither}")
        if waiting:
            detail_parts.append(f"Waiting {waiting}")
        line = f"{rating}/10 - {entries} entries | {wins}W / {stops}L | {format_win_rate(wins, stops)}"
        if detail_parts:
            line += f" | {', '.join(detail_parts)}"
        rows.append(line)
    if no_entry_ratings:
        rows.append(f"No Entries - {', '.join(no_entry_ratings)}")

    unrated_count = int(record_ratings.isna().sum())
    if unrated_count:
        unrated_results = (
            result_frame[result_frame["_rating_bucket"].isna()]
            if not result_frame.empty and "_rating_bucket" in result_frame
            else pd.DataFrame()
        )
        unrated_filled = unrated_results[unrated_results["filled"] == True] if not unrated_results.empty else pd.DataFrame()  # noqa: E712
        if unrated_filled.empty:
            rows.append("No Entries - Unrated/N/A")
        else:
            finalized = unrated_filled[unrated_filled["final_result"] != "Pending"]
            final_counts = finalized["final_result"].value_counts()
            wins = int(final_counts.get("+0.5R", 0)) + int(final_counts.get("+1R", 0)) + int(final_counts.get("+2R", 0))
            stops = int(final_counts.get("SL", 0))
            rows.append(f"Unrated/N/A - {len(unrated_filled)} entries | {wins}W / {stops}L | {format_win_rate(wins, stops)}")
    return "\n".join(rows) if rows else "None"


def format_outcome_lines(counts: pd.Series) -> list[str]:
    labels = {DATA_QUALITY_AMBIGUOUS: "Ambiguous"}
    lines: list[str] = []
    for outcome in OUTCOME_ORDER:
        count = int(counts.get(outcome, 0))
        if count:
            lines.append(metric(labels.get(outcome, outcome), count))
    return lines


def display_symbol(symbol: str) -> str:
    raw = str(symbol).strip().upper()
    mapping = XSTOCK_UNDERLYINGS.get(raw)
    if mapping:
        return str(mapping["ticker"]).upper()

    text = raw
    for separator in (":", "/", "-", "."):
        if separator in text:
            text = text.split(separator, 1)[0]
    for suffix in ("USDT", "BUSD", "USD", "INR"):
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


def metric(label: str, value) -> str:
    return f"{label} - {value}"


def hourly_breakdown_lines(results: pd.DataFrame) -> list[str]:
    """Per-hour (IST, by alert time) alert/entry/outcome/rating breakdown."""
    if results.empty or "event_time_ist" not in results.columns:
        return []

    frame = results.copy()
    frame["hour"] = pd.to_datetime(frame["event_time_ist"]).dt.floor("h")

    lines = []
    for hour in sorted(frame["hour"].dropna().unique()):
        group = frame[frame["hour"] == hour]
        parts = [f"Alerts {len(group)}"]

        filled_group = group[group["filled"] == True]  # noqa: E712
        if len(filled_group):
            parts.append(f"Entries {len(filled_group)}")
            finalized_group = filled_group[filled_group["final_result"] != "Pending"]
            outcome_counts = finalized_group["final_result"].value_counts()
            for label in ["+0.5R", "+1R", "+2R", "SL"]:
                count = int(outcome_counts.get(label, 0))
                if count:
                    parts.append(f"{label} {count}")

        ratings = pd.to_numeric(group["rating"], errors="coerce").dropna()
        if not ratings.empty:
            parts.append(f"Avg Rating {ratings.mean():.1f}")

        hour_label = pd.Timestamp(hour).strftime("%H:%M")
        lines.append(f"{hour_label} - " + " | ".join(parts))
    return lines


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
            f"{index}. {display_symbol(row['symbol'])} - {rating}/10 - {row['final_result']}"
        )
    return "\n".join(lines)


def rating_counts(records: pd.DataFrame) -> dict[int, int]:
    ratings = pd.to_numeric(records["rating"], errors="coerce").dropna()
    if ratings.empty:
        return {}
    counts = ratings.astype(int).value_counts()
    return {int(score): int(count) for score, count in counts.items() if 1 <= int(score) <= 10}


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
    webhook_url = discord_wait_url(webhook_url)
    payload = discord_payload(message)
    for attempt in range(6):
        response = requests.post(webhook_url, json=payload, timeout=15)
        if response.status_code != 429:
            response.raise_for_status()
            message_id = discord_message_id(response)
            if not message_id:
                raise RuntimeError("Discord webhook accepted the request but did not return a message id")
            print(f"Discord daily backtest message posted: {message_id}")
            return
        try:
            retry_after = float(response.json().get("retry_after", 1.0))
        except (TypeError, ValueError, requests.JSONDecodeError):
            retry_after = 1.0
        if attempt == 5:
            response.raise_for_status()
        time.sleep(max(0.25, min(retry_after, 30.0)))


def send_discord_message_with_attachment(message: str, filename: str, file_bytes: bytes) -> None:
    webhook_url = os.getenv(WEBHOOK_ENV, "").strip()
    if not webhook_url:
        raise RuntimeError(f"{WEBHOOK_ENV} is not configured")
    webhook_url = discord_wait_url(webhook_url)
    payload = discord_payload(message)
    for attempt in range(6):
        files = {
            "file": (
                filename,
                file_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        }
        data = {"payload_json": json.dumps(payload)}
        response = requests.post(webhook_url, data=data, files=files, timeout=30)
        if response.status_code != 429:
            response.raise_for_status()
            message_id = discord_message_id(response)
            if not message_id:
                raise RuntimeError("Discord webhook accepted the request but did not return a message id")
            print(f"Discord message with attachment posted: {message_id}")
            return
        try:
            retry_after = float(response.json().get("retry_after", 1.0))
        except (TypeError, ValueError, requests.JSONDecodeError):
            retry_after = 1.0
        if attempt == 5:
            response.raise_for_status()
        time.sleep(max(0.25, min(retry_after, 30.0)))


def discord_wait_url(webhook_url: str) -> str:
    parts = urlsplit(webhook_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["wait"] = "true"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def discord_message_id(response: requests.Response) -> str | None:
    try:
        body = response.json()
    except requests.JSONDecodeError:
        return None
    message_id = body.get("id") if isinstance(body, dict) else None
    return str(message_id) if message_id else None


def discord_payload(message: str) -> dict:
    chunks = split_discord_embed_descriptions(message)
    if chunks:
        return {
            "embeds": [
                {"description": chunk, "color": 3447003}
                for chunk in chunks[:10]
            ]
        }
    return {"content": message[:2000]}


def split_discord_embed_descriptions(message: str, limit: int = 4096) -> list[str]:
    if not message:
        return []
    chunks: list[str] = []
    current = ""
    for line in message.splitlines():
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = line
        while len(current) > limit:
            chunks.append(current[:limit])
            current = current[limit:]
    if current:
        chunks.append(current)
    return chunks


def report_key(target_date, timeframe: str, market: str = "nse") -> str:
    return f"{market.upper()}|{timeframe}|{pd.Timestamp(target_date).date().isoformat()}"


def load_sent_reports(path: Path = SENT_REPORTS_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
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
    pending_path = path.with_name(PENDING_RECORDS_PATH.name) if path == FINALIZED_RECORDS_PATH else None
    lifecycle_rows = load_lifecycle_rows(path, pending_path)
    for row in results.to_dict("records") if not results.empty else []:
        payload = lifecycle_payload(row, target_date, timeframe, market)
        lifecycle_rows[payload["trade_id"]] = payload
    write_lifecycle_rows(lifecycle_rows, path, pending_path)


def lifecycle_payload(row: dict, target_date, timeframe: str, market: str) -> dict:
    alert_time = first_present_value(row.get("event_time_ist"), row.get("event_time"))
    row_date = row.get("report_date") or row.get("date") or target_date
    payload = {
        "market": market.upper(),
        "timeframe": timeframe,
        "date": pd.Timestamp(row_date).date().isoformat(),
        "symbol": str(row.get("symbol", "")),
        "display_symbol": display_symbol(row.get("symbol", "")),
        "side": row.get("side", ""),
        "rating": json_optional_float(row.get("rating")),
        "trade_id": row.get("trade_id") or stable_trade_id(row),
        "alert_time": format_optional_timestamp(alert_time),
        "entry_time": format_optional_timestamp(row.get("entry_time")),
        "entry_price": json_optional_float(row.get("entry_price")),
        "planned_entry": json_optional_float(row.get("planned_entry")),
        "stop_price": json_optional_float(row.get("stop_price")),
        "zone_bottom": json_optional_float(row.get("zone_bottom")),
        "zone_top": json_optional_float(row.get("zone_top")),
        "alert_price": json_optional_float(row.get("alert_price")),
        "filled": bool(row.get("filled", False)),
        "outcome": row.get("outcome", ""),
        "final_result": row.get("final_result", ""),
        "timing_status": row.get("timing_status", ""),
        "final_resolution_time": format_optional_timestamp(row.get("final_resolution_time")),
        "time_to_half_r": format_optional_timestamp(row.get("time_to_half_r")),
        "time_to_1r": format_optional_timestamp(row.get("time_to_1r")),
        "time_to_2r": format_optional_timestamp(row.get("time_to_2r")),
        "time_to_sl": format_optional_timestamp(row.get("time_to_sl")),
        "time_to_resolution_seconds": json_optional_float(row.get("time_to_resolution_seconds")),
        "time_to_best_secured_milestone_seconds": json_optional_float(row.get("time_to_best_secured_milestone_seconds")),
        "realized_r": json_optional_float(row.get("realized_r")),
        "net_realized_r": json_optional_float(row.get("net_realized_r")),
        "cooldown_blocked": bool(row.get("cooldown_blocked", False)),
        "ambiguous_interval_start": format_optional_timestamp(row.get("ambiguous_interval_start")),
        "ambiguous_interval_end": format_optional_timestamp(row.get("ambiguous_interval_end")),
        "zone_id": row.get("zone_id", ""),
        "source_line": int(row.get("source_line", 0) or 0),
    }
    return payload


def load_lifecycle_rows(finalized_path: Path, pending_path: Path | None) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for path in (finalized_path, pending_path):
        if path is None or not path.exists():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            trade_id = row.get("trade_id")
            if trade_id:
                rows[str(trade_id)] = row
    return rows


def write_lifecycle_rows(rows: dict[str, dict], finalized_path: Path, pending_path: Path | None) -> None:
    finalized = []
    pending = []
    for row in rows.values():
        if (
            row.get("final_result") in {"Pending", DATA_QUALITY_AMBIGUOUS}
            or str(row.get("timing_status", "")).endswith("_tbd")
        ):
            pending.append(row)
        else:
            finalized.append(row)
    finalized_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in finalized) + ("\n" if finalized else ""),
        encoding="utf-8",
    )
    if pending_path is not None:
        pending_path.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in pending) + ("\n" if pending else ""),
            encoding="utf-8",
        )


def load_pending_records(path: Path = PENDING_RECORDS_PATH, timeframe: str | None = None, market: str | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if timeframe and row.get("timeframe") != timeframe:
            continue
        if market and row.get("market") != market.upper():
            continue
        row["event_time_ist"] = row.get("alert_time")
        row["event_time"] = row.get("alert_time")
        row["market_class"] = row.get("market", "")
        row["report_date"] = pd.Timestamp(row.get("date")).date() if row.get("date") else None
        rows.append(row)
    return pd.DataFrame(rows)


def resolution_windows(results: pd.DataFrame) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    """Return exact fine-data windows for unresolved same-candle conflicts."""
    if results.empty or "final_result" not in results:
        return {}
    ambiguous = results[results["final_result"] == DATA_QUALITY_AMBIGUOUS].copy()
    if ambiguous.empty:
        return {}
    windows: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    for _, row in ambiguous.iterrows():
        symbol = str(row.get("symbol", ""))
        start = row.get("ambiguous_interval_start")
        end = row.get("ambiguous_interval_end")
        if not symbol or pd.isna(start) or pd.isna(end):
            continue
        start_ts = _as_ist_timestamp(start)
        end_ts = _as_ist_timestamp(end)
        if symbol not in windows:
            windows[symbol] = (start_ts, end_ts)
        else:
            current_start, current_end = windows[symbol]
            windows[symbol] = (min(current_start, start_ts), max(current_end, end_ts))
    return windows


def reconciliation_diagnostics(
    delivered: pd.DataFrame,
    backtested: pd.DataFrame,
    finalized_path: Path = FINALIZED_RECORDS_PATH,
) -> dict[str, object]:
    """Check delivered -> backtested -> finalized lifecycle continuity."""
    delivered_ids = (
        set(delivered.get("trade_id", pd.Series(dtype=str)).dropna().astype(str))
        if not delivered.empty else set()
    )
    backtested_ids = (
        set(backtested.get("trade_id", pd.Series(dtype=str)).dropna().astype(str))
        if not backtested.empty else set()
    )
    finalized_rows = []
    raw_id_counts: dict[str, int] = {}
    if finalized_path.exists():
        for line in finalized_path.read_text(encoding="utf-8-sig").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            trade_id = str(row.get("trade_id", ""))
            if not trade_id:
                continue
            raw_id_counts[trade_id] = raw_id_counts.get(trade_id, 0) + 1
            finalized_rows.append(row)
    finalized_ids = {str(row["trade_id"]) for row in finalized_rows}
    completed_ids = {
        str(row.get("trade_id"))
        for row in backtested.to_dict("records") if not backtested.empty
        if row.get("final_result") in OUTCOME_ORDER and row.get("final_result") != DATA_QUALITY_AMBIGUOUS
    }
    duplicate_finalization = sorted(
        trade_id for trade_id, count in raw_id_counts.items() if count > 1
    )
    issues = []
    if delivered_ids - backtested_ids:
        issues.append(f"delivered_without_backtest={len(delivered_ids - backtested_ids)}")
    if completed_ids - finalized_ids:
        issues.append(f"backtest_without_finalized={len(completed_ids - finalized_ids)}")
    if duplicate_finalization:
        issues.append(f"duplicate_finalization={len(duplicate_finalization)}")
    cohort_keys = {}
    cross_cohort = set()
    for row in finalized_rows:
        trade_id = str(row.get("trade_id", ""))
        cohort = (row.get("market"), row.get("timeframe"), row.get("date"))
        previous = cohort_keys.setdefault(trade_id, cohort)
        if previous != cohort:
            cross_cohort.add(trade_id)
    if cross_cohort:
        issues.append(f"cross_cohort={len(cross_cohort)}")
    return {
        "delivered": len(delivered_ids),
        "backtested": len(backtested_ids),
        "finalized": len(finalized_ids),
        "issues": issues,
    }


def build_timing_analytics(records: pd.DataFrame) -> pd.DataFrame:
    if records.empty:
        return pd.DataFrame()

    frame = records.copy()
    if "filled" not in frame or "final_result" not in frame:
        return pd.DataFrame()

    frame = frame[
        (frame["filled"] == True)  # noqa: E712
        & (frame["final_result"].notna())
        & (~frame["final_result"].isin(["", "Pending"]))
    ].copy()
    if frame.empty:
        return pd.DataFrame()

    frame["time_to_resolution_seconds"] = pd.to_numeric(
        frame.get("time_to_resolution_seconds"), errors="coerce"
    )
    frame = frame[frame["time_to_resolution_seconds"].notna()].copy()
    if frame.empty:
        return pd.DataFrame()

    for column, fallback in (
        ("market", "UNKNOWN"),
        ("timeframe", ""),
        ("side", ""),
        ("rating", float("nan")),
        ("final_result", ""),
    ):
        if column not in frame:
            frame[column] = fallback

    rows: list[dict] = []
    group_columns = ["market", "timeframe", "rating", "side", "final_result"]
    for key, group in frame.groupby(group_columns, dropna=False):
        durations = pd.to_numeric(group["time_to_resolution_seconds"], errors="coerce").dropna()
        if durations.empty:
            continue
        row = dict(zip(group_columns, key))
        row["trades"] = int(len(durations))
        for hours in range(1, 7):
            row[f"resolved_within_{hours}h_pct"] = float((durations <= hours * 3600).mean() * 100.0)
        row["median_resolution_seconds"] = float(durations.median())
        row["p75_resolution_seconds"] = float(durations.quantile(0.75))
        row["p90_resolution_seconds"] = float(durations.quantile(0.90))
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(group_columns).reset_index(drop=True)


def main() -> None:
    args = parse_args()
    default_records = (
        configure_crypto_data(args.timeframe)
        if args.market in {"crypto", "xstock", "other"}
        else configure_nse_data(args.timeframe)
    )
    records = load_records(args.records or default_records, args.timeframe)
    wanted_market = {
        "nse": MARKET_NSE,
        "crypto": MARKET_CRYPTO,
        "xstock": MARKET_XSTOCK,
        "other": MARKET_OTHER,
    }[args.market]
    if not records.empty:
        records = records[records["market_class"] == wanted_market].copy()
    records = assign_report_dates(records, args.market)
    pending = load_pending_records(
        PENDING_RECORDS_PATH,
        timeframe=args.timeframe,
        market=wanted_market,
    )
    if not pending.empty:
        pending = pending[pending["market_class"] == wanted_market].copy()
        pending_ids = set(pending.get("trade_id", pd.Series(dtype=str)).astype(str))
        if not records.empty and "trade_id" in records:
            records = records[~records["trade_id"].astype(str).isin(pending_ids)].copy()
    target_date = select_target_date(records, args.date, args.market, args.timeframe)
    if target_date is None and not pending.empty and not args.date:
        # A pending-only run is a reconciliation run.  It must continue even
        # when the current crypto report bucket is not complete yet.
        target_date = max(pending["report_date"].dropna())
    if target_date is None:
        print(f"CRYPTO {args.timeframe} BACKTEST\n\nNo completed crypto report bucket yet.")
        return
    day_records = (
        records[records["report_date"] == target_date].copy()
        if not records.empty
        else records
    )

    current_day_records = day_records.copy()
    evaluation_records = pd.concat([day_records, pending], ignore_index=True) if not pending.empty else day_records
    if not evaluation_records.empty and "trade_id" in evaluation_records:
        evaluation_records = evaluation_records.drop_duplicates("trade_id", keep="last")

    frames: dict[str, pd.DataFrame] = {}
    data_failures: dict[str, str] = {}
    cooldown_blocked = 0
    results = pd.DataFrame()
    if not evaluation_records.empty:
        if args.market in {"crypto", "xstock", "other"}:
            frames, data_failures = fetch_crypto_frames(sorted(evaluation_records["symbol"].unique()))
        else:
            frames, data_failures = fetch_frames(sorted(evaluation_records["symbol"].unique()))
        results, cooldown_blocked = run_backtest(evaluation_records, frames, args.market)

        ambiguous_symbols = sorted(
            results.loc[
                results.get("final_result", pd.Series(dtype=str)) == DATA_QUALITY_AMBIGUOUS,
                "symbol",
            ].dropna().astype(str).unique()
        ) if not results.empty and "final_result" in results else []
        if ambiguous_symbols:
            fine_frames, fine_failures = fetch_resolution_frames(
                ambiguous_symbols,
                args.market,
                windows=resolution_windows(results),
            )
            data_failures.update({f"{symbol} (fine)": error for symbol, error in fine_failures.items()})
            results, cooldown_blocked = run_backtest(
                evaluation_records,
                frames,
                args.market,
                resolution_frames=fine_frames,
            )

    if CRYPTO_FETCH_SOURCE_COUNTS:
        print(f"[backtest-exchange-summary] {CRYPTO_FETCH_SOURCE_COUNTS}", file=sys.stderr)

    # The Discord report represents only today's newly delivered alerts. Pending
    # rows are reconciled in storage, but must not inflate today's alert counts.
    report_results = report_results_for_current_day(results, current_day_records, target_date)

    message = build_summary(
        current_day_records,
        target_date,
        report_results,
        data_failures,
        cooldown_blocked,
        args.timeframe,
        args.market,
    )
    print(message)
    if not args.dry_run:
        # Persist before duplicate-report gating so a rerun can still reconcile
        # a pending trade even when the Discord report was already sent.
        persist_finalized_records(target_date, args.timeframe, results, args.market)
        diagnostics = reconciliation_diagnostics(
            evaluation_records,
            results,
            FINALIZED_RECORDS_PATH,
        )
        if diagnostics["issues"]:
            print("RECONCILIATION ISSUES: " + "; ".join(diagnostics["issues"]))
        key = report_key(target_date, args.timeframe, args.market)
        if not args.force and key in load_sent_reports():
            print(f"Skipped duplicate report: {key}")
            return
        send_discord_message(message)
        mark_sent_report(key)

    if not evaluation_records.empty:
        finalized_count = int(
            (results.get("final_result", pd.Series(dtype=str)).isin(OUTCOME_ORDER)).sum()
        ) if not results.empty else 0
        pending_count = int(
            (results.get("final_result", pd.Series(dtype=str)) == "Pending").sum()
        ) if not results.empty else 0
        print(
            f"RECONCILIATION delivered={len(evaluation_records)} "
            f"backtested={len(results)} finalized={finalized_count} pending={pending_count}"
        )


if __name__ == "__main__":
    main()
