NSE_INDEX_CSV_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
NSE_MAX_SYMBOLS = 400

FALLBACK_WATCHLIST = [
    "ABB.NS",
    "ADANIENSOL.NS",
    "ADANIENT.NS",
    "ADANIGREEN.NS",
    "ADANIPORTS.NS",
    "AMBUJACEM.NS",
    "APOLLOHOSP.NS",
    "ASIANPAINT.NS",
    "AXISBANK.NS",
    "BAJAJ-AUTO.NS",
    "BAJFINANCE.NS",
    "BAJAJFINSV.NS",
    "BANKBARODA.NS",
    "BEL.NS",
    "BHARTIARTL.NS",
    "BOSCHLTD.NS",
    "BPCL.NS",
    "BRITANNIA.NS",
    "CANBK.NS",
    "CHOLAFIN.NS",
    "CIPLA.NS",
    "COALINDIA.NS",
    "DABUR.NS",
    "DIVISLAB.NS",
    "DLF.NS",
    "DMART.NS",
    "DRREDDY.NS",
    "EICHERMOT.NS",
    "ETERNAL.NS",
    "GAIL.NS",
    "GODREJCP.NS",
    "GRASIM.NS",
    "HAL.NS",
    "HAVELLS.NS",
    "HCLTECH.NS",
    "HDFCBANK.NS",
    "HDFCLIFE.NS",
    "HEROMOTOCO.NS",
    "HINDALCO.NS",
    "HINDUNILVR.NS",
    "HYUNDAI.NS",
    "ICICIBANK.NS",
    "ICICIGI.NS",
    "ICICIPRULI.NS",
    "INDIGO.NS",
    "INDUSINDBK.NS",
    "INFY.NS",
    "IOC.NS",
    "IRFC.NS",
    "ITC.NS",
    "JINDALSTEL.NS",
    "JIOFIN.NS",
    "JSWENERGY.NS",
    "JSWSTEEL.NS",
    "KOTAKBANK.NS",
    "LICI.NS",
    "LODHA.NS",
    "LT.NS",
    "LTIM.NS",
    "M&M.NS",
    "MARUTI.NS",
    "MAXHEALTH.NS",
    "MOTHERSON.NS",
    "NAUKRI.NS",
    "NESTLEIND.NS",
    "NTPC.NS",
    "ONGC.NS",
    "PFC.NS",
    "PIDILITIND.NS",
    "PNB.NS",
    "POWERGRID.NS",
    "RECLTD.NS",
    "RELIANCE.NS",
    "SBICARD.NS",
    "SBILIFE.NS",
    "SBIN.NS",
    "SHREECEM.NS",
    "SHRIRAMFIN.NS",
    "SIEMENS.NS",
    "SUNPHARMA.NS",
    "SWIGGY.NS",
    "TATACONSUM.NS",
    "TATAMOTORS.NS",
    "TATAPOWER.NS",
    "TATASTEEL.NS",
    "TCS.NS",
    "TECHM.NS",
    "TITAN.NS",
    "TORNTPHARM.NS",
    "TRENT.NS",
    "TVSMOTOR.NS",
    "ULTRACEMCO.NS",
    "UNIONBANK.NS",
    "UNITDSPR.NS",
    "VBL.NS",
    "VEDL.NS",
    "WIPRO.NS",
    "ZYDUSLIFE.NS",
]

TIMEFRAME = "4h"
SOURCE_INTERVAL = "1h"
SOURCE_PERIOD = "700d"
MARKET_TIMEZONE = "Asia/Kolkata"
MARKET_OPEN = "09:15"
MARKET_CLOSE = "15:30"
ALERT_SCAN_START = "09:00"
TRADE_START = "09:15"
STRATEGY_CUTOFF = "15:10"
REPORT_TIME = "16:30"

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
MIN_DISTANCE_PCT = 0.0
MAX_DISTANCE_PCT = 0.20
REARM_FACTOR = 1.25
MAX_CONSECUTIVE_ZONE_TOUCHES = 2
SCAN_SLEEP = 300
SCAN_WORKERS = 8
ALERT_COOLDOWN_SECONDS = 4 * 60 * 60
ALERT_RANGE_FILTER_SIGNALS = True
SIGNAL_ALERT_COOLDOWN_SECONDS = 4 * 60 * 60

PRINT_SCAN_SUMMARY = True
PRINT_ALERTS_TO_CONSOLE = True

# Display-only ratings for the isolated NSE 30m backtest phase.
SHOW_ZONE_RATINGS = False
ZONE_RATING_BASE = 4
# Show the transparent rule-based quality score on every 4h NSE zone.
SHOW_4H_ZONE_SCORES = True

DISCORD_WEBHOOK_URL = ""
DISCORD_NSE_WEBHOOK_URL = ""
DISCORD_STATUS_WEBHOOK_URL = ""
