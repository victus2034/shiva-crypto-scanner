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
MIN_DISTANCE_PCT = 0.0
MAX_DISTANCE_PCT = 0.20
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
MIN_ZONE_AGE_CANDLES = 20
# Shortest gap between two scans of the same timeframe. Every workflow is
# also dispatched by an external scheduler, so cron in this repo means each
# scan would otherwise run twice, minutes apart.
MIN_SCAN_INTERVAL_SECONDS = 8 * 60
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
