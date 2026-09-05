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


# Cut to the Delta contracts worth scanning, 2026-09-01. The watchlist had
# grown to 119 scanned symbols, 30% of which traded under $50,000 a day on
# Delta - a zone drawn on a book that thin is a level nobody can be filled
# in. Ranked every Delta perpetual by seven-day traded value (a single
# session misranks badly: TAC printed 6% of its weekly average that day)
# and kept the 31 that earn the scan. The CoinSwitch symbols below are
# untouched - CoinSwitch's futures endpoints need an API key, so there is
# no volume figure to judge them on yet.
CRYPTO_WATCHLIST = [
    "BTCUSD",
    "ETHUSD",
    "SOLUSD",
    "XRPUSD",
    "HYPEUSD",
    "AKE/USDT",
    "COTI/USDT",
    "ZECUSD",
    "DOGEUSD",
    "DEXE/USDT",
    "SOON/USDT",
    "AAVEUSD",
    "BEAT/USDT",
    "EUL/USDT",
    "ZIL/USDT",
    "UNIUSD",
    "LINKUSD",
    "AVAXUSD",
    "LTCUSD",
    "BTW/USDT",
    "LA/USDT",
    "BNBUSD",
    "ZAMA/USDT",
    "TRUMP/USDT",
    "ESP/USDT",
    "BCHUSD",
    "UB/USDT",
    "ATOM/USDT",
    "AERO/USDT",
    "CAP/USDT",
    "RE/USDT",
    "US/USDT",
    "ICP/USDT",
    "BOME/USDT",
    "O/USDT",
    "MNT/USDT",
    "ERA/USDT",
    "CRV/USDT",
    "STORJ/USDT",
    "ALGO/USDT",
    "0G/USDT",
    "HOME/USDT",
    "KGEN/USDT",
    "GWEI/USDT",
    # From a CoinSwitch volume sweep, checked over a month rather than a day
    # so a spike could not pass for a book. Per 30m candle, against a
    # watchlist median near 203,000: CL about 1,090,000, KORU 978,000,
    # ACE 739,000. ETC came in with them at 80,000 and went out again in the
    # 2026-09-01 cut, at $49,900 a day on Delta.
    "CL/USDT",
    "KORU/USDT",
    "ACE/USDT",
    # Added in the 2026-09-01 cut on seven-day Delta volume: TAC $87.8M,
    # ZORA $28.0M, BLESS $21.1M, H $12.5M, VELVET $12.0M, RIVER $6.8M.
    # RIVER had been removed once for thin volume - a removal is only ever
    # as good as its last measurement.
    "TACUSD",
    "ZORAUSD",
    "BLESSUSD",
    "HUSD",
    "VELVETUSD",
    "RIVERUSD",
]

# Keep non-crypto contracts separate from the CoinSwitch crypto liquidity audit.
# XAUT replaced PAXG here: both are gold, and XAUT traded $3.0B over seven days
# against PAXG's $749M.
OTHER_WATCHLIST = [
    "SLVONUSD",
    "XAUTUSD",
]

# NVDAXUSD is back. It was dropped with QQQX, EWYB, DRAMB and CBRSB for having
# no live data, but a re-audit on 2026-09-01 - two rounds 30s apart, the same
# method that removed them - had all five answering from delta_india. The
# fetch chain reaches Delta directly now, so that finding no longer holds.
XSTOCK_WATCHLIST = [
    "TSLAXUSD",
    "METAXUSD",
    "SOXLBUSD",
    "SNDKBUSD",
    "BZ/USDT:USDT",
    "SAMSUNG/USDT:USDT",
    "AXTI/USDT:USDT",
    "MRVL/USDT:USDT",
    "SLX/USDT:USDT",
    "MSFT/USDT:USDT",
    "NVDAXUSD",
    # Still out, measured on CoinSwitch over 96 30m candles. The watchlist
    # median was about 200,000 in traded value per candle; every symbol here
    # sat under 11,000, and FLNC went a full 30 minutes with no trades at all
    # seven times in two days. A zone price drifts into on no volume is a
    # zone nobody can be filled in:
    #   FLNC, IBM, PHAROS, SOXX, NVDL, BABA, DELL, AVGO, TAIKO, TQQQ
    # Then OPENAI (2,914 per candle, 3 of 96 bars with no trades at all) and
    # AMZN (5,279), both measurable only once the xStocks were fetched under
    # the names CoinSwitch uses. VANRY went with them: not listed on
    # CoinSwitch, last candle ten days old - never a thin feed but a dead one.
    # SPY too, at 6,366: the token is thin even though the ETF behind it is
    # not, and SPY stays in the rating registry as its own sector marker.
    #
    # Dropped in the 2026-09-01 cut for thin seven-day Delta volume, keeping
    # the six xStocks above: AAPLX, CRCLX, GOOGLX, COINX, MUB, SPCXX, INTCB,
    # MSTRB, SKHYNIX, NBIS, HOOD.
]

WATCHLIST = CRYPTO_WATCHLIST + OTHER_WATCHLIST + XSTOCK_WATCHLIST

# Which venue each scanned symbol is actually traded on, so an alert can say
# where to go and place it. Delta India lists these 31; anything else on the
# watchlist is reached through CoinSwitch instead.
#
# This is a static list on purpose. Delta's listings drift, but a live lookup
# on every run would make an alert depend on a third API being up, and the
# venue of a symbol is not something that should change mid-session. Re-audit
# it against /v2/products when the watchlist is next reviewed.
DELTA_LISTED_SYMBOLS = {
    "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "HYPEUSD", "AKE/USDT",
    "ZECUSD", "DOGEUSD", "AAVEUSD", "BEAT/USDT", "UNIUSD", "LINKUSD",
    "AVAXUSD", "LTCUSD", "BNBUSD", "TRUMP/USDT", "BCHUSD", "TACUSD",
    "ZORAUSD", "BLESSUSD", "HUSD", "VELVETUSD", "RIVERUSD", "SLVONUSD",
    "XAUTUSD", "TSLAXUSD", "METAXUSD", "SOXLBUSD", "SNDKBUSD",
    "MRVL/USDT:USDT", "NVDAXUSD",
}

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
PREFER_COINSWITCH = env_flag("VICTUS_PREFER_COINSWITCH", default=True)
REQUIRE_COINSWITCH = env_flag("VICTUS_REQUIRE_COINSWITCH")
USE_LIVE_TICKER = env_flag("VICTUS_USE_LIVE_TICKER")
PRIMARY_EXCHANGE_ID = "binance"
# CoinSwitch first, then Binance. The rest exist because Binance is
# geo-blocked from GitHub Actions runners - without them a CI scan has no
# source at all once CoinSwitch misses, which is exactly what happened when
# this list was trimmed to Binance alone.
EXCHANGE_IDS = ["binance", "kucoin", "okx", "bybit", "mexc", "bitget", "lbank", "coinex"]
TIMEFRAME = os.getenv("VICTUS_TIMEFRAME", "4h").strip() or "4h"
# Crypto trades around the clock, so 500 30m candles is only ten days.
# A zone from three weeks ago was not being ignored - it was not in the
# data at all, and no amount of zone logic can find a candle that was
# never fetched. Measured over sixty days on ten majors: at 500 bars the
# oldest level price actually returned to was 6 days old and 65 zones
# were alertable; at 1500 it was 29 days and 76. Going further to 2880
# bought only three more, so this is where the curve flattens.
#
# One request either way - the venue takes a limit, so this costs no
# extra calls, which matters while CoinSwitch is rate-limiting us.
OHLCV_LIMIT = env_int("VICTUS_OHLCV_LIMIT", 1500)

SWING_LENGTH = 10
ATR_PERIOD = 50
BOX_WIDTH = 2.5
# Raised with the lookback above. The cap keeps the NEWEST zones, so at
# 20 it discarded precisely the old levels the longer window exists to
# find - every one of six majors produced 19-32 zones a side at 1500
# bars. 60 leaves headroom above that.
HISTORY_OF_ZONES_TO_KEEP = env_int("VICTUS_HISTORY_OF_ZONES_TO_KEEP", 60)
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
MIN_DISTANCE_PCT = env_float("VICTUS_MIN_DISTANCE_PCT", 0.0)
MAX_DISTANCE_PCT = env_float("VICTUS_MAX_DISTANCE_PCT", 0.20)
REARM_FACTOR = 1.25
# 0 disables the over-touch veto. The Pine indicator counts no touches and
# never retires a zone for being revisited - only a close through it kills the
# zone - so any positive value here drops levels the chart still shows.
# Back-to-back candles sitting on a zone mean price is grinding through it
# rather than reacting to it - thin volume, no rejection. Two consecutive
# touching candles retire the zone. This is deliberately stricter than the
# Pine indicator, which has no touch veto at all: the indicator draws every
# level, this decides which are worth an alert.
# ---------------------------------------------------------------------------
# Zone construction. Backtested 2026-09-06 over 42 symbols / 187 days of 30m;
# see ZONE_GEOMETRY_BACKTEST_FINDINGS.md for the table behind each default.
#
# ZONE_GEOMETRY "atr"  the fixed atr * (BOX_WIDTH/10) band. Production, and still
#                      the best arm on total net R.
#              "wick"  Shiva_Indicator_v7.pine's geometry - the pivot candle's
#                      wick, with the near edge pulled to the nearest body edge
#                      within ZONE_BASE_EXTRA bars. LIVE since 2026-09-06, on
#                      Shiva's call after reading it on chart. The ATR band still
#                      shows more total R in backtest (67.5 vs 54.3 over 187 days
#                      of 30m) but the same net expectancy per trade, on ~15%
#                      fewer trades and with less than half the same-bar
#                      stop/target collisions - so its number rests on far less
#                      that bar data cannot verify. The shadow now runs "atr", so
#                      the road not taken keeps being scored.
#
# The wick geometry is NOT a drop-in. Flipping this flag alone, leaving the close
# break rule and OVERLAP_ATR 2.0 in place, was the single worst configuration
# measured - 0.020 net expectancy against 0.058 for the ATR band. It needs
# ZONE_BREAK_ON_WICK and the tighter overlap below to reach 0.055. Change these
# together or not at all.
ZONE_GEOMETRY = os.getenv("VICTUS_ZONE_GEOMETRY", "wick").strip().lower() or "wick"
ZONE_BASE_EXTRA = env_int("VICTUS_ZONE_BASE_EXTRA", 5)
# Built alongside the live geometry and logged, never sent. Set empty to disable.
ZONE_SHADOW_GEOMETRY = os.getenv("VICTUS_ZONE_SHADOW_GEOMETRY", "atr").strip().lower()

# When the ring buffer is full, drop the weakest zone rather than the oldest.
# The original FIFO throws away exactly the old untouched zones the strategy
# calls strongest. Measured effect on P&L is nil - it evicts zones already spent
# - but it is what keeps long-dormant levels alive, which is the point.
# A wick through the far edge kills the zone, rather than a close through it.
# Essential to the wick geometry rather than cosmetic: with the close rule the
# wick construction nets 0.020 per trade, with this it nets 0.055. Zones die
# sooner and there are ~30% fewer of them, which is where the gain comes from.
# Meaningless under "atr", which is why it follows the geometry by default.
ZONE_BREAK_ON_WICK = env_flag("VICTUS_ZONE_BREAK_ON_WICK", ZONE_GEOMETRY == "wick")

ZONE_EVICT_WEAKEST = env_flag("VICTUS_ZONE_EVICT_WEAKEST", True)

# Restart the minimum-age clock on every touch, so MIN_ZONE_AGE_CANDLES means
# "untouched for this long" rather than "created this long ago". Worth +7% on net
# expectancy, and it gets there by removing trades on zones price is already
# working rather than by adding any.
ZONE_CLOCK_RESTARTS_ON_TOUCH = env_flag("VICTUS_ZONE_CLOCK_RESTARTS_ON_TOUCH", True)

# Wick zones are thinner than ATR bands, so their midpoints crowd this filter
# harder and real structure goes undrawn at the original 2.0. Measured over 187
# days: 1.0 gives 983 trades for 54.3 net R against 855 for 46.7 at 2.0, same
# expectancy per trade. Kept at 2.0 for the ATR band, which was tuned around it.
OVERLAP_ATR = env_float("VICTUS_OVERLAP_ATR", 1.0 if ZONE_GEOMETRY == "wick" else OVERLAP_ATR)

# ---------------------------------------------------------------------------
# Matching Shiva_Indicator_v7.pine exactly. The point of running the wick
# geometry live is to see its mistakes in the alerts, which only works if the
# alerts are the ones the chart would fire. Each value below tracks the
# indicator's own default when the geometry is "wick", and keeps the scanner's
# long-standing value when it is "atr".

# Pine's ta.atr is Wilder's RMA. This module used a simple rolling mean, which
# is a different number - it feeds the overlap filter, so the two disagreed
# about which zones to reject. "sma" restores the old behaviour.
ATR_METHOD = os.getenv("VICTUS_ATR_METHOD", "rma").strip().lower() or "rma"

# v7 keeps 50 per side; the scanner kept 60. v7 waits 15 untouched candles; the
# scanner waited 20. v7 has no over-touch veto at all - a zone that keeps being
# touched simply never matures, which the restarted clock already handles, so a
# second mechanism on top of it drops zones the chart still shows.
# v7 puts the stop a share of the ZONE HEIGHT beyond the far edge - measured at
# 30%, 17% and 25% of height on EX2, EX4 and EX3 - not a fixed share of price.
# On a wick zone those differ by a lot, because wick heights vary where an ATR
# band's do not. "price_pct" is the scanner's original 0.10%-of-price rule.
ZONE_SL_MODE = os.getenv(
    "VICTUS_ZONE_SL_MODE", "zone_pct" if ZONE_GEOMETRY == "wick" else "price_pct"
).strip().lower()
ZONE_SL_HEIGHT_PCT = env_float("VICTUS_ZONE_SL_HEIGHT_PCT", 25.0)

# v7 retires a broken zone and builds its replacement off a short pivot, so a
# new level appears within a few bars instead of waiting a full swing_length.
# Screenshot (44): "we retire the ZONE 1 and create a new and updated zone".
ZONE_REBUILD_AFTER_BREAK = env_flag("VICTUS_ZONE_REBUILD_AFTER_BREAK", ZONE_GEOMETRY == "wick")

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
MIN_ZONE_AGE_CANDLES = env_int("VICTUS_MIN_ZONE_AGE_CANDLES", 20)

# These three are defined above with the scanner's own values, then overridden
# here when the wick geometry is running so the alerts track what v7 draws.
# Placed after their definitions on purpose - an override written before them
# is silently clobbered, which is exactly what happened the first time.
if ZONE_GEOMETRY == "wick":
    HISTORY_OF_ZONES_TO_KEEP = env_int("VICTUS_HISTORY_OF_ZONES_TO_KEEP", 50)
    MIN_ZONE_AGE_CANDLES = env_int("VICTUS_MIN_ZONE_AGE_CANDLES", 15)
    # v7 has no over-touch veto. The restarted age clock already stops a zone
    # price keeps working from maturing, so a second mechanism on top of it
    # only drops levels the chart still shows.
    MAX_CONSECUTIVE_ZONE_TOUCHES = env_int("VICTUS_MAX_CONSECUTIVE_ZONE_TOUCHES", 0)
# Shortest gap between two scans of the same timeframe. Every workflow is
# also dispatched by an external scheduler, so adding cron meant each scan
# ran twice - once on each trigger, minutes apart. Rather than depend on
# that scheduler being found and switched off, a scan that starts too soon
# after the last one steps aside. Zero disables the guard.
MIN_SCAN_INTERVAL_SECONDS = env_int("VICTUS_MIN_SCAN_INTERVAL_SECONDS", 8 * 60)

# Symbols whose older candles may be spliced in from a deeper venue.
#
# CoinSwitch stops at 751 30m candles - 15.6 days - however it is asked,
# so a month-old 30m zone is unreachable on the book being charted. KuCoin
# serves 1500 in one request. Splicing its older candles underneath the
# CoinSwitch ones reaches thirty days, but only where the two venues price
# the same candle closely enough that the zone still lands where the chart
# shows it. Measured across the watchlist: BTC, ETH and SOL sit 0.04% apart,
# five times inside the 0.20% alert distance, while ESPORTS is 1.11% apart
# and 2.9% at worst - a zone spliced there would mark a price that never
# traded on the venue being watched.
#
# Filled by venue_divergence.py, which compares every watchlist symbol's
# 30m closes across both venues. 28 of the 90 it could compare agree
# inside 0.20% at the 95th percentile. The rest keep CoinSwitch alone -
# a shorter history is a smaller problem than a level in the wrong place.
# Pruned alongside the 2026-09-01 watchlist cut: splicing deep history for a
# symbol no longer scanned just buys candles nothing reads.
DEEP_HISTORY_SYMBOLS = {
    "AAVE", "AVAX", "BCH", "BNB", "BTC", "DOGE", "ETH", "HYPE", "LINK",
    "LTC", "SOL", "UNI", "XRP", "ZEC"
}
# Where the older candles come from. Binance is deliberately absent: it is
# geo-blocked from GitHub Actions runners, which took the whole scanner
# down once before.
DEEP_HISTORY_EXCHANGE = os.getenv("VICTUS_DEEP_HISTORY_EXCHANGE", "kucoin")

# How many candles a feed may be behind before it counts as dead.
# CoinSwitch omits any bucket with no trades and its higher-timeframe
# series trails the live market, so at 14:55 the newest 30m candle was
# 13:30 for BTC and 13:00 for XRP - while their 1m candles and tickers
# were current to the second. Two bars plus five minutes rejected that
# as stale and sent the symbol to an exchange the user does not chart,
# which is the opposite of what the check is for. Four bars still
# catches a genuinely dead feed - VANRY was ten days behind.
STALE_BARS_ALLOWED = env_int("VICTUS_STALE_BARS_ALLOWED", 4)

# Crypto trades around the clock, but the user does not. Alerts are held
# outside 08:00-01:00 IST so nothing fires while nobody is awake to take
# it - an alert at 04:00 is not an opportunity, it is a missed trade in
# the morning's scrollback. The window wraps midnight, so the end hour is
# earlier than the start hour on the clock.
CRYPTO_ALERT_START = datetime_time(8, 0)
CRYPTO_ALERT_END = datetime_time(1, 0)

SCAN_SLEEP = 300
SCAN_WORKERS = 8
ALERT_COOLDOWN_SECONDS = env_int("VICTUS_ALERT_COOLDOWN_SECONDS", 4 * 60 * 60)
ALERT_RANGE_FILTER_SIGNALS = True
SIGNAL_ALERT_COOLDOWN_SECONDS = env_int("VICTUS_SIGNAL_ALERT_COOLDOWN_SECONDS", 4 * 60 * 60)
# The previous model was trained on the old ATR-strip zones. Keep ratings off
# until a model trained on the polished wick zones passes out-of-sample checks.
ENABLE_CRYPTO_ZONE_RATINGS = env_flag(
    "VICTUS_ENABLE_CRYPTO_ZONE_RATINGS",
    default=True,
)
# Only validated crypto zone ratings above 5/10 are eligible for live alerts.
MIN_CRYPTO_ZONE_SCORE = env_int("VICTUS_MIN_CRYPTO_ZONE_SCORE", 6)
# Show the transparent rule-based quality score on every 4h crypto/xstock zone.
SHOW_4H_ZONE_SCORES = env_flag("VICTUS_SHOW_4H_ZONE_SCORES", default=True)
ENABLE_XSTOCK_HYBRID_RATINGS = env_flag(
    "VICTUS_ENABLE_XSTOCK_HYBRID_RATINGS",
    default=True,
)
XSTOCK_REGULAR_MIN_SCORE = env_int("VICTUS_XSTOCK_REGULAR_MIN_SCORE", 5)
XSTOCK_EXTENDED_MIN_SCORE = env_int("VICTUS_XSTOCK_EXTENDED_MIN_SCORE", 5)

PRINT_SCAN_SUMMARY = True
PRINT_ALERTS_TO_CONSOLE = True

TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""
DISCORD_WEBHOOK_URL = ""
DISCORD_STATUS_WEBHOOK_URL = ""
