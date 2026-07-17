import os


def env_int(name, default):
    value = os.getenv(name, "").strip()
    try:
        return int(value) if value else default
    except ValueError:
        return default


def env_flag(name, default=False):
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


WATCHLIST = [
    "BTCUSD",
    "ETHUSD",
    "PAXGUSD",
    "SOLUSD",
    "XRPUSD",
    "SLVONUSD",
    "DOGEUSD",
    "ZECUSD",
    "HYPEUSD",
    "RIVERUSD",
    "LINKUSD",
    "LTCUSD",
    "AVAXUSD",
    "QQQXUSD",
    "TSLAXUSD",
    "SUIUSD",
    "METAXUSD",
    "SPYXUSD",
    "AMZNXUSD",
    "NVDAXUSD",
    "AAPLXUSD",
    "XMRUSD",
    "CRCLXUSD",
    "GOOGLXUSD",
    "COINXUSD",
    "BNBUSD",
    "ADAUSD",
    "DOTUSD",
    "BCHUSD",
    "NEARUSD",
    "AAVEUSD",
    "UNIUSD",
    "APTUSD",
    "ARBUSD",
    "OPUSD",
    "INJUSD",
    "TIAUSD",
    "SEIUSD",
    "FILUSD",
    "ETCUSD",
    "TRIA/USDT",
    "VIRTUAL/USDT",
    "ONDOUSD",
    "FET/USDT",
    "PUMPUSD",
    "T/USDT",
    "1000BONKUSD",
    "LDO/USDT",
    "CRV/USDT",
    "XLM/USDT",
    "MUSD",
    "GRAMUSD",
    "XPLUSD",
    "LABUSD",
    "DODO/USDT",
    "DEXE/USDT",
    "AIOTUSD",
    "VELVET/USDT",
    "1000SHIBUSD",
    "FARTCOIN/USDT",
    "SXT/USDT",
    "BILLUSD",
    "SYN/USDT",
    "WLD/USDT",
    "1000PEPEUSD",
    "LIT/USDT",
    "ALLO/USDT",
    "EVAAUSD",
    "ENA/USDT",
    "TAO/USDT",
    "SOXLBUSD",
    "SNDKBUSD",
    "MUBUSD",
    "SPCXXUSD",
    "EWYBUSD",
    "DRAMBUSD",
    "CBRSBUSD",
    "INTCBUSD",
    "MSTRBUSD",
    "RIF/USDT",
    "THE/USDT",
    "MAGMA/USDT",
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
]

COINSWITCH_WATCHLIST = []

DELTA_API_BASE_URL = "https://api.india.delta.exchange"
COINSWITCH_API_BASE_URL = "https://coinswitch.co"
COINSWITCH_EXCHANGE = "EXCHANGE_2"
COINSWITCH_API_KEY = ""
COINSWITCH_SECRET_KEY = ""
PREFER_COINSWITCH = env_flag("SHIVA_PREFER_COINSWITCH")
REQUIRE_COINSWITCH = env_flag("SHIVA_REQUIRE_COINSWITCH")
PRIMARY_EXCHANGE_ID = "binance"
EXCHANGE_IDS = ["binance", "kucoin", "okx", "bybit", "mexc", "bitget", "lbank", "coinex"]
TIMEFRAME = os.getenv("SHIVA_TIMEFRAME", "4h").strip() or "4h"
OHLCV_LIMIT = 500

SWING_LENGTH = 10
ATR_PERIOD = 50
BOX_WIDTH = 2.5

MAX_DISTANCE_PCT = 1.5
REARM_FACTOR = 1.25
SCAN_SLEEP = 300
SCAN_WORKERS = 8
ALERT_COOLDOWN_SECONDS = env_int("SHIVA_ALERT_COOLDOWN_SECONDS", 4 * 60 * 60)
ALERT_RANGE_FILTER_SIGNALS = True
SIGNAL_ALERT_COOLDOWN_SECONDS = env_int("SHIVA_SIGNAL_ALERT_COOLDOWN_SECONDS", 4 * 60 * 60)

PRINT_SCAN_SUMMARY = True
PRINT_ALERTS_TO_CONSOLE = True

TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""
DISCORD_WEBHOOK_URL = ""
DISCORD_STATUS_WEBHOOK_URL = ""
