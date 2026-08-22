import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import unquote, urlencode

import ccxt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pandas as pd
import requests

from config import (
    ALERT_COOLDOWN_SECONDS,
    ALERT_RANGE_FILTER_SIGNALS,
    ATR_PERIOD,
    BOX_WIDTH,
    COINSWITCH_API_BASE_URL,
    COINSWITCH_API_KEY,
    COINSWITCH_EXCHANGE,
    COINSWITCH_SECRET_KEY,
    COINSWITCH_WATCHLIST,
    DELTA_API_BASE_URL,
    DISCORD_STATUS_WEBHOOK_URL,
    DISCORD_WEBHOOK_URL,
    ENABLE_CRYPTO_ZONE_RATINGS,
    ENABLE_XSTOCK_HYBRID_RATINGS,
    EXCHANGE_IDS,
    MAX_CONSECUTIVE_ZONE_TOUCHES,
    MAX_DISTANCE_PCT,
    MIN_CRYPTO_ZONE_SCORE,
    MIN_DISTANCE_PCT,
    HISTORY_OF_ZONES_TO_KEEP,
    MIN_DEPARTURE_ATR,
    MIN_WICK_ATR,
    MIN_WICK_TO_BODY,
    OHLCV_LIMIT,
    OVERLAP_ATR,
    PRIMARY_EXCHANGE_ID,
    PRINT_ALERTS_TO_CONSOLE,
    PRINT_SCAN_SUMMARY,
    PREFER_COINSWITCH,
    REARM_FACTOR,
    SHOW_4H_ZONE_SCORES,
    REQUIRE_COINSWITCH,
    SCAN_SLEEP,
    SCAN_WORKERS,
    SIGNAL_ALERT_COOLDOWN_SECONDS,
    SWING_LENGTH,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TIMEFRAME,
    USE_LIVE_TICKER,
    WATCHLIST,
    XSTOCK_EXTENDED_MIN_SCORE,
    XSTOCK_REGULAR_MIN_SCORE,
    ZONE_PADDING_ATR,
)
from crypto_zone_rating import rate_crypto_zone
from xstock_hybrid_rating import (
    BLOCKED_XSTOCK_SYMBOLS,
    XSTOCK_UNDERLYINGS,
    is_xstock,
    prepare_xstock_contexts,
    rate_xstock_zone,
)
from zone_scoring import score_wick_zone


STATE_FILE = Path(__file__).with_name(os.getenv("SHIVA_STATE_FILE", "alert_state.json"))
ALERT_RECORD_FILE = Path(__file__).with_name(
    os.getenv(
        "SHIVA_ALERT_RECORD_FILE",
        "crypto_alert_records_30m.jsonl" if TIMEFRAME == "30m" else "crypto_alert_records.jsonl",
    )
)
SL_BUFFER_PCT = 0.10
ZONE_REPEAT_SUPPRESSION_SECONDS = 60 * 60
EXCHANGE_OPTIONS = {
    "enableRateLimit": True,
    "options": {"defaultType": "future"},
}
EXCHANGES = [
    # dict.copy() is shallow - the nested "options" dict must be copied
    # separately, or every exchange instance would share the same
    # mutable dict object.
    getattr(ccxt, exchange_id)({**EXCHANGE_OPTIONS, "options": dict(EXCHANGE_OPTIONS["options"])})
    for exchange_id in EXCHANGE_IDS
]
EXCHANGES_BY_ID = {exchange.id: exchange for exchange in EXCHANGES}
XSTOCK_CONTEXTS = {}
TIMEFRAME_SECONDS = {
    "1m": 60,
    "3m": 3 * 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h": 60 * 60,
    "2h": 2 * 60 * 60,
    "4h": 4 * 60 * 60,
    "6h": 6 * 60 * 60,
    "12h": 12 * 60 * 60,
    "1d": 24 * 60 * 60,
    "1w": 7 * 24 * 60 * 60,
}
COINSWITCH_INTERVALS = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "2h": "120",
    "4h": "240",
    "6h": "360",
    "12h": "720",
    "1d": "1440",
}


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


def get_env_or_config(env_name, config_value):
    value = os.getenv(env_name, "").strip()
    return value if value else config_value


def coinswitch_credentials():
    return (
        get_env_or_config("COINSWITCH_API_KEY", COINSWITCH_API_KEY),
        get_env_or_config("COINSWITCH_SECRET_KEY", COINSWITCH_SECRET_KEY),
    )


def is_coinswitch_configured():
    api_key, secret_key = coinswitch_credentials()
    return bool(api_key and secret_key)


def active_watchlist():
    symbols = [
        symbol
        for symbol in WATCHLIST
        if symbol not in BLOCKED_XSTOCK_SYMBOLS
    ]
    if is_coinswitch_configured():
        for symbol in COINSWITCH_WATCHLIST:
            if symbol not in symbols and symbol not in BLOCKED_XSTOCK_SYMBOLS:
                symbols.append(symbol)
    return symbols


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

    return tr.rolling(period).mean()


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
    # 0 disables the veto entirely, matching the indicator. Without the guard
    # a threshold of 0 would flag every zone the moment it is created.
    if MAX_CONSECUTIVE_ZONE_TOUCHES > 0 and zone["max_touch_streak"] >= MAX_CONSECUTIVE_ZONE_TOUCHES:
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

    # Geometry follows the Pine indicator exactly: a fixed atr * (BOX_WIDTH/10)
    # band anchored on the pivot extreme, not the pivot candle's own wick. The
    # wick version produced the same far edge but a near edge far away from the
    # level - and the near edge is the entry, so entries and stops came out
    # several times wider than the chart implies.
    band = float(pivot_atr) * (BOX_WIDTH / 10.0)
    if zone_type == "demand":
        bottom = candle_low
        top = bottom + band
        wick_top = min(candle_open, candle_close)
        wick_bottom = candle_low
        departure = float(departure_closes.max() - wick_top)
    else:
        top = candle_high
        bottom = top - band
        wick_bottom = max(candle_open, candle_close)
        wick_top = candle_high
        departure = float(wick_bottom - departure_closes.min())

    # Recorded as metadata for the rating and later analysis. The indicator
    # applies no such tests, so they must not gate zone creation.
    wick_size = wick_top - wick_bottom
    return {
        "type": zone_type,
        "created_idx": confirmation_index,
        "pivot_idx": pivot_index,
        "top": top,
        "bottom": bottom,
        "body_entry": top if zone_type == "demand" else bottom,
        "active": True,
        "broken": False,
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

    # Create zones only after pivot confirmation, using the original pivot
    # candle's wick and the confirmed post-pivot departure.
    for confirmation_index in range(SWING_LENGTH, len(df)):
        pivot_index = confirmation_index - SWING_LENGTH
        if pivot_index in pivot_high_set:
            zone = qualify_wick_zone(df, pivot_index, confirmation_index, atr_series, "supply")
            if zone is not None and add_zone_if_not_overlapping(supply_zones, zone, zone["atr"]):
                supply_zones[:] = supply_zones[-HISTORY_OF_ZONES_TO_KEEP:]
        elif pivot_index in pivot_low_set:
            zone = qualify_wick_zone(df, pivot_index, confirmation_index, atr_series, "demand")
            if zone is not None and add_zone_if_not_overlapping(demand_zones, zone, zone["atr"]):
                demand_zones[:] = demand_zones[-HISTORY_OF_ZONES_TO_KEEP:]

        close = float(df["close"].iloc[confirmation_index])
        high = float(df["high"].iloc[confirmation_index])
        low = float(df["low"].iloc[confirmation_index])
        for zone in supply_zones:
            if zone["active"] and confirmation_index > zone["created_idx"]:
                record_zone_touch(zone, high, low)
            if zone["active"] and confirmation_index > zone["created_idx"] and close >= zone["top"]:
                zone["active"] = False
                zone["broken"] = True
        for zone in demand_zones:
            if zone["active"] and confirmation_index > zone["created_idx"]:
                record_zone_touch(zone, high, low)
            if zone["active"] and confirmation_index > zone["created_idx"] and close <= zone["bottom"]:
                zone["active"] = False
                zone["broken"] = True

    return supply_zones, demand_zones


def nearest_active_zone(price, zones, zone_type):
    nearest = None
    nearest_dist = 999.0

    for zone in zones:
        if not zone["active"] or zone.get("over_touched", False):
            continue

        # Measure to the edge price actually reaches first, which is the
        # edge the trade is entered at. Measuring to the far edge put a
        # whole zone height between the trigger and the fill, so alerts
        # could arrive with price already through the entry.
        reference = planned_entry_price(zone_type, zone)
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

    for index in range(1, len(src)):
        previous = filt.iloc[index - 1]
        price = src.iloc[index]
        range_value = smooth_range.iloc[index] if not pd.isna(smooth_range.iloc[index]) else 0

        if price > previous:
            filt.iloc[index] = previous if price - range_value < previous else price - range_value
        else:
            filt.iloc[index] = previous if price + range_value > previous else price + range_value

    upward = 0.0
    downward = 0.0
    condition_state = 0
    buy_signal = False
    sell_signal = False

    for index in range(1, len(src)):
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
            or
            (src.iloc[index] > filt.iloc[index] and src.iloc[index] < src.iloc[index - 1] and upward > 0)
        )
        short_condition = (
            (src.iloc[index] < filt.iloc[index] and src.iloc[index] < src.iloc[index - 1] and downward > 0)
            or
            (src.iloc[index] < filt.iloc[index] and src.iloc[index] > src.iloc[index - 1] and downward > 0)
        )

        previous_state = condition_state
        if long_condition:
            condition_state = 1
        elif short_condition:
            condition_state = -1

        buy_signal = long_condition and previous_state == -1
        sell_signal = short_condition and previous_state == 1

    return buy_signal, sell_signal


def is_delta_symbol(symbol):
    return "/" not in symbol and symbol.endswith("USD")


def fallback_symbol(symbol):
    # XUSD/BUSD-suffixed xStock tickers (e.g. QQQXUSD, MSTRBUSD) are
    # Delta-native symbols, not "<base>USD" crypto pairs - stripping the
    # trailing "USD" would produce a bogus ccxt symbol (QQQX/USDT) that
    # could coincidentally match an unrelated token on a small exchange.
    if is_delta_symbol(symbol) and not symbol.upper().endswith(("XUSD", "BUSD")):
        return f"{symbol[:-3]}/USDT"
    return symbol


def coinswitch_symbol(symbol):
    stable_symbol_aliases = {
        "PUMPUSD": "PUMPFUNUSDT",
        "1000SHIBUSD": "SHIB1000USDT",
    }
    upper_symbol = symbol.upper()
    if upper_symbol in stable_symbol_aliases:
        return stable_symbol_aliases[upper_symbol]
    if "/" in symbol:
        # CCXT perpetual symbols include a settlement suffix such as
        # AVGO/USDT:USDT, while CoinSwitch expects the contract as AVGOUSDT.
        return symbol.replace("/", "").split(":", 1)[0].upper()
    if upper_symbol.endswith("USDT"):
        return upper_symbol
    if upper_symbol.endswith("USD") and not upper_symbol.endswith(("XUSD", "BUSD")):
        return f"{upper_symbol[:-3]}USDT"
    return upper_symbol


def exchange_symbol_candidates(symbol):
    candidates = [symbol]
    if symbol.endswith("/USDT") and ":USDT" not in symbol:
        candidates.insert(0, f"{symbol}:USDT")
    return candidates


def fetch_exchange_ohlcv(exchange, symbol):
    candidates = exchange_symbol_candidates(symbol)
    last_error = None
    for candidate in candidates:
        try:
            return exchange.fetch_ohlcv(
                candidate, timeframe=TIMEFRAME, limit=OHLCV_LIMIT
            )
        except Exception as error:
            last_error = error
    raise last_error


def fetch_exchange_ticker(exchange, symbol):
    candidates = exchange_symbol_candidates(symbol)
    last_error = None
    for candidate in candidates:
        try:
            return exchange.fetch_ticker(candidate)
        except Exception as error:
            last_error = error
    raise last_error


def require_fresh_ohlcv(ohlcv, source_name):
    if not ohlcv:
        raise RuntimeError(f"{source_name} returned no candles")

    timeframe_seconds = TIMEFRAME_SECONDS.get(TIMEFRAME)
    if timeframe_seconds is None:
        return ohlcv

    last_candle_seconds = ohlcv[-1][0] / 1000
    max_age_seconds = timeframe_seconds * 2 + 5 * 60
    age_seconds = time.time() - last_candle_seconds
    if age_seconds > max_age_seconds:
        raise RuntimeError(
            f"{source_name} returned a stale {TIMEFRAME} candle "
            f"({age_seconds / 60:.1f} minutes old)"
        )

    return ohlcv


def fetch_delta_ohlcv(symbol, attempts=3, retry_delay=1.5):
    if not is_delta_symbol(symbol):
        return None

    timeframe_seconds = TIMEFRAME_SECONDS.get(TIMEFRAME)
    if timeframe_seconds is None:
        raise RuntimeError(f"Delta does not support timeframe {TIMEFRAME}")

    last_error = None
    for attempt in range(attempts):
        try:
            return _fetch_delta_ohlcv_once(symbol, timeframe_seconds)
        except Exception as error:
            last_error = error
            if attempt < attempts - 1:
                time.sleep(retry_delay)
    raise last_error


def _fetch_delta_ohlcv_once(symbol, timeframe_seconds):
    end_ts = int(time.time())
    start_ts = end_ts - (OHLCV_LIMIT + SWING_LENGTH * 2 + ATR_PERIOD) * timeframe_seconds
    response = requests.get(
        f"{DELTA_API_BASE_URL}/v2/history/candles",
        params={
            "symbol": symbol,
            "resolution": TIMEFRAME,
            "start": start_ts,
            "end": end_ts,
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(payload)

    candles = sorted(payload.get("result", []), key=lambda candle: candle["time"])
    if not candles:
        raise RuntimeError(f"Delta returned no candles for {symbol}")

    return [
        [
            int(candle["time"]) * 1000,
            float(candle["open"]),
            float(candle["high"]),
            float(candle["low"]),
            float(candle["close"]),
            float(candle.get("volume") or 0),
        ]
        for candle in candles[-OHLCV_LIMIT:]
    ]


def coinswitch_path_with_query(path, params):
    query = unquote(urlencode(params))
    return f"{path}?{query}" if query else path


def sign_coinswitch_request(method, path, params):
    api_key, secret_key = coinswitch_credentials()
    if not api_key or not secret_key:
        raise RuntimeError("CoinSwitch credentials are not configured")

    epoch = str(int(time.time() * 1000))
    path_query = coinswitch_path_with_query(path, params)
    message = f"{method.upper()}{path_query}{epoch}".encode("utf-8")
    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(secret_key))
    signature = private_key.sign(message).hex()
    return path_query, {
        "Content-Type": "application/json",
        "X-AUTH-APIKEY": api_key,
        "X-AUTH-SIGNATURE": signature,
        "X-AUTH-EPOCH": epoch,
    }


def fetch_coinswitch_ohlcv(symbol, attempts=3, retry_delay=1.5):
    if not is_coinswitch_configured():
        return None

    interval = COINSWITCH_INTERVALS.get(TIMEFRAME)
    if interval is None:
        raise RuntimeError(f"CoinSwitch does not support timeframe {TIMEFRAME}")

    last_error = None
    for attempt in range(attempts):
        try:
            return _fetch_coinswitch_ohlcv_once(symbol, interval)
        except Exception as error:
            last_error = error
            if attempt < attempts - 1:
                time.sleep(retry_delay)
    raise last_error


def _fetch_coinswitch_ohlcv_once(symbol, interval):
    path = "/trade/api/v2/futures/klines"
    params = {
        "exchange": get_env_or_config("COINSWITCH_EXCHANGE", COINSWITCH_EXCHANGE),
        "symbol": coinswitch_symbol(symbol),
        "interval": interval,
        "limit": OHLCV_LIMIT,
    }
    path_query, headers = sign_coinswitch_request("GET", path, params)
    response = requests.get(
        f"{COINSWITCH_API_BASE_URL}{path_query}",
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    candles = payload.get("data") or []
    if not candles:
        raise RuntimeError(f"CoinSwitch returned no candles for {symbol}")

    candles = sorted(candles, key=lambda candle: candle["start_time"])
    return [
        [
            int(candle["start_time"]),
            float(candle["o"]),
            float(candle["h"]),
            float(candle["l"]),
            float(candle["c"]),
            float(candle.get("volume") or 0),
        ]
        for candle in candles[-OHLCV_LIMIT:]
    ]


def live_ticker_price(exchange_name, symbol, candle_close):
    """Use the current last-traded price for alerts without changing candle-based zones."""
    if not USE_LIVE_TICKER:
        return candle_close, "candle_close"

    exchange = EXCHANGES_BY_ID.get(exchange_name)
    if exchange is None:
        return candle_close, "candle_close"

    try:
        ticker = fetch_exchange_ticker(exchange, fallback_symbol(symbol))
        price = ticker.get("last") or ticker.get("close")
        if price is not None and float(price) > 0:
            return float(price), "live_ticker"
    except Exception as error:
        print(f"{symbol} live ticker unavailable from {exchange_name}: {error}")

    return candle_close, "candle_close"


def scan_symbol(symbol):
    last_error = None
    ohlcv = None
    exchange_name = None
    symbol_for_fallback = fallback_symbol(symbol)

    if PREFER_COINSWITCH:
        try:
            ohlcv = require_fresh_ohlcv(fetch_coinswitch_ohlcv(symbol), "CoinSwitch")
            exchange_name = "coinswitch" if ohlcv is not None else exchange_name
        except Exception as error:
            last_error = error

        if ohlcv is None and REQUIRE_COINSWITCH:
            raise RuntimeError(f"CoinSwitch data unavailable for {symbol}: {last_error}")

    primary_exchange = EXCHANGES_BY_ID.get(PRIMARY_EXCHANGE_ID)
    if ohlcv is None and primary_exchange is not None:
        try:
            ohlcv = require_fresh_ohlcv(
                fetch_exchange_ohlcv(primary_exchange, symbol_for_fallback), primary_exchange.id
            )
            exchange_name = primary_exchange.id
        except Exception as error:
            last_error = error

    # Beyond this point the venue is no longer the one being charted, so
    # levels can drift from the chart. That is still better than no scan at
    # all: Binance is geo-blocked from GitHub Actions runners, so on CI the
    # chain really is CoinSwitch then these.
    if ohlcv is None:
        try:
            ohlcv = require_fresh_ohlcv(fetch_delta_ohlcv(symbol), "delta_india")
            exchange_name = "delta_india" if ohlcv is not None else exchange_name
        except Exception as error:
            last_error = error

    if ohlcv is None:
        for exchange in EXCHANGES:
            if exchange.id == PRIMARY_EXCHANGE_ID:
                continue

            try:
                ohlcv = require_fresh_ohlcv(fetch_exchange_ohlcv(exchange, symbol_for_fallback), exchange.id)
                exchange_name = exchange.id
                break
            except Exception as error:
                last_error = error

    if ohlcv is None:
        try:
            ohlcv = require_fresh_ohlcv(fetch_coinswitch_ohlcv(symbol), "CoinSwitch")
            exchange_name = "coinswitch" if ohlcv is not None else exchange_name
        except Exception as error:
            last_error = error

    if ohlcv is None:
        raise RuntimeError(f"all exchanges failed for {symbol}: {last_error}")

    df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])

    candle_close = float(df["close"].iloc[-1])
    price, price_source = live_ticker_price(exchange_name, symbol, candle_close)
    supply_zones, demand_zones = build_zones(df)
    nearest_supply, supply_dist = nearest_active_zone(price, supply_zones, "supply")
    nearest_demand, demand_dist = nearest_active_zone(price, demand_zones, "demand")
    buy_signal, sell_signal = get_range_filter_signals(df)
    supply_rating = None
    demand_rating = None
    supply_score = None
    demand_score = None
    should_score_zone = (
        (SHOW_4H_ZONE_SCORES and TIMEFRAME == "4h")
        or (ENABLE_XSTOCK_HYBRID_RATINGS and is_xstock(symbol))
        or (ENABLE_CRYPTO_ZONE_RATINGS and not is_xstock(symbol))
    )
    if should_score_zone:
        supply_score = score_wick_zone(
            nearest_supply, supply_dist, MIN_DISTANCE_PCT, MAX_DISTANCE_PCT
        )
        demand_score = score_wick_zone(
            nearest_demand, demand_dist, MIN_DISTANCE_PCT, MAX_DISTANCE_PCT
        )
    if ENABLE_CRYPTO_ZONE_RATINGS and supply_dist <= MAX_DISTANCE_PCT:
        supply_rating = rate_crypto_zone(
            df,
            symbol,
            TIMEFRAME,
            "supply",
            nearest_supply,
            supply_dist,
            SWING_LENGTH,
        )
    if ENABLE_CRYPTO_ZONE_RATINGS and demand_dist <= MAX_DISTANCE_PCT:
        demand_rating = rate_crypto_zone(
            df,
            symbol,
            TIMEFRAME,
            "demand",
            nearest_demand,
            demand_dist,
            SWING_LENGTH,
        )
    if ENABLE_XSTOCK_HYBRID_RATINGS and is_xstock(symbol):
        context = XSTOCK_CONTEXTS.get(symbol)
        if nearest_supply is not None:
            supply_rating = rate_xstock_zone(
                symbol,
                "supply",
                supply_score,
                price,
                context,
                XSTOCK_REGULAR_MIN_SCORE,
                XSTOCK_EXTENDED_MIN_SCORE,
            )
        if nearest_demand is not None:
            demand_rating = rate_xstock_zone(
                symbol,
                "demand",
                demand_score,
                price,
                context,
                XSTOCK_REGULAR_MIN_SCORE,
                XSTOCK_EXTENDED_MIN_SCORE,
            )

    return {
        "symbol": symbol,
        "exchange": exchange_name,
        "candle_time": int(df["time"].iloc[-1]),
        "price": price,
        "candle_close": candle_close,
        "price_source": price_source,
        "supply": nearest_supply,
        "supply_dist": supply_dist,
        "supply_rating": supply_rating,
        "supply_score": supply_score,
        "demand": nearest_demand,
        "demand_dist": demand_dist,
        "demand_rating": demand_rating,
        "demand_score": demand_score,
        "buy_signal": buy_signal,
        "sell_signal": sell_signal,
    }


def build_state_key(symbol, zone_type, zone):
    return f"{symbol}|{zone_type}|{zone['bottom']:.8f}|{zone['top']:.8f}"


def build_signal_state_key(symbol, signal_type):
    return f"{symbol}|range_filter|{signal_type}"


def display_symbol(symbol):
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


def alert_symbol(symbol):
    """Name shown in Discord alerts.

    Matches how NSE alerts read - RELIANCE.NS is shown as RELIANCE - so a
    crypto or xStock alert names the underlying rather than the venue's
    contract string. SPYXUSD reads as SPY, MSFT/USDT as MSFT.
    """
    return display_symbol(symbol)


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


def record_delivered_zone_alert(result, zone_type, zone, distance_pct, message, now_ts):
    """Persist delivered zone alerts for the daily backtest summary."""
    rating = result.get(f"{zone_type}_rating") or {}
    # Prefer the validated rating (ML crypto model or xstock hybrid) when
    # available; fall back to the transparent rule-based score for symbols
    # the rating model doesn't cover, so alerts aren't left unrated.
    score = rating.get("score")
    if score is None:
        score = result.get(f"{zone_type}_score")

    record = {
        "delivered_at_utc": pd.Timestamp.fromtimestamp(now_ts, tz="UTC").isoformat(),
        "symbol": result["symbol"],
        "exchange": result.get("exchange"),
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
        "score": score,
        "message": message,
    }
    record["trade_id"] = delivered_alert_id(record)
    try:
        with ALERT_RECORD_FILE.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, separators=(",", ":")) + "\n")
    except OSError as error:
        print(f"Crypto alert record write failed: {error}")


def format_alert(result, zone_type, zone, distance_pct):
    symbol = alert_symbol(result["symbol"])
    price = result["price"]
    side = "SELL" if zone_type == "supply" else "BUY"
    score = result.get(f"{zone_type}_score")
    rating = result.get(f"{zone_type}_rating")
    score_text = ""
    if rating and rating.get("kind") == "xstock_hybrid":
        score_text = f" | {rating['score']}/10"
    elif score is not None:
        score_text = f" | {score}/10"
    elif rating:
        if rating.get("score") is not None:
            score_text = f" | {rating['score']}/10"
        elif rating.get("rating"):
            score_text = f" | {rating['rating']}"
    stop = planned_stop_price(zone_type, zone)
    stop_distance = planned_stop_distance_pct(zone_type, zone)

    return (
        f"{symbol} | {side}{score_text}\n"
        f"Price: {price:.6f} | {distance_pct:.2f}%\n"
        f"Zone: {zone['bottom']:.6f} - {zone['top']:.6f}\n"
        f"SL: {stop:.6f} | {stop_distance:.2f}%"
    )


def format_signal_alert(result, signal_type):
    symbol = display_symbol(result["symbol"])
    price = result["price"]
    label = "BUY" if signal_type == "buy" else "SELL"

    def display_distance(zone_key, distance_key):
        if result.get(zone_key) is None or result.get(distance_key, 999.0) >= 999.0:
            return "N/A"
        return f"{result[distance_key]:.2f}%"

    message = (
        f"{symbol} Range Filter {label} signal\n"
        f"Price: {price:.6f}\n"
        f"Nearest Demand Distance: {display_distance('demand', 'demand_dist')}\n"
        f"Nearest Supply Distance: {display_distance('supply', 'supply_dist')}"
    )
    zone_type = "demand" if signal_type == "buy" else "supply"
    rating = result.get(f"{zone_type}_rating")
    if rating and rating.get("kind") == "xstock_hybrid":
        message += f"\nScore: {rating['score']}/10"
    return message


def send_telegram_message(message):
    bot_token = get_env_or_config("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
    chat_id = get_env_or_config("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)

    if not bot_token or not chat_id:
        return

    response = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data={"chat_id": chat_id, "text": message},
        timeout=15,
    )
    response.raise_for_status()


def send_discord_message(message, webhook_env_name="DISCORD_WEBHOOK_URL", webhook_config_value=DISCORD_WEBHOOK_URL):
    webhook_url = get_env_or_config(webhook_env_name, webhook_config_value)
    if not webhook_url:
        return False

    # Discord webhooks allow only a small burst of messages. Respect a 429
    # response so every eligible alert is delivered instead of silently lost.
    for attempt in range(4):
        response = requests.post(
            webhook_url,
            json={"content": message},
            timeout=15,
        )
        if response.status_code != 429:
            response.raise_for_status()
            return True

        try:
            retry_after = float(response.json().get("retry_after", 1))
        except (ValueError, AttributeError):
            retry_after = float(response.headers.get("Retry-After", 1))

        if attempt == 3:
            response.raise_for_status()

        wait_seconds = max(0.25, min(retry_after, 15.0))
        print(f"Discord rate limited; retrying alert in {wait_seconds:.2f}s")
        time.sleep(wait_seconds)

    return False


def send_alert(message):
    if PRINT_ALERTS_TO_CONSOLE:
        print("\n" + "=" * 80)
        print(message)
        print("=" * 80)

    try:
        send_telegram_message(message)
    except requests.RequestException as error:
        print(f"Telegram alert failed: {error}")

    try:
        return send_discord_message(message)
    except requests.RequestException as error:
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
            send_discord_message(
                "STATUS WEBHOOK MISSING - sending scanner status to alert channel for now.\n\n" + message
            )
    except requests.RequestException as error:
        print(f"Discord status message failed: {error}")


def process_candidate(state, result, zone_type, zone, distance_pct, now_ts):
    if zone is None:
        return False

    rating = result.get(f"{zone_type}_rating")
    if rating and rating.get("kind") == "xstock_hybrid":
        if not rating.get("alert_allowed"):
            return False
    elif TIMEFRAME == "30m" and rating is not None:
        # Preserve the validated crypto 30m rating gate unchanged.
        score = rating.get("score")
        if score is None or score < MIN_CRYPTO_ZONE_SCORE:
            return False

    state_key = build_state_key(result["symbol"], zone_type, zone)
    entry = state.setdefault(state_key, {"in_zone": False, "last_alert_at": 0.0})
    noise_state = state.setdefault("_noise_control", {})
    noise_key = exact_zone_identity(result["symbol"], zone_type, zone)
    alert_sent = False

    if MIN_DISTANCE_PCT <= distance_pct <= MAX_DISTANCE_PCT:
        should_alert = (not entry["in_zone"]) or (now_ts - entry["last_alert_at"] >= ALERT_COOLDOWN_SECONDS)
        last_success = float(noise_state.get(noise_key, 0.0) or 0.0)
        noise_open = not last_success or now_ts - last_success >= ZONE_REPEAT_SUPPRESSION_SECONDS
        if should_alert and noise_open:
            message = format_alert(result, zone_type, zone, distance_pct)
            if send_alert(message):
                entry["last_alert_at"] = now_ts
                noise_state[noise_key] = now_ts
                record_delivered_zone_alert(result, zone_type, zone, distance_pct, message, now_ts)
                alert_sent = True
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
        return False

    # A range-filter flip is actionable only as confirmation of a nearby,
    # directionally relevant zone. Ignore distant zones and missing distances
    # instead of sending misleading N/A or stale-distance alerts.
    if signal_type == "buy":
        zone = result.get("demand")
        distance_pct = result.get("demand_dist", 999.0)
    else:
        zone = result.get("supply")
        distance_pct = result.get("supply_dist", 999.0)

    if zone is None or not (MIN_DISTANCE_PCT <= distance_pct <= MAX_DISTANCE_PCT):
        return False

    zone_type = "demand" if signal_type == "buy" else "supply"
    rating = result.get(f"{zone_type}_rating")
    if (
        rating
        and rating.get("kind") == "xstock_hybrid"
        and not rating.get("alert_allowed")
    ):
        return False
    if TIMEFRAME == "30m" and rating is not None and rating.get("kind") != "xstock_hybrid":
        score = rating.get("score")
        if score is None or score < MIN_CRYPTO_ZONE_SCORE:
            return False

    signal_active = result["buy_signal"] if signal_type == "buy" else result["sell_signal"]
    if not signal_active:
        return False

    state_key = build_signal_state_key(result["symbol"], signal_type)
    entry = state.setdefault(state_key, {"last_alert_at": 0.0})
    if now_ts - entry["last_alert_at"] < SIGNAL_ALERT_COOLDOWN_SECONDS:
        return False

    if send_alert(format_signal_alert(result, signal_type)):
        entry["last_alert_at"] = now_ts
        return True

    return False


def print_summary(results):
    ranked = sorted(results, key=lambda item: min(item["supply_dist"], item["demand_dist"]))

    print("\n" + "=" * 80)
    print(f"SHIVA WATCHLIST SCAN - {TIMEFRAME}")
    print("=" * 80)

    for index, result in enumerate(ranked, start=1):
        closest = min(result["supply_dist"], result["demand_dist"])
        bias = "BUY" if result["demand_dist"] < result["supply_dist"] else "SELL"

        print(f"\n{index}. {result['symbol']} | Closest {closest:.2f}% | Bias {bias}")
        print(f"Exchange: {result['exchange']}")
        print(f"Price: {result['price']:.6f}")

        if result["supply"]:
            print(
                "Supply: "
                f"{result['supply']['bottom']:.6f} - {result['supply']['top']:.6f} "
                f"({result['supply_dist']:.2f}%)"
            )
        else:
            print("Supply: none")

        if result["demand"]:
            print(
                "Demand: "
                f"{result['demand']['bottom']:.6f} - {result['demand']['top']:.6f} "
                f"({result['demand_dist']:.2f}%)"
            )
        else:
            print("Demand: none")

        print(f"Buy Signal: {result['buy_signal']}")
        print(f"Sell Signal: {result['sell_signal']}")


def run_scan_once(state):
    global XSTOCK_CONTEXTS

    results = []
    failures = []
    alerts_sent = 0
    symbols = active_watchlist()
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    run_number = os.getenv("GITHUB_RUN_NUMBER", "local")
    trigger = os.getenv("GITHUB_EVENT_NAME", "local")
    print("\n" + "=" * 80)
    print(f"Starting scan at {started_at}")
    print("=" * 80)
    coinswitch_status = (
        "required and configured"
        if REQUIRE_COINSWITCH and is_coinswitch_configured()
        else "REQUIRED BUT NOT CONFIGURED"
        if REQUIRE_COINSWITCH
        else "preferred and configured"
        if PREFER_COINSWITCH and is_coinswitch_configured()
        else "preferred but not configured"
        if PREFER_COINSWITCH
        else "fallback only"
    )
    send_status_message(
        f"Shiva scanner started\n"
        f"Time: {started_at}\n"
        f"Run: {run_number}\n"
        f"Trigger: {trigger}\n"
        f"Timeframe: {TIMEFRAME}\n"
        f"Watchlist: {len(symbols)} symbols\n"
        f"CoinSwitch source: {coinswitch_status}"
    )

    XSTOCK_CONTEXTS = {}
    if ENABLE_XSTOCK_HYBRID_RATINGS:
        try:
            XSTOCK_CONTEXTS = prepare_xstock_contexts(symbols)
            print(
                "xStock hybrid context: "
                f"{len(XSTOCK_CONTEXTS)} verified underlyings loaded"
            )
        except Exception as error:
            # Mapped xStocks fail closed when their US context cannot load.
            print(f"xStock hybrid context unavailable: {error}")

    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as executor:
        futures = {executor.submit(scan_symbol, symbol): symbol for symbol in symbols}
        scanned_by_symbol = {}

        for future in as_completed(futures):
            symbol = futures[future]
            try:
                scanned_by_symbol[symbol] = future.result()
            except Exception as error:
                error_message = f"{symbol} -> {error}"
                failures.append(error_message)
                print(error_message)

    for symbol in symbols:
        result = scanned_by_symbol.get(symbol)
        if result is None:
            continue

        results.append(result)
        now_ts = time.time()
        if process_signal_candidate(state, result, "buy", now_ts):
            alerts_sent += 1
        if process_signal_candidate(state, result, "sell", now_ts):
            alerts_sent += 1
        if process_candidate(state, result, "supply", result["supply"], result["supply_dist"], now_ts):
            alerts_sent += 1
        if process_candidate(state, result, "demand", result["demand"], result["demand_dist"], now_ts):
            alerts_sent += 1

    save_state(state)

    if PRINT_SCAN_SUMMARY and results:
        print_summary(results)

    finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
    no_required_source_data = REQUIRE_COINSWITCH and not results
    status = "ERROR" if no_required_source_data else "OK" if not failures else "WARN"
    message = (
        f"Shiva scanner finished ({status})\n"
        f"Time: {finished_at}\n"
        f"Run: {run_number}\n"
        f"Trigger: {trigger}\n"
        f"Timeframe: {TIMEFRAME}\n"
        f"Scanned: {len(results)}/{len(symbols)} symbols\n"
        f"Alerts sent: {alerts_sent}\n"
        f"Failures: {len(failures)}"
    )
    if failures:
        message += "\n" + "\n".join(failures[:5])

    send_status_message(message)

    if no_required_source_data:
        raise RuntimeError("CoinSwitch-only scan produced no usable market data")


def parse_args():
    parser = argparse.ArgumentParser(description="Scan a fixed crypto watchlist for nearby Shiva levels.")
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
