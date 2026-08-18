import argparse
import hashlib
from io import StringIO
import json
import os
from statistics import median
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

from nse_config import (
    ALERT_COOLDOWN_SECONDS,
    ALERT_SCAN_START,
    ALERT_RANGE_FILTER_SIGNALS,
    ATR_PERIOD,
    BOX_WIDTH,
    DISCORD_NSE_WEBHOOK_URL,
    DISCORD_STATUS_WEBHOOK_URL,
    DISCORD_WEBHOOK_URL,
    FALLBACK_WATCHLIST,
    HISTORY_OF_ZONES_TO_KEEP,
    MARKET_CLOSE,
    MARKET_OPEN,
    MARKET_TIMEZONE,
    MAX_CONSECUTIVE_ZONE_TOUCHES,
    MAX_DISTANCE_PCT,
    MIN_DISTANCE_PCT,
    MIN_DEPARTURE_ATR,
    MIN_WICK_ATR,
    MIN_WICK_TO_BODY,
    NSE_INDEX_CSV_URL,
    NSE_MAX_SYMBOLS,
    OHLCV_LIMIT,
    OVERLAP_ATR,
    PRINT_ALERTS_TO_CONSOLE,
    PRINT_SCAN_SUMMARY,
    REARM_FACTOR,
    STRATEGY_CUTOFF,
    SHOW_4H_ZONE_SCORES,
    SCAN_SLEEP,
    SIGNAL_ALERT_COOLDOWN_SECONDS,
    SOURCE_INTERVAL,
    SOURCE_PERIOD,
    SWING_LENGTH,
    TIMEFRAME,
    SHOW_ZONE_RATINGS,
    ZONE_RATING_BASE,
    ZONE_PADDING_ATR,
)
from zone_scoring import score_wick_zone


STATE_FILE = Path(__file__).with_name("nse_alert_state.json")
ALERT_RECORD_FILE = Path(__file__).with_name("nse_alert_records.jsonl")
SL_BUFFER_PCT = 0.10
# Round-trip Dhan NSE equity intraday charges as a share of turnover, and
# the stop distance below which the +0.5R capital-protection rule stops
# working. Kept in step with daily_backtest_summary, which prices results
# net of the same figures.
ROUND_TRIP_COST_PCT = 0.1063
MIN_SAFE_STOP_PCT = 0.240
MARKET_DATA = {}
ZONE_REPEAT_SUPPRESSION_SECONDS = 60 * 60
NSE_SECTOR_MAP = {}
NSE_SECTOR_BIAS_THRESHOLD_PCT = float(os.getenv("NSE_SECTOR_BIAS_THRESHOLD_PCT", "1.5"))
NSE_SECTOR_BUCKETS = (
    ("Financials", ("financial", "bank", "insurance", "capital market")),
    ("Materials", ("metal", "mining", "cement", "chemical", "fertilizer", "paper", "packaging", "materials")),
    ("Industrials", ("capital goods", "construction", "engineering", "industrial", "logistics", "transport", "infrastructure")),
    ("Healthcare", ("healthcare", "pharma", "pharmaceutical", "hospital", "diagnostic", "biotech")),
    # "services" was deliberately dropped here: it's a generic qualifier
    # that real industry labels append to a specific sector name (e.g.
    # "Telecom - Services", "IT - Services"), so it was pre-empting the
    # correct, more specific bucket (Technology & Telecom) below since
    # this bucket is checked first. "consumer" alone already covers
    # genuine consumer-services labels like "Consumer Services".
    ("Consumer", ("consumer", "fmcg", "retail", "textile", "media", "hotel", "food", "beverage", "durable")),
    ("Automobile", ("automobile", "auto", "automotive")),
    ("Energy & Utilities", ("oil", "gas", "power", "energy", "utility", "utilities", "electric", "renewable")),
    ("Technology & Telecom", ("information technology", "software", "telecom", "communication", "technology")),
    ("Real Estate", ("realty", "real estate")),
    ("Diversified", ("diversified",)),
)


def parse_hhmm(value):
    hour, minute = value.split(":", 1)
    return int(hour), int(minute)


def market_window_status(now=None):
    now = now or pd.Timestamp.now(tz=ZoneInfo(MARKET_TIMEZONE))
    scan_hour, scan_minute = parse_hhmm(ALERT_SCAN_START)
    cutoff_hour, cutoff_minute = parse_hhmm(STRATEGY_CUTOFF)
    market_open = now.replace(hour=scan_hour, minute=scan_minute, second=0, microsecond=0)
    market_close = now.replace(hour=cutoff_hour, minute=cutoff_minute, second=0, microsecond=0)
    holiday_text = os.getenv("NSE_HOLIDAYS", "")
    holidays = {item.strip() for item in holiday_text.split(",") if item.strip()}
    is_session = now.weekday() < 5 and now.date().isoformat() not in holidays
    return is_session and market_open <= now <= market_close, now, market_open, market_close


def has_current_session_data(watchlist, now=None):
    """Reject stale previous-session data before producing executable alerts.

    A single symbol failing to fetch (delisted ticker, transient API hiccup)
    must not blank the entire scan - only a majority-stale feed indicates a
    real systemic staleness problem worth skipping the whole run for.
    """
    now = now or pd.Timestamp.now(tz=ZoneInfo(MARKET_TIMEZONE))
    available = 0
    current = 0
    for symbol in watchlist:
        data = MARKET_DATA.get(symbol)
        if data is None or data.empty or "Datetime" not in data.columns:
            continue
        try:
            latest = _localized_datetimes(data).iloc[-1]
        except Exception:
            continue
        available += 1
        if latest.date() == now.date():
            current += 1
    if available == 0:
        return False
    return current / available >= 0.5


def load_state():
    if not STATE_FILE.exists():
        return {}

    try:
        with STATE_FILE.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state):
    with STATE_FILE.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)


def record_delivered_zone_alert(result, zone_type, zone, distance_pct, message, now_ts):
    """Persist only alerts confirmed as delivered to Discord.

    This log is the source of truth for the later outcome evaluator. It is
    append-only so a scanner state rewrite cannot erase delivery history.
    """
    score = result.get(f"{zone_type}_score")
    if score is None and SHOW_ZONE_RATINGS and TIMEFRAME == "30m":
        score = zone_rating(zone, distance_pct)

    record = {
        "delivered_at_utc": pd.Timestamp.fromtimestamp(now_ts, tz="UTC").isoformat(),
        "symbol": result["symbol"],
        "timeframe": TIMEFRAME,
        "side": "short" if zone_type == "supply" else "long",
        "zone_type": zone_type,
        "distance_pct": float(distance_pct),
        "alert_price": float(result["price"]),
        "level": float(zone["top"] if zone_type == "supply" else zone["bottom"]),
        "zone_bottom": float(zone["bottom"]),
        "zone_top": float(zone["top"]),
        "body_entry": zone.get("body_entry"),
        "planned_entry": planned_entry_price(zone_type, zone),
        "stop_price": planned_stop_price(zone_type, zone),
        "stop_distance_pct": planned_stop_distance_pct(zone_type, zone),
        "stop_too_tight": stop_is_too_tight(planned_stop_distance_pct(zone_type, zone)),
        "score": score,
        # Raw score_wick_zone inputs, logged so a future validation pass can
        # tell which criterion actually predicts outcomes instead of only
        # seeing the capped 4-10 total (see rating_validation_report.py).
        "wick_to_body": zone.get("wick_to_body"),
        "wick_atr": zone.get("wick_atr"),
        "departure_atr": zone.get("departure_atr"),
        "touch_count": zone.get("touch_count"),
        "message": message,
    }
    record["trade_id"] = delivered_alert_id(record)
    try:
        with ALERT_RECORD_FILE.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, separators=(",", ":")) + "\n")
    except OSError as error:
        # Delivery already succeeded; surface the audit-log problem without
        # turning a valid Discord alert into a scanner failure.
        print(f"Alert record write failed: {error}")


def get_env_or_config(env_name, config_value):
    value = os.getenv(env_name, "").strip()
    return value if value else config_value


def normalize_nse_symbol(symbol):
    text = str(symbol).strip().upper()
    return text if text.endswith(".NS") else f"{text}.NS"


def classify_nse_sector(raw_industry):
    text = str(raw_industry or "").strip().lower()
    for sector, keywords in NSE_SECTOR_BUCKETS:
        if any(keyword in text for keyword in keywords):
            return sector
    return "Unclassified"


def build_sector_map_from_constituents(csv):
    symbol_column = "Symbol"
    industry_column = next(
        (
            column
            for column in csv.columns
            if str(column).strip().lower() in {"industry", "sector", "macro-economic sector", "basic industry"}
        ),
        None,
    )
    if symbol_column not in csv.columns or industry_column is None:
        return {}

    sector_map = {}
    for _, row in csv[[symbol_column, industry_column]].dropna(subset=[symbol_column]).iterrows():
        sector_map[normalize_nse_symbol(row[symbol_column])] = classify_nse_sector(row.get(industry_column))
    return sector_map


def load_watchlist():
    global NSE_SECTOR_MAP
    try:
        response = requests.get(
            NSE_INDEX_CSV_URL,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        response.raise_for_status()
        csv = pd.read_csv(StringIO(response.text))
        if "Symbol" not in csv.columns:
            raise RuntimeError("NSE index CSV did not include Symbol column")

        symbols = [normalize_nse_symbol(symbol) for symbol in csv["Symbol"].dropna()]
        symbols = list(dict.fromkeys(symbols))
        if len(symbols) < 50:
            raise RuntimeError(f"NSE index CSV returned only {len(symbols)} symbols")
        NSE_SECTOR_MAP = build_sector_map_from_constituents(csv)
        return symbols[:NSE_MAX_SYMBOLS]
    except Exception as error:
        print(f"Using fallback NSE watchlist because index CSV failed: {error}")
        NSE_SECTOR_MAP = {symbol: "Unclassified" for symbol in FALLBACK_WATCHLIST}
        return FALLBACK_WATCHLIST


def atr(df, period=50):
    high = df["high"]
    low = df["low"]
    close = df["close"]

    tr = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)

    result = pd.Series(float("nan"), index=df.index, dtype="float64")
    if len(tr) < period:
        return result

    # Pine's ta.atr() uses Wilder's RMA, seeded with the first period's SMA.
    result.iloc[period - 1] = tr.iloc[:period].mean()
    for index in range(period, len(tr)):
        result.iloc[index] = (result.iloc[index - 1] * (period - 1) + tr.iloc[index]) / period

    return result


def find_pivots(df, swing_length=10):
    highs = []
    lows = []
    high_values = df["high"].values
    low_values = df["low"].values

    for index in range(swing_length, len(df) - swing_length):
        left_highs = high_values[index - swing_length:index]
        right_highs = high_values[index + 1:index + swing_length + 1]
        if high_values[index] > left_highs.max() and high_values[index] > right_highs.max():
            highs.append(index)

        left_lows = low_values[index - swing_length:index]
        right_lows = low_values[index + 1:index + swing_length + 1]
        if low_values[index] < left_lows.min() and low_values[index] < right_lows.min():
            lows.append(index)

    return highs, lows


def zone_center(zone):
    return (zone["top"] + zone["bottom"]) / 2.0


def add_zone_if_not_overlapping(zones, new_zone, atr_value):
    atr_threshold = atr_value * OVERLAP_ATR
    new_center = zone_center(new_zone)

    for zone in zones:
        if not zone["active"]:
            continue

        existing_center = zone_center(zone)
        if existing_center - atr_threshold <= new_center <= existing_center + atr_threshold:
            return False

    zones.append(new_zone)
    return True


def record_zone_touch(zone, candle_high, candle_low):
    touches_zone = candle_high >= zone["bottom"] and candle_low <= zone["top"]
    zone["touch_streak"] = zone.get("touch_streak", 0) + 1 if touches_zone else 0
    if touches_zone:
        zone["touch_count"] = zone.get("touch_count", 0) + 1
    zone["max_touch_streak"] = max(zone.get("max_touch_streak", 0), zone["touch_streak"])
    if zone["max_touch_streak"] >= MAX_CONSECUTIVE_ZONE_TOUCHES:
        zone["over_touched"] = True


def qualify_wick_zone(df, pivot_index, confirmation_index, atr_series, zone_type):
    pivot_atr = atr_series.iloc[pivot_index]
    if pd.isna(pivot_atr):
        return None

    candle_open = float(df["open"].iloc[pivot_index])
    candle_close = float(df["close"].iloc[pivot_index])
    candle_high = float(df["high"].iloc[pivot_index])
    candle_low = float(df["low"].iloc[pivot_index])
    body_size = abs(candle_close - candle_open)
    departure_closes = df["close"].iloc[pivot_index + 1:confirmation_index + 1]
    if departure_closes.empty:
        return None

    if zone_type == "demand":
        wick_top = min(candle_open, candle_close)
        wick_bottom = candle_low
        departure = float(departure_closes.max() - wick_top)
    else:
        wick_bottom = max(candle_open, candle_close)
        wick_top = candle_high
        departure = float(wick_bottom - departure_closes.min())

    wick_size = wick_top - wick_bottom
    strong_wick = wick_size >= max(body_size * MIN_WICK_TO_BODY, 0.0)
    if (
        wick_size < float(pivot_atr) * MIN_WICK_ATR
        or not strong_wick
        or departure < float(pivot_atr) * MIN_DEPARTURE_ATR
    ):
        return None

    padding = float(pivot_atr) * ZONE_PADDING_ATR
    return {
        "type": zone_type,
        "created_idx": confirmation_index,
        "pivot_idx": pivot_index,
        "top": wick_top + padding,
        "bottom": wick_bottom - padding,
        "body_entry": wick_top if zone_type == "demand" else wick_bottom,
        "active": True,
        "touch_streak": 0,
        "touch_count": 0,
        "max_touch_streak": 0,
        "over_touched": False,
        "atr": float(pivot_atr),
        "wick_to_body": wick_size / body_size if body_size > 0 else wick_size / float(pivot_atr),
        "wick_atr": wick_size / float(pivot_atr),
        "departure_atr": departure / float(pivot_atr),
    }


def build_zones(df):
    atr_series = atr(df, ATR_PERIOD)
    if atr_series.isna().all():
        return [], []

    pivot_highs, pivot_lows = find_pivots(df, SWING_LENGTH)
    pivot_high_set = set(pivot_highs)
    pivot_low_set = set(pivot_lows)
    supply_zones = []
    demand_zones = []

    # Qualify only confirmed pivot wicks with enough rejection and departure.
    for confirmation_index in range(SWING_LENGTH, len(df)):
        pivot_index = confirmation_index - SWING_LENGTH
        if pivot_index in pivot_high_set:
            zone = qualify_wick_zone(df, pivot_index, confirmation_index, atr_series, "supply")
            if zone is not None and add_zone_if_not_overlapping(supply_zones, zone, zone["atr"]):
                supply_zones = supply_zones[-HISTORY_OF_ZONES_TO_KEEP:]
        elif pivot_index in pivot_low_set:
            zone = qualify_wick_zone(df, pivot_index, confirmation_index, atr_series, "demand")
            if zone is not None and add_zone_if_not_overlapping(demand_zones, zone, zone["atr"]):
                demand_zones = demand_zones[-HISTORY_OF_ZONES_TO_KEEP:]

        close = float(df["close"].iloc[confirmation_index])
        high = float(df["high"].iloc[confirmation_index])
        low = float(df["low"].iloc[confirmation_index])
        for zone in supply_zones:
            if zone["active"] and confirmation_index > zone["created_idx"]:
                record_zone_touch(zone, high, low)
            if zone["active"] and confirmation_index > zone["created_idx"] and close >= zone["top"]:
                zone["active"] = False
        for zone in demand_zones:
            if zone["active"] and confirmation_index > zone["created_idx"]:
                record_zone_touch(zone, high, low)
            if zone["active"] and confirmation_index > zone["created_idx"] and close <= zone["bottom"]:
                zone["active"] = False

    return supply_zones, demand_zones


def nearest_active_zone(price, zones, zone_type):
    nearest = None
    nearest_dist = 999.0

    for zone in zones:
        if not zone["active"] or zone.get("over_touched", False):
            continue

        reference = zone["top"] if zone_type == "supply" else zone["bottom"]
        distance = abs(reference - price) / price * 100.0
        if distance < nearest_dist:
            nearest = zone
            nearest_dist = distance

    return nearest, nearest_dist


def get_range_filter_signals(df):
    src = df["close"]
    period = 100
    multiplier = 3.0

    def smoothrng(series, length, mult):
        weighted_period = length * 2 - 1
        average_range = series.diff().abs().ewm(span=length, adjust=False).mean()
        return average_range.ewm(span=weighted_period, adjust=False).mean() * mult

    smooth_range = smoothrng(src, period, multiplier)
    filt = src.copy()
    filt.iloc[0] = src.iloc[0]
    upward = 0.0
    downward = 0.0
    condition_state = 0
    buy_signal = False
    sell_signal = False

    for index in range(1, len(src)):
        previous = filt.iloc[index - 1]
        price = src.iloc[index]
        range_value = smooth_range.iloc[index] if not pd.isna(smooth_range.iloc[index]) else 0

        if price > previous:
            filt.iloc[index] = previous if price - range_value < previous else price - range_value
        else:
            filt.iloc[index] = previous if price + range_value > previous else price + range_value

        if filt.iloc[index] > filt.iloc[index - 1]:
            upward += 1
        elif filt.iloc[index] < filt.iloc[index - 1]:
            upward = 0

        if filt.iloc[index] < filt.iloc[index - 1]:
            downward += 1
        elif filt.iloc[index] > filt.iloc[index - 1]:
            downward = 0

        long_condition = (
            (src.iloc[index] > filt.iloc[index] and src.iloc[index] > src.iloc[index - 1] and upward > 0)
            or (src.iloc[index] > filt.iloc[index] and src.iloc[index] < src.iloc[index - 1] and upward > 0)
        )
        short_condition = (
            (src.iloc[index] < filt.iloc[index] and src.iloc[index] < src.iloc[index - 1] and downward > 0)
            or (src.iloc[index] < filt.iloc[index] and src.iloc[index] > src.iloc[index - 1] and downward > 0)
        )

        previous_state = condition_state
        if long_condition:
            condition_state = 1
        elif short_condition:
            condition_state = -1

        buy_signal = long_condition and previous_state == -1
        sell_signal = short_condition and previous_state == 1

    return buy_signal, sell_signal


def normalize_yfinance_columns(data):
    if not isinstance(data.columns, pd.MultiIndex):
        return {None: data}

    tickers = set(data.columns.get_level_values(1))
    if tickers and all(str(ticker).endswith(".NS") for ticker in tickers):
        return {ticker: data.xs(ticker, axis=1, level=1, drop_level=True) for ticker in tickers}

    tickers = set(data.columns.get_level_values(0))
    return {ticker: data.xs(ticker, axis=1, level=0, drop_level=True) for ticker in tickers}


def yfinance_time_range(now=None):
    if SOURCE_INTERVAL != "1h":
        return {"period": SOURCE_PERIOD}

    # Yahoo can ignore an intraday period for newer listings and request from
    # the IPO date, which its API rejects when that date is over 730 days old.
    end = now or (pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=1))
    start = end - pd.Timedelta(days=700)
    return {"start": start.to_pydatetime(), "end": end.to_pydatetime()}


def resample_for_timeframe(data):
    if TIMEFRAME == "30m" and SOURCE_INTERVAL == "15m":
        return data.resample("30min", origin="start_day", offset="15min").agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        ).dropna()

    if TIMEFRAME == "4h":
        # Anchor four-hour candles to the NSE open (09:15), not 08:15.
        return data.resample("4h", origin="start_day", offset="1h15min").agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        ).dropna()

    return data


def confirmed_candles(data, now=None):
    if data.empty or "Datetime" not in data.columns:
        return data

    durations = {"30m": pd.Timedelta(minutes=30), "4h": pd.Timedelta(hours=4)}
    duration = durations.get(TIMEFRAME)
    if duration is None:
        return data

    candle_start = pd.Timestamp(data["Datetime"].iloc[-1])
    timezone = candle_start.tz
    now = now or pd.Timestamp.now(tz=timezone)
    close_hour, close_minute = parse_hhmm(MARKET_CLOSE)
    session_close = candle_start.replace(hour=close_hour, minute=close_minute, second=0, microsecond=0)
    candle_close = min(candle_start + duration, session_close)

    if now < candle_close:
        return data.iloc[:-1].copy()
    return data


def prepare_ohlcv(data):
    if data.empty:
        raise RuntimeError("empty candle data")

    data = data.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    data = data[["open", "high", "low", "close", "volume"]].dropna()

    data = resample_for_timeframe(data)

    if len(data) < ATR_PERIOD + SWING_LENGTH * 2:
        raise RuntimeError(f"not enough candles after resample: {len(data)}")

    return data.tail(OHLCV_LIMIT).reset_index()


def fetch_market_data(watchlist):
    global MARKET_DATA
    MARKET_DATA = {}
    chunk_size = 50

    for start in range(0, len(watchlist), chunk_size):
        chunk = watchlist[start:start + chunk_size]
        try:
            raw = yf.download(
                tickers=" ".join(chunk),
                interval=SOURCE_INTERVAL,
                auto_adjust=False,
                progress=False,
                threads=True,
                group_by="column",
                **yfinance_time_range(),
            )
        except Exception as error:
            print(f"chunk starting at {chunk[0]} -> yf.download failed: {error}")
            continue
        grouped = normalize_yfinance_columns(raw)

        if None in grouped and len(chunk) == 1:
            grouped = {chunk[0]: grouped[None]}

        for symbol in chunk:
            symbol_data = grouped.get(symbol)
            if symbol_data is None or symbol_data.empty:
                continue

            try:
                MARKET_DATA[symbol] = prepare_ohlcv(symbol_data)
            except Exception as error:
                print(f"{symbol} -> data preparation failed: {error}")


def fetch_stock_ohlcv(symbol):
    cached = MARKET_DATA.get(symbol)
    if cached is not None:
        return cached

    data = yf.download(
        symbol,
        interval=SOURCE_INTERVAL,
        auto_adjust=False,
        progress=False,
        threads=False,
        **yfinance_time_range(),
    )
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    return prepare_ohlcv(data)


def _localized_datetimes(df):
    datetimes = pd.to_datetime(df["Datetime"])
    if getattr(datetimes.dt, "tz", None) is None:
        return datetimes.dt.tz_localize(MARKET_TIMEZONE)
    return datetimes.dt.tz_convert(MARKET_TIMEZONE)


def stock_session_move_pct(df):
    if df is None or df.empty or "Datetime" not in df.columns or len(df) < 2:
        return None

    try:
        localized = _localized_datetimes(df)
        latest_date = localized.iloc[-1].date()
        same_session = df.loc[localized.dt.date == latest_date]
        if same_session.empty:
            return None

        base = float(same_session["open"].iloc[0])
        latest = float(df["close"].iloc[-1])
        if base <= 0:
            return None
        return (latest - base) / base * 100.0
    except Exception:
        return None


def build_sector_context(watchlist):
    grouped_moves = {}
    for symbol in watchlist:
        sector = NSE_SECTOR_MAP.get(symbol, "Unclassified")
        move = stock_session_move_pct(MARKET_DATA.get(symbol))
        if move is None:
            continue
        grouped_moves.setdefault(sector, []).append(move)

    return {
        sector: {
            "session_pct": median(moves),
            "members": len(moves),
        }
        for sector, moves in grouped_moves.items()
    }


def attach_sector_context(result, sector_context):
    sector = NSE_SECTOR_MAP.get(result["symbol"], "Unclassified")
    context = sector_context.get(sector)
    result["sector"] = sector
    result["sector_session_pct"] = context["session_pct"] if context else None
    result["sector_member_count"] = context["members"] if context else 0
    return result


def sector_bias_line(result, zone_type):
    sector = result.get("sector")
    move = result.get("sector_session_pct")
    if not sector or move is None:
        return None

    if abs(move) < NSE_SECTOR_BIAS_THRESHOLD_PCT:
        label = "OK"
    else:
        wants_up = zone_type == "demand"
        supports_trade = move > 0 if wants_up else move < 0
        label = "Good" if supports_trade else "Risk"

    return f"{sector}: {move:+.2f}% | {label}"


def sector_coverage_summary(watchlist):
    counts = {}
    for symbol in watchlist:
        sector = NSE_SECTOR_MAP.get(symbol, "Unclassified")
        counts[sector] = counts.get(sector, 0) + 1
    return ", ".join(f"{sector}: {counts[sector]}" for sector in sorted(counts))


def scan_symbol(symbol):
    df = fetch_stock_ohlcv(symbol)
    price = float(df["close"].iloc[-1])
    indicator_df = confirmed_candles(df)
    if len(indicator_df) < ATR_PERIOD + SWING_LENGTH * 2:
        raise RuntimeError(f"not enough confirmed candles: {len(indicator_df)}")

    supply_zones, demand_zones = build_zones(indicator_df)
    for zone in supply_zones:
        if zone["active"] and price >= zone["top"]:
            zone["active"] = False
    for zone in demand_zones:
        if zone["active"] and price <= zone["bottom"]:
            zone["active"] = False

    nearest_supply, supply_dist = nearest_active_zone(price, supply_zones, "supply")
    nearest_demand, demand_dist = nearest_active_zone(price, demand_zones, "demand")
    buy_signal, sell_signal = get_range_filter_signals(indicator_df)
    supply_score = None
    demand_score = None
    should_score_zones = (SHOW_4H_ZONE_SCORES and TIMEFRAME == "4h") or (
        SHOW_ZONE_RATINGS and TIMEFRAME == "30m"
    )
    if should_score_zones:
        supply_score = score_wick_zone(
            nearest_supply, supply_dist, MIN_DISTANCE_PCT, MAX_DISTANCE_PCT
        )
        demand_score = score_wick_zone(
            nearest_demand, demand_dist, MIN_DISTANCE_PCT, MAX_DISTANCE_PCT
        )

    return {
        "symbol": symbol,
        "price": price,
        "supply": nearest_supply,
        "supply_dist": supply_dist,
        "supply_score": supply_score,
        "demand": nearest_demand,
        "demand_dist": demand_dist,
        "demand_score": demand_score,
        "buy_signal": buy_signal,
        "sell_signal": sell_signal,
    }


def build_state_key(symbol, zone_type, zone):
    return f"{symbol}|{zone_type}|{zone['bottom']:.4f}|{zone['top']:.4f}"


def build_signal_state_key(symbol, signal_type):
    return f"{symbol}|range_filter|{signal_type}"


def display_symbol(symbol):
    text = str(symbol).strip().upper()
    if text.endswith(".NS"):
        return text[:-3]
    return text


def planned_entry_price(zone_type, zone):
    """Use the near/body edge as the practical planned entry."""
    return float(zone["top"] if zone_type == "demand" else zone["bottom"])


def planned_stop_price(zone_type, zone, buffer_pct=SL_BUFFER_PCT):
    """Place SL beyond the far zone edge with a small fixed buffer."""
    if zone_type == "demand":
        return float(zone["bottom"]) * (1 - buffer_pct / 100.0)
    return float(zone["top"]) * (1 + buffer_pct / 100.0)


def planned_stop_distance_pct(zone_type, zone, buffer_pct=SL_BUFFER_PCT):
    entry = planned_entry_price(zone_type, zone)
    if entry == 0:
        return 0.0
    stop = planned_stop_price(zone_type, zone, buffer_pct)
    return abs(entry - stop) / abs(entry) * 100.0


def delivered_alert_id(record):
    """Stable ID carried from alert log into daily/weekly backtest summaries."""
    parts = [
        str(record.get("symbol", "")).upper(),
        str(record.get("timeframe", "")),
        str(record.get("side", "")),
        f"{float(record.get('zone_bottom', 0.0)):.10f}",
        f"{float(record.get('zone_top', 0.0)):.10f}",
        str(record.get("delivered_at_utc", "")),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def stop_is_too_tight(stop_distance_pct):
    """True when +0.5R arrives before the trade is even net positive.

    Reaching +0.5R only moves price half the stop distance. If that is
    less than the round-trip cost cushion, moving the stop up at +0.5R
    still locks in a loss, so the capital-protection rule cannot work on
    this setup at all.
    """
    return float(stop_distance_pct) < MIN_SAFE_STOP_PCT


def format_alert(result, zone_type, zone, distance_pct):
    side = "SELL" if zone_type == "supply" else "BUY"
    score = result.get(f"{zone_type}_score")
    score_text = ""
    if score is not None:
        score_text = f" | {score}/10"
    elif SHOW_ZONE_RATINGS and TIMEFRAME == "30m":
        score_text = f" | {zone_rating(zone, distance_pct)}/10"
    stop = planned_stop_price(zone_type, zone)
    stop_distance = planned_stop_distance_pct(zone_type, zone)
    lines = [
        f"{display_symbol(result['symbol'])} | {side}{score_text}\n"
        f"Price: {result['price']:.2f} | {distance_pct:.2f}%\n"
        f"Zone: {zone['bottom']:.2f} - {zone['top']:.2f}\n"
        f"SL: {stop:.2f} | {stop_distance:.2f}%"
    ]
    if stop_is_too_tight(stop_distance):
        lines.append(
            f"WARNING SL under {MIN_SAFE_STOP_PCT:.2f}% - at +0.5R the move "
            f"is only {stop_distance / 2:.3f}%, under the {ROUND_TRIP_COST_PCT:.4f}% "
            f"round trip, so moving the stop up cannot protect capital here"
        )
    bias = sector_bias_line(result, zone_type)
    if bias:
        lines.append(bias)
    return "\n".join(lines)


def zone_rating(zone, distance_pct):
    """Return a transparent display score, not a validated predictor."""
    score = ZONE_RATING_BASE
    midpoint = (MIN_DISTANCE_PCT + MAX_DISTANCE_PCT) / 2
    if distance_pct <= midpoint:
        score += 1
    if zone.get("max_touch_streak", 0) == 0:
        score += 1
    return min(10, score)


def format_signal_alert(result, signal_type):
    label = "BUY" if signal_type == "buy" else "SELL"

    def display_distance(zone_key, distance_key):
        if result.get(zone_key) is None or result.get(distance_key, 999.0) >= 999.0:
            return "N/A"
        return f"{result[distance_key]:.2f}%"

    return (
        f"{display_symbol(result['symbol'])} Range Filter {label} signal\n"
        f"Price: {result['price']:.2f}\n"
        f"Nearest Demand Distance: {display_distance('demand', 'demand_dist')}\n"
        f"Nearest Supply Distance: {display_distance('supply', 'supply_dist')}"
    )


def send_discord_message(message, webhook_env_name="DISCORD_WEBHOOK_URL", webhook_config_value=DISCORD_WEBHOOK_URL):
    webhook_url = get_env_or_config(webhook_env_name, webhook_config_value)
    if not webhook_url:
        raise RuntimeError(f"{webhook_env_name} is not configured")

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


def send_alert(message):
    if PRINT_ALERTS_TO_CONSOLE:
        print("\n" + "=" * 80)
        print(message)
        print("=" * 80)

    try:
        if get_env_or_config("DISCORD_NSE_WEBHOOK_URL", DISCORD_NSE_WEBHOOK_URL):
            send_discord_message(
                message,
                webhook_env_name="DISCORD_NSE_WEBHOOK_URL",
                webhook_config_value=DISCORD_NSE_WEBHOOK_URL,
            )
        else:
            send_discord_message(message)
        return True
    except (RuntimeError, requests.RequestException) as error:
        print(f"Discord alert failed: {error}")
        return False


def send_status_message(message):
    print(message)

    try:
        status_webhook = get_env_or_config("DISCORD_STATUS_WEBHOOK_URL", DISCORD_STATUS_WEBHOOK_URL)
        alert_webhook = get_env_or_config("DISCORD_WEBHOOK_URL", DISCORD_WEBHOOK_URL)

        if status_webhook:
            send_discord_message(
                message,
                webhook_env_name="DISCORD_STATUS_WEBHOOK_URL",
                webhook_config_value=DISCORD_STATUS_WEBHOOK_URL,
            )
        elif alert_webhook:
            send_discord_message("NSE STATUS WEBHOOK MISSING - sending status to alert channel.\n\n" + message)
    except requests.RequestException as error:
        print(f"Discord status message failed: {error}")


def process_candidate(state, result, zone_type, zone, distance_pct, now_ts):
    if zone is None:
        return None

    state_key = build_state_key(result["symbol"], zone_type, zone)
    entry = state.setdefault(
        state_key,
        {"in_zone": False, "last_alert_at": 0.0, "last_attempt_at": 0.0},
    )
    noise_state = state.setdefault("_noise_control", {})
    noise_key = exact_zone_identity(result["symbol"], zone_type, zone)
    alert_sent = None

    if MIN_DISTANCE_PCT <= distance_pct <= MAX_DISTANCE_PCT:
        last_attempt_at = max(entry.get("last_alert_at", 0.0), entry.get("last_attempt_at", 0.0))
        should_alert = (not entry["in_zone"]) or (now_ts - last_attempt_at >= ALERT_COOLDOWN_SECONDS)
        last_success = float(noise_state.get(noise_key, 0.0) or 0.0)
        noise_open = not last_success or now_ts - last_success >= ZONE_REPEAT_SUPPRESSION_SECONDS
        if should_alert and noise_open:
            entry["last_attempt_at"] = now_ts
            message = format_alert(result, zone_type, zone, distance_pct)
            alert_sent = send_alert(message)
            if alert_sent:
                entry["last_alert_at"] = now_ts
                noise_state[noise_key] = now_ts
                record_delivered_zone_alert(
                    result, zone_type, zone, distance_pct, message, now_ts
                )
        elif should_alert and last_success:
            remaining = max(0, int(ZONE_REPEAT_SUPPRESSION_SECONDS - (now_ts - last_success)))
            print(f"Suppressed repeat alert: {noise_key} | {remaining // 60}m remaining")
        entry["in_zone"] = True
    # Keep the successful-delivery timestamp through a zone touch.  A touch
    # must not re-arm the same zone before the suppression window expires.
    elif distance_pct > MAX_DISTANCE_PCT * REARM_FACTOR:
        entry["in_zone"] = False

    return alert_sent


def exact_zone_identity(symbol, zone_type, zone):
    side = "long" if zone_type == "demand" else "short"
    return (
        f"{str(symbol).upper()}|{TIMEFRAME}|{side}|"
        f"{float(zone['bottom']):.10f}|{float(zone['top']):.10f}"
    )


def process_signal_candidate(state, result, signal_type, now_ts):
    if not ALERT_RANGE_FILTER_SIGNALS:
        return None

    # A range-filter signal is useful only as confirmation of a nearby,
    # directionally relevant zone. Do not send standalone signals for distant
    # zones or for missing distances (which previously produced N/A alerts).
    if signal_type == "buy":
        zone = result.get("demand")
        distance_pct = result.get("demand_dist", 999.0)
    else:
        zone = result.get("supply")
        distance_pct = result.get("supply_dist", 999.0)

    if zone is None or not (MIN_DISTANCE_PCT <= distance_pct <= MAX_DISTANCE_PCT):
        return None

    signal_active = result["buy_signal"] if signal_type == "buy" else result["sell_signal"]
    if not signal_active:
        return None

    state_key = build_signal_state_key(result["symbol"], signal_type)
    entry = state.setdefault(state_key, {"last_alert_at": 0.0, "last_attempt_at": 0.0})
    last_attempt_at = max(entry.get("last_alert_at", 0.0), entry.get("last_attempt_at", 0.0))
    if now_ts - last_attempt_at < SIGNAL_ALERT_COOLDOWN_SECONDS:
        return None

    entry["last_attempt_at"] = now_ts
    alert_sent = send_alert(format_signal_alert(result, signal_type))
    if alert_sent:
        entry["last_alert_at"] = now_ts
    return alert_sent


def print_summary(results):
    ranked = sorted(results, key=lambda item: min(item["supply_dist"], item["demand_dist"]))
    print("\n" + "=" * 80)
    print(f"SHIVA NSE SCAN - {TIMEFRAME}")
    print("=" * 80)

    for index, result in enumerate(ranked, start=1):
        closest = min(result["supply_dist"], result["demand_dist"])
        bias = "BUY" if result["demand_dist"] < result["supply_dist"] else "SELL"
        print(f"\n{index}. {result['symbol']} | Closest {closest:.2f}% | Bias {bias}")
        print(f"Price: {result['price']:.2f}")

        if result["supply"]:
            print(
                "Supply: "
                f"{result['supply']['bottom']:.2f} - {result['supply']['top']:.2f} "
                f"({result['supply_dist']:.2f}%)"
            )
        else:
            print("Supply: none")

        if result["demand"]:
            print(
                "Demand: "
                f"{result['demand']['bottom']:.2f} - {result['demand']['top']:.2f} "
                f"({result['demand_dist']:.2f}%)"
            )
        else:
            print("Demand: none")

        print(f"Buy Signal: {result['buy_signal']}")
        print(f"Sell Signal: {result['sell_signal']}")


def run_scan_once(state):
    watchlist = load_watchlist()
    results = []
    failures = []
    alerts_sent = 0
    alert_delivery_failures = 0
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    run_number = os.getenv("GITHUB_RUN_NUMBER", "local")
    trigger = os.getenv("GITHUB_EVENT_NAME", "local")
    is_market_open, market_now, market_open, market_close = market_window_status()

    if not is_market_open:
        send_status_message(
            f"Shiva NSE scanner skipped - market closed\n"
            f"Time: {market_now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
            f"Run: {run_number}\n"
            f"Trigger: {trigger}\n"
            f"Market window: {market_open.strftime('%H:%M')} - {market_close.strftime('%H:%M')} IST"
        )
        return

    trade_start_hour, trade_start_minute = parse_hhmm(MARKET_OPEN)
    trade_start = market_now.replace(
        hour=trade_start_hour,
        minute=trade_start_minute,
        second=0,
        microsecond=0,
    )
    if market_now < trade_start:
        send_status_message(
            "Shiva NSE scanner context-only pre-open update\n"
            f"Time: {market_now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
            "Reference Price: Previous Close\n"
            "Executable alerts begin at 09:15 IST."
        )
        return

    send_status_message(
        f"Shiva NSE scanner started\n"
        f"Time: {started_at}\n"
        f"Run: {run_number}\n"
        f"Trigger: {trigger}\n"
        f"Timeframe: {TIMEFRAME}\n"
        f"Watchlist: {len(watchlist)} symbols\n"
        f"Sectors: {sector_coverage_summary(watchlist)}"
    )

    fetch_market_data(watchlist)
    if not has_current_session_data(watchlist, market_now):
        send_status_message(
            "Shiva NSE scanner skipped - stale or incomplete session data\n"
            f"Time: {market_now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
            "Reference Price: Previous Close\n"
            "No executable alerts were generated."
        )
        return
    sector_context = build_sector_context(watchlist)
    scanned_by_symbol = {}
    for symbol in watchlist:
        try:
            scanned_by_symbol[symbol] = attach_sector_context(scan_symbol(symbol), sector_context)
        except Exception as error:
            error_message = f"{symbol} -> {error}"
            failures.append(error_message)
            print(error_message)

    for symbol in watchlist:
        result = scanned_by_symbol.get(symbol)
        if result is None:
            continue

        results.append(result)
        now_ts = time.time()
        alert_results = [
            process_signal_candidate(state, result, "buy", now_ts),
            process_signal_candidate(state, result, "sell", now_ts),
            process_candidate(state, result, "supply", result["supply"], result["supply_dist"], now_ts),
            process_candidate(state, result, "demand", result["demand"], result["demand_dist"], now_ts),
        ]
        alerts_sent += sum(1 for alert_result in alert_results if alert_result is True)
        alert_delivery_failures += sum(1 for alert_result in alert_results if alert_result is False)

    save_state(state)

    if PRINT_SCAN_SUMMARY and results:
        print_summary(results)

    finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
    status = "OK" if not failures else "WARN"
    message = (
        f"Shiva NSE scanner finished ({status})\n"
        f"Time: {finished_at}\n"
        f"Run: {run_number}\n"
        f"Trigger: {trigger}\n"
        f"Scanned: {len(results)}/{len(watchlist)} symbols\n"
        f"Alerts sent: {alerts_sent}\n"
        f"Alert delivery failures: {alert_delivery_failures}\n"
        f"Failures: {len(failures)}"
    )
    if failures:
        message += "\n" + "\n".join(failures[:5])

    send_status_message(message)


def parse_args():
    parser = argparse.ArgumentParser(description="Scan NSE stocks for nearby Shiva levels.")
    parser.add_argument("--once", action="store_true", help="Run a single scan and exit.")
    return parser.parse_args()


def main():
    args = parse_args()
    state = load_state()

    if args.once:
        run_scan_once(state)
        return

    while True:
        run_scan_once(state)
        print("\n" + "=" * 80)
        print(f"Waiting {SCAN_SLEEP} seconds...")
        print("=" * 80)
        time.sleep(SCAN_SLEEP)


if __name__ == "__main__":
    main()
