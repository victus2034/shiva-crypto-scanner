import os
from datetime import time as datetime_time


def env_int(name, default):
    value = os.getenv(name, "").strip()
    try:
        return int(value) if value else default
    except ValueError:
        return default


def env_float(name, default):
    value = os.getenv(name, "").strip()
    try:
        return float(value) if value else default
    except ValueError:
        return default


def env_flag(name, default=False):
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


CRYPTO_WATCHLIST = [
    "BTCUSD",
    "ETHUSD",
    "SOLUSD",
    "BANK/USDT",
    "XRPUSD",
    "HYPEUSD",
    "AKE/USDT",
    "COTI/USDT",
    "ZECUSD",
    "DOGEUSD",
    "ADAUSD",
    "NEARUSD",
    "DEXE/USDT",
    "1000PEPEUSD",
    "ONDOUSD",
    "SOON/USDT",
    "AAVEUSD",
    "WLD/USDT",
    "KAITO/USDT",
    "PUMPUSD",
    "BEAT/USDT",
    "SUIUSD",
    "ENA/USDT",
    "EUL/USDT",
    "ZIL/USDT",
    "UNIUSD",
    "LINKUSD",
    "TAO/USDT",
    "AVAXUSD",
    "1000SHIBUSD",
    "LTCUSD",
    "BTW/USDT",
    "LA/USDT",
    "BNBUSD",
    "OPUSD",
    "INJUSD",
    "FARTCOIN/USDT",
    "GRAMUSD",
    "XPLUSD",
    "ESPORTS/USDT",
    "XLM/USDT",
    "ASTER/USDT",
    "ZAMA/USDT",
    "XMRUSD",
    "TRUMP/USDT",
    "ARBUSD",
    "WIF/USDT",
    "ESP/USDT",
    "LDO/USDT",
    "APTUSD",
    "PENGU/USDT",
    "1000BONKUSD",
    "BCHUSD",
    "DOTUSD",
    "UB/USDT",
    "ZRO/USDT",
    "VVV/USDT",
    "ATOM/USDT",
    "AERO/USDT",
    "TRX/USDT",
    "ALLO/USDT",
    "SEIUSD",
    "CAP/USDT",
    "RE/USDT",
    "VIRTUAL/USDT",
    "FILUSD",
    "US/USDT",
    "HBAR/USDT",
    "ICP/USDT",
    "BOME/USDT",
    "ORDI/USDT",
    "COAI/USDT",
    "TIAUSD",
    "WLFI/USDT",
    "LABUSD",
    "JUP/USDT",
    "O/USDT",
    "JTO/USDT",
    "MNT/USDT",
    "STRK/USDT",
    "ERA/USDT",
    "CRV/USDT",
    "MMT/USDT",
    "STORJ/USDT",
    "ALGO/USDT",
    "ETHFI/USDT",
    "DASH/USDT",
    "GALA/USDT",
    "PEOPLE/USDT",
    "0G/USDT",
    "HOME/USDT",
    "POL/USDT",
    "KGEN/USDT",
    "GWEI/USDT",
    # Added from a CoinSwitch volume sweep, checked over a month rather than
    # a day so a spike could not pass for a book. All four traded every one
    # of the last thirty days. Per 30m candle, against a watchlist median
    # near 203,000: CL about 1,090,000, KORU 978,000, ACE 739,000, and ETC
    # 80,000 - the steadiest of them, and the only one here that is a major.
    "CL/USDT",
    "KORU/USDT",
    "ACE/USDT",
    "ETC/USDT",
]

# Keep non-crypto contracts separate from the CoinSwitch crypto liquidity audit.
OTHER_WATCHLIST = [
    "PAXGUSD",
    "SLVONUSD",
]

XSTOCK_WATCHLIST = [
    "TSLAXUSD",
    "METAXUSD",
    "AAPLXUSD",
    "CRCLXUSD",
    "GOOGLXUSD",
    "COINXUSD",
    "SOXLBUSD",
    "SNDKBUSD",
    "MUBUSD",
    "SPCXXUSD",
    "INTCBUSD",
    "MSTRBUSD",
    # Removed (no live data on Delta/CoinSwitch/any exchange - confirmed
    # via a two-round audit 30s apart, all 5 failed both times):
    # QQQXUSD, NVDAXUSD, EWYBUSD, DRAMBUSD, CBRSBUSD
    "SKHYNIX/USDT:USDT",
    "NBIS/USDT:USDT",
    "BZ/USDT:USDT",
    "SAMSUNG/USDT:USDT",
    "AXTI/USDT:USDT",
    "HOOD/USDT:USDT",
    "MRVL/USDT:USDT",
    # Removed for thin volume, measured on CoinSwitch over 96 30m candles.
    # The watchlist median is about 200,000 in traded value per candle;
    # every symbol below sat under 11,000, and FLNC went a full 30 minutes
    # with no trades at all seven times in two days. A zone price drifts
    # into on no volume is a zone nobody can be filled in:
    # FLNC, IBM, PHAROS, SOXX, NVDL, BABA, DELL, AVGO, TAIKO, TQQQ
    # Then OPENAI (2,914 per candle, 3 of 96 bars with no trades at all)
    # and AMZN (5,279), both of which only became measurable once the
    # xStocks were being fetched under the names CoinSwitch uses.
    # VANRY went with them: not listed on CoinSwitch, and its last candle
    # was ten days old, so it was never a thin feed but a dead one.
    # SPY too, at 6,366: the token is thin even though the ETF behind it
    # is not. SPY stays in the rating registry as its own sector marker.
    # Additional CoinSwitch US-stock futures approved for the liquidity pilot.
    "SLX/USDT:USDT",
    "MSFT/USDT:USDT",
]

WATCHLIST = CRYPTO_WATCHLIST + OTHER_WATCHLIST + XSTOCK_WATCHLIST

COINSWITCH_WATCHLIST = []

DELTA_API_BASE_URL = "https://api.india.delta.exchange"
COINSWITCH_API_BASE_URL = "https://coinswitch.co"
COINSWITCH_EXCHANGE = "EXCHANGE_2"
COINSWITCH_API_KEY = ""
COINSWITCH_SECRET_KEY = ""
# CoinSwitch is the venue actually charted and traded, so zones must be
# built from its candles. Binance is only a fallback for symbols it does
# not carry. Defaulting this off meant Binance was always primary and the
# alerted levels never matched the chart.
PREFER_COINSWITCH = env_flag("SHIVA_PREFER_COINSWITCH", default=True)
REQUIRE_COINSWITCH = env_flag("SHIVA_REQUIRE_COINSWITCH")
USE_LIVE_TICKER = env_flag("SHIVA_USE_LIVE_TICKER")
PRIMARY_EXCHANGE_ID = "binance"
# CoinSwitch first, then Binance. The rest exist because Binance is
# geo-blocked from GitHub Actions runners - without them a CI scan has no
# source at all once CoinSwitch misses, which is exactly what happened when
# this list was trimmed to Binance alone.
EXCHANGE_IDS = ["binance", "kucoin", "okx", "bybit", "mexc", "bitget", "lbank", "coinex"]
TIMEFRAME = os.getenv("SHIVA_TIMEFRAME", "4h").strip() or "4h"
OHLCV_LIMIT = 500

SWING_LENGTH = 10
ATR_PERIOD = 50
BOX_WIDTH = 2.5
HISTORY_OF_ZONES_TO_KEEP = 20
# Matches the Pine indicator's f_check_overlapping, which rejects a new zone
# whose midpoint sits within atr * 2 of an existing one.
OVERLAP_ATR = 2.0
# The Pine indicator applies no wick, body-ratio or departure test - every
# confirmed pivot becomes a zone. These are kept only as metadata on the zone
# for the rating and for later analysis, never as filters, so the zone set
# matches what the chart draws.
MIN_WICK_ATR = 0.15
MIN_WICK_TO_BODY = 1.5
MIN_DEPARTURE_ATR = 0.75
# Zones are a fixed atr * (BOX_WIDTH / 10) band anchored on the pivot extreme,
# exactly as the indicator draws them, so no separate padding applies.
ZONE_PADDING_ATR = 0.0

# Distance is measured to the entry edge - the one price reaches first -
# so this is "how far is price from the level I would actually trade".
# Alert as soon as a symbol comes within MAX_DISTANCE_PCT of it.
MIN_DISTANCE_PCT = env_float("SHIVA_MIN_DISTANCE_PCT", 0.0)
MAX_DISTANCE_PCT = env_float("SHIVA_MAX_DISTANCE_PCT", 0.20)
REARM_FACTOR = 1.25
# 0 disables the over-touch veto. The Pine indicator counts no touches and
# never retires a zone for being revisited - only a close through it kills the
# zone - so any positive value here drops levels the chart still shows.
# Back-to-back candles sitting on a zone mean price is grinding through it
# rather than reacting to it - thin volume, no rejection. Two consecutive
# touching candles retire the zone. This is deliberately stricter than the
# Pine indicator, which has no touch veto at all: the indicator draws every
# level, this decides which are worth an alert.
MAX_CONSECUTIVE_ZONE_TOUCHES = 2

# A zone has to stand before it means anything. A level confirmed a candle
# or two ago that price is already sitting on was never defended - it is
# just the recent high or low, and alerting on it produces the small, risky
# levels that are not worth a trade. Age is counted from confirmation, so a
# 30m zone must survive twenty candles - about ten hours - before it can
# raise an alert, and a 4h zone a little over three days.
# Twenty rather than fifteen because both markets said so: replayed on 5m
# candles, the alerts this blocks earned 0.054R on NSE and 0.389R on
# crypto, against 0.122R and 0.564R for the ones that survive it.
MIN_ZONE_AGE_CANDLES = env_int("SHIVA_MIN_ZONE_AGE_CANDLES", 20)
# How many candles a feed may be behind before it counts as dead.
# CoinSwitch omits any bucket with no trades and its higher-timeframe
# series trails the live market, so at 14:55 the newest 30m candle was
# 13:30 for BTC and 13:00 for XRP - while their 1m candles and tickers
# were current to the second. Two bars plus five minutes rejected that
# as stale and sent the symbol to an exchange the user does not chart,
# which is the opposite of what the check is for. Four bars still
# catches a genuinely dead feed - VANRY was ten days behind.
STALE_BARS_ALLOWED = env_int("SHIVA_STALE_BARS_ALLOWED", 4)

# Crypto trades around the clock, but the user does not. Alerts are held
# outside 08:00-01:00 IST so nothing fires while nobody is awake to take
# it - an alert at 04:00 is not an opportunity, it is a missed trade in
# the morning's scrollback. The window wraps midnight, so the end hour is
# earlier than the start hour on the clock.
CRYPTO_ALERT_START = datetime_time(8, 0)
CRYPTO_ALERT_END = datetime_time(1, 0)

SCAN_SLEEP = 300
SCAN_WORKERS = 8
ALERT_COOLDOWN_SECONDS = env_int("SHIVA_ALERT_COOLDOWN_SECONDS", 4 * 60 * 60)
ALERT_RANGE_FILTER_SIGNALS = True
SIGNAL_ALERT_COOLDOWN_SECONDS = env_int("SHIVA_SIGNAL_ALERT_COOLDOWN_SECONDS", 4 * 60 * 60)
# The previous model was trained on the old ATR-strip zones. Keep ratings off
# until a model trained on the polished wick zones passes out-of-sample checks.
ENABLE_CRYPTO_ZONE_RATINGS = env_flag(
    "SHIVA_ENABLE_CRYPTO_ZONE_RATINGS",
    default=True,
)
# Only validated crypto zone ratings above 5/10 are eligible for live alerts.
MIN_CRYPTO_ZONE_SCORE = env_int("SHIVA_MIN_CRYPTO_ZONE_SCORE", 6)
# Show the transparent rule-based quality score on every 4h crypto/xstock zone.
SHOW_4H_ZONE_SCORES = env_flag("SHIVA_SHOW_4H_ZONE_SCORES", default=True)
ENABLE_XSTOCK_HYBRID_RATINGS = env_flag(
    "SHIVA_ENABLE_XSTOCK_HYBRID_RATINGS",
    default=True,
)
XSTOCK_REGULAR_MIN_SCORE = env_int("SHIVA_XSTOCK_REGULAR_MIN_SCORE", 5)
XSTOCK_EXTENDED_MIN_SCORE = env_int("SHIVA_XSTOCK_EXTENDED_MIN_SCORE", 5)

PRINT_SCAN_SUMMARY = True
PRINT_ALERTS_TO_CONSOLE = True

TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""
DISCORD_WEBHOOK_URL = ""
DISCORD_STATUS_WEBHOOK_URL = ""
