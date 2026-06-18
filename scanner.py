import argparse
import json
import os
import time
from pathlib import Path

import ccxt
import pandas as pd
import requests

from config import (
    ALERT_COOLDOWN_SECONDS,
    ATR_PERIOD,
    BOX_WIDTH,
    DISCORD_WEBHOOK_URL,
    EXCHANGE_IDS,
    MAX_DISTANCE_PCT,
    OHLCV_LIMIT,
    PRINT_ALERTS_TO_CONSOLE,
    PRINT_SCAN_SUMMARY,
    REARM_FACTOR,
    SCAN_SLEEP,
    SWING_LENGTH,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TIMEFRAME,
    WATCHLIST,
)


STATE_FILE = Path(__file__).with_name("alert_state.json")
EXCHANGES = [getattr(ccxt, exchange_id)({"enableRateLimit": True}) for exchange_id in EXCHANGE_IDS]


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

    latest_atr = atr_series.iloc[-1]
    if pd.isna(latest_atr):
        return [], []

    atr_buffer = latest_atr * (BOX_WIDTH / 10.0)
    pivot_highs, pivot_lows = find_pivots(df, SWING_LENGTH)

    supply_zones = []
    demand_zones = []

    events = [("high", index) for index in pivot_highs] + [("low", index) for index in pivot_lows]
    events.sort(key=lambda event: event[1])

    for kind, index in events:
        if kind == "high":
            top = float(df["high"].iloc[index])
            bottom = top - atr_buffer
            zone = {
                "type": "supply",
                "created_idx": index,
                "top": top,
                "bottom": bottom,
                "active": True,
                "broken": False,
            }
            add_zone_if_not_overlapping(supply_zones, zone, latest_atr)
        else:
            bottom = float(df["low"].iloc[index])
            top = bottom + atr_buffer
            zone = {
                "type": "demand",
                "created_idx": index,
                "top": top,
                "bottom": bottom,
                "active": True,
                "broken": False,
            }
            add_zone_if_not_overlapping(demand_zones, zone, latest_atr)

    closes = df["close"].values

    for zone in supply_zones:
        for index in range(zone["created_idx"] + 1, len(df)):
            if closes[index] >= zone["top"]:
                zone["active"] = False
                zone["broken"] = True
                zone["broken_idx"] = index
                zone["bos_level"] = zone_center(zone)
                break

    for zone in demand_zones:
        for index in range(zone["created_idx"] + 1, len(df)):
            if closes[index] <= zone["bottom"]:
                zone["active"] = False
                zone["broken"] = True
                zone["broken_idx"] = index
                zone["bos_level"] = zone_center(zone)
                break

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


def scan_symbol(symbol):
    last_error = None
    ohlcv = None
    exchange_name = None

    for exchange in EXCHANGES:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=OHLCV_LIMIT)
            exchange_name = exchange.id
            break
        except Exception as error:
            last_error = error

    if ohlcv is None:
        raise RuntimeError(f"all exchanges failed for {symbol}: {last_error}")

    df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])

    price = float(df["close"].iloc[-1])
    supply_zones, demand_zones = build_zones(df)
    nearest_supply, supply_dist = nearest_active_zone(price, supply_zones, "supply")
    nearest_demand, demand_dist = nearest_active_zone(price, demand_zones, "demand")
    buy_signal, sell_signal = get_range_filter_signals(df)

    return {
        "symbol": symbol,
        "exchange": exchange_name,
        "price": price,
        "supply": nearest_supply,
        "supply_dist": supply_dist,
        "demand": nearest_demand,
        "demand_dist": demand_dist,
        "buy_signal": buy_signal,
        "sell_signal": sell_signal,
    }


def build_state_key(symbol, zone_type, zone):
    return f"{symbol}|{zone_type}|{zone['bottom']:.8f}|{zone['top']:.8f}"


def format_alert(result, zone_type, zone, distance_pct):
    symbol = result["symbol"]
    price = result["price"]
    reference = zone["top"] if zone_type == "supply" else zone["bottom"]
    side = "SELL zone" if zone_type == "supply" else "BUY zone"

    return (
        f"{symbol} is {distance_pct:.2f}% away from a {side}\n"
        f"Price: {price:.6f}\n"
        f"Level: {reference:.6f}\n"
        f"Zone: {zone['bottom']:.6f} - {zone['top']:.6f}\n"
        f"Range Filter Buy Signal: {result['buy_signal']}\n"
        f"Range Filter Sell Signal: {result['sell_signal']}\n"
        f"Timeframe: {TIMEFRAME}"
    )


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


def send_discord_message(message):
    webhook_url = get_env_or_config("DISCORD_WEBHOOK_URL", DISCORD_WEBHOOK_URL)
    if not webhook_url:
        return

    response = requests.post(
        webhook_url,
        json={"content": message},
        timeout=15,
    )
    response.raise_for_status()


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
        send_discord_message(message)
    except requests.RequestException as error:
        print(f"Discord alert failed: {error}")


def process_candidate(state, result, zone_type, zone, distance_pct, now_ts):
    if zone is None:
        return

    state_key = build_state_key(result["symbol"], zone_type, zone)
    entry = state.setdefault(state_key, {"in_zone": False, "last_alert_at": 0.0})

    if distance_pct <= MAX_DISTANCE_PCT:
        should_alert = (not entry["in_zone"]) or (now_ts - entry["last_alert_at"] >= ALERT_COOLDOWN_SECONDS)
        if should_alert:
            send_alert(format_alert(result, zone_type, zone, distance_pct))
            entry["last_alert_at"] = now_ts
        entry["in_zone"] = True
    elif distance_pct > MAX_DISTANCE_PCT * REARM_FACTOR:
        entry["in_zone"] = False


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
    results = []
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "=" * 80)
    print(f"Starting scan at {started_at}")
    print("=" * 80)

    for symbol in WATCHLIST:
        try:
            result = scan_symbol(symbol)
            results.append(result)
            now_ts = time.time()
            process_candidate(state, result, "supply", result["supply"], result["supply_dist"], now_ts)
            process_candidate(state, result, "demand", result["demand"], result["demand_dist"], now_ts)
        except Exception as error:
            print(f"{symbol} -> {error}")

    save_state(state)

    if PRINT_SCAN_SUMMARY and results:
        print_summary(results)


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
