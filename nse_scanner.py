import argparse
from io import StringIO
import json
import os
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

from nse_config import (
    ALERT_COOLDOWN_SECONDS,
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
    MAX_DISTANCE_PCT,
    NSE_INDEX_CSV_URL,
    NSE_MAX_SYMBOLS,
    OHLCV_LIMIT,
    PRINT_ALERTS_TO_CONSOLE,
    PRINT_SCAN_SUMMARY,
    REARM_FACTOR,
    SCAN_SLEEP,
    SIGNAL_ALERT_COOLDOWN_SECONDS,
    SOURCE_INTERVAL,
    SOURCE_PERIOD,
    SWING_LENGTH,
    TIMEFRAME,
)


STATE_FILE = Path(__file__).with_name("nse_alert_state.json")
MARKET_DATA = {}


def parse_hhmm(value):
    hour, minute = value.split(":", 1)
    return int(hour), int(minute)


def market_window_status(now=None):
    now = now or pd.Timestamp.now(tz=ZoneInfo(MARKET_TIMEZONE))
    open_hour, open_minute = parse_hhmm(MARKET_OPEN)
    close_hour, close_minute = parse_hhmm(MARKET_CLOSE)
    market_open = now.replace(hour=open_hour, minute=open_minute, second=0, microsecond=0)
    market_close = now.replace(hour=close_hour, minute=close_minute, second=0, microsecond=0)
    is_weekday = now.weekday() < 5
    return is_weekday and market_open <= now <= market_close, now, market_open, market_close


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


def load_watchlist():
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

        symbols = [f"{symbol.strip()}.NS" for symbol in csv["Symbol"].dropna()]
        symbols = list(dict.fromkeys(symbols))
        if len(symbols) < 50:
            raise RuntimeError(f"NSE index CSV returned only {len(symbols)} symbols")
        return symbols[:NSE_MAX_SYMBOLS]
    except Exception as error:
        print(f"Using fallback NSE watchlist because index CSV failed: {error}")
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
    atr_threshold = atr_value * 2.0
    new_center = zone_center(new_zone)

    for zone in zones:
        if not zone["active"]:
            continue

        existing_center = zone_center(zone)
        if existing_center - atr_threshold <= new_center <= existing_center + atr_threshold:
            return False

    zones.append(new_zone)
    return True


def build_zones(df):
    atr_series = atr(df, ATR_PERIOD)
    if atr_series.isna().all():
        return [], []

    pivot_highs, pivot_lows = find_pivots(df, SWING_LENGTH)
    pivot_high_set = set(pivot_highs)
    pivot_low_set = set(pivot_lows)
    supply_zones = []
    demand_zones = []

    # Pine confirms a pivot SWING_LENGTH bars later, creates its box using the
    # confirmation bar's ATR, then checks all active boxes for breaks. Keeping
    # this chronological order lets a broken box stop blocking future boxes.
    for confirmation_index in range(SWING_LENGTH, len(df)):
        pivot_index = confirmation_index - SWING_LENGTH
        confirmation_atr = atr_series.iloc[confirmation_index]

        if not pd.isna(confirmation_atr):
            atr_buffer = confirmation_atr * (BOX_WIDTH / 10.0)
            if pivot_index in pivot_high_set:
                top = float(df["high"].iloc[pivot_index])
                zone = {
                    "type": "supply",
                    "created_idx": confirmation_index,
                    "pivot_idx": pivot_index,
                    "top": top,
                    "bottom": top - atr_buffer,
                    "active": True,
                }
                if add_zone_if_not_overlapping(supply_zones, zone, confirmation_atr):
                    supply_zones = supply_zones[-HISTORY_OF_ZONES_TO_KEEP:]
            elif pivot_index in pivot_low_set:
                bottom = float(df["low"].iloc[pivot_index])
                zone = {
                    "type": "demand",
                    "created_idx": confirmation_index,
                    "pivot_idx": pivot_index,
                    "top": bottom + atr_buffer,
                    "bottom": bottom,
                    "active": True,
                }
                if add_zone_if_not_overlapping(demand_zones, zone, confirmation_atr):
                    demand_zones = demand_zones[-HISTORY_OF_ZONES_TO_KEEP:]

        close = float(df["close"].iloc[confirmation_index])
        for zone in supply_zones:
            if zone["active"] and close >= zone["top"]:
                zone["active"] = False
        for zone in demand_zones:
            if zone["active"] and close <= zone["bottom"]:
                zone["active"] = False

    return supply_zones, demand_zones


def nearest_active_zone(price, zones, zone_type):
    nearest = None
    nearest_dist = 999.0

    for zone in zones:
        if not zone["active"]:
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
        return data.resample("4h", origin="start_day", offset="15min").agg(
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
        raw = yf.download(
            tickers=" ".join(chunk),
            interval=SOURCE_INTERVAL,
            auto_adjust=False,
            progress=False,
            threads=True,
            group_by="column",
            **yfinance_time_range(),
        )
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

    return {
        "symbol": symbol,
        "price": price,
        "supply": nearest_supply,
        "supply_dist": supply_dist,
        "demand": nearest_demand,
        "demand_dist": demand_dist,
        "buy_signal": buy_signal,
        "sell_signal": sell_signal,
    }


def build_state_key(symbol, zone_type, zone):
    return f"{symbol}|{zone_type}|{zone['bottom']:.4f}|{zone['top']:.4f}"


def build_signal_state_key(symbol, signal_type):
    return f"{symbol}|range_filter|{signal_type}"


def format_alert(result, zone_type, zone, distance_pct):
    reference = zone["top"] if zone_type == "supply" else zone["bottom"]
    side = "SELL zone" if zone_type == "supply" else "BUY zone"
    return (
        f"{result['symbol']} is {distance_pct:.2f}% away from a {side}\n"
        f"Price: {result['price']:.2f}\n"
        f"Level: {reference:.2f}\n"
        f"Zone: {zone['bottom']:.2f} - {zone['top']:.2f}"
    )


def format_signal_alert(result, signal_type):
    label = "BUY" if signal_type == "buy" else "SELL"
    return (
        f"{result['symbol']} Range Filter {label} signal\n"
        f"Price: {result['price']:.2f}\n"
        f"Nearest Demand Distance: {result['demand_dist']:.2f}%\n"
        f"Nearest Supply Distance: {result['supply_dist']:.2f}%"
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
    alert_sent = None

    if distance_pct <= MAX_DISTANCE_PCT:
        last_attempt_at = max(entry.get("last_alert_at", 0.0), entry.get("last_attempt_at", 0.0))
        should_alert = (not entry["in_zone"]) or (now_ts - last_attempt_at >= ALERT_COOLDOWN_SECONDS)
        if should_alert:
            entry["last_attempt_at"] = now_ts
            alert_sent = send_alert(format_alert(result, zone_type, zone, distance_pct))
            if alert_sent:
                entry["last_alert_at"] = now_ts
        entry["in_zone"] = True
    elif distance_pct > MAX_DISTANCE_PCT * REARM_FACTOR:
        entry["in_zone"] = False

    return alert_sent


def process_signal_candidate(state, result, signal_type, now_ts):
    if not ALERT_RANGE_FILTER_SIGNALS:
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

    send_status_message(
        f"Shiva NSE scanner started\n"
        f"Time: {started_at}\n"
        f"Run: {run_number}\n"
        f"Trigger: {trigger}\n"
        f"Timeframe: {TIMEFRAME}\n"
        f"Watchlist: {len(watchlist)} symbols"
    )

    fetch_market_data(watchlist)
    scanned_by_symbol = {}
    for symbol in watchlist:
        try:
            scanned_by_symbol[symbol] = scan_symbol(symbol)
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
