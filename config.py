import os


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
    "VANRY/USDT",
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
    "PHAROS/USDT",
    "VIRTUAL/USDT",
    "FILUSD",
    "US/USDT",
    "HBAR/USDT",
    "ICP/USDT",
    "BOME/USDT",
    "ORDI/USDT",
    "COAI/USDT",
    "TAIKO/USDT",
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
]

# Keep non-crypto contracts separate from the CoinSwitch crypto liquidity audit.
OTHER_WATCHLIST = [
    "PAXGUSD",
    "SLVONUSD",
]

XSTOCK_WATCHLIST = [
    "TSLAXUSD",
    "METAXUSD",
    "SPYXUSD",
    "AMZNXUSD",
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
    "AVGO/USDT:USDT",
    "IBM/USDT:USDT",
    "BABA/USDT:USDT",
    "OPENAI/USDT:USDT",
    "NBIS/USDT:USDT",
    "BZ/USDT:USDT",
    "SAMSUNG/USDT:USDT",
    "AXTI/USDT:USDT",
    "HOOD/USDT:USDT",
    "MRVL/USDT:USDT",
    "FLNC/USDT:USDT",
    "DELL/USDT:USDT",
    # Additional CoinSwitch US-stock futures approved for the liquidity pilot.
    "NVDL/USDT:USDT",
    "SLX/USDT:USDT",
    "SOXX/USDT:USDT",
    "MSFT/USDT:USDT",
    "TQQQ/USDT:USDT",
]

WATCHLIST = CRYPTO_WATCHLIST + OTHER_WATCHLIST + XSTOCK_WATCHLIST

COINSWITCH_WATCHLIST = []

DELTA_API_BASE_URL = "https://api.india.delta.exchange"
COINSWITCH_API_BASE_URL = "https://coinswitch.co"
COINSWITCH_EXCHANGE = "EXCHANGE_2"
COINSWITCH_API_KEY = ""
COINSWITCH_SECRET_KEY = ""
PREFER_COINSWITCH = env_flag("SHIVA_PREFER_COINSWITCH")
REQUIRE_COINSWITCH = env_flag("SHIVA_REQUIRE_COINSWITCH")
USE_LIVE_TICKER = env_flag("SHIVA_USE_LIVE_TICKER")
PRIMARY_EXCHANGE_ID = "binance"
EXCHANGE_IDS = ["binance", "kucoin", "okx", "bybit", "mexc", "bitget", "lbank", "coinex"]
TIMEFRAME = os.getenv("SHIVA_TIMEFRAME", "4h").strip() or "4h"
OHLCV_LIMIT = 500

SWING_LENGTH = 10
ATR_PERIOD = 50
BOX_WIDTH = 2.5
HISTORY_OF_ZONES_TO_KEEP = 20
OVERLAP_ATR = 1.0
MIN_WICK_ATR = 0.15
MIN_WICK_TO_BODY = 1.5
MIN_DEPARTURE_ATR = 0.75
# Keep alert zones on the confirmed candle wick. ATR padding shifts the
# reported Level away from the actual wick, especially on low-priced symbols.
ZONE_PADDING_ATR = 0.0

# Distance is measured to the entry edge - the one price reaches first -
# so this is "how far is price from the level I would actually trade".
# Alert as soon as a symbol comes within MAX_DISTANCE_PCT of it.
MIN_DISTANCE_PCT = env_float("SHIVA_MIN_DISTANCE_PCT", 0.0)
MAX_DISTANCE_PCT = env_float("SHIVA_MAX_DISTANCE_PCT", 0.20)
REARM_FACTOR = 1.25
MAX_CONSECUTIVE_ZONE_TOUCHES = 2
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
