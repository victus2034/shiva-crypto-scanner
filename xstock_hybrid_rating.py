"""Session-aware xStock ratings using the listed US underlying for context."""

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf


US_EASTERN = ZoneInfo("America/New_York")

# Only direct, price-verified xStock-to-underlying matches are eligible.
XSTOCK_UNDERLYINGS = {
    "QQQXUSD": {"ticker": "QQQ", "sector": "QQQ"},
    "TSLAXUSD": {"ticker": "TSLA", "sector": "XLY"},
    "METAXUSD": {"ticker": "META", "sector": "XLC"},
    "SPYXUSD": {"ticker": "SPY", "sector": "SPY"},
    "AMZNXUSD": {"ticker": "AMZN", "sector": "XLY"},
    "NVDAXUSD": {"ticker": "NVDA", "sector": "SOXX"},
    "AAPLXUSD": {"ticker": "AAPL", "sector": "XLK"},
    "CRCLXUSD": {"ticker": "CRCL", "sector": "ARKF"},
    "GOOGLXUSD": {"ticker": "GOOGL", "sector": "XLC"},
    "COINXUSD": {"ticker": "COIN", "sector": "ARKF"},
    "SOXLBUSD": {"ticker": "SOXL", "sector": "SOXX"},
    "SNDKBUSD": {"ticker": "SNDK", "sector": "SOXX"},
    "MUBUSD": {"ticker": "MU", "sector": "SOXX"},
    "EWYBUSD": {"ticker": "EWY", "sector": "EWY"},
    "INTCBUSD": {"ticker": "INTC", "sector": "SOXX"},
    "MSTRBUSD": {"ticker": "MSTR", "sector": "ARKF"},
    "AVGO/USDT:USDT": {"ticker": "AVGO", "sector": "SOXX"},
    "IBM/USDT:USDT": {"ticker": "IBM", "sector": "XLK"},
    "BABA/USDT:USDT": {"ticker": "BABA", "sector": "KWEB"},
    "NBIS/USDT:USDT": {"ticker": "NBIS", "sector": "QQQ"},
    "AXTI/USDT:USDT": {"ticker": "AXTI", "sector": "SOXX"},
    "HOOD/USDT:USDT": {"ticker": "HOOD", "sector": "ARKF"},
    "MRVL/USDT:USDT": {"ticker": "MRVL", "sector": "SOXX"},
    "FLNC/USDT:USDT": {"ticker": "FLNC", "sector": "ICLN"},
    "DELL/USDT:USDT": {"ticker": "DELL", "sector": "XLK"},
    "NVDL/USDT:USDT": {"ticker": "NVDL", "sector": "SOXX"},
    "SOXX/USDT:USDT": {"ticker": "SOXX", "sector": "SOXX"},
    "MSFT/USDT:USDT": {"ticker": "MSFT", "sector": "XLK"},
    "TQQQ/USDT:USDT": {"ticker": "TQQQ", "sector": "QQQ"},
}

UNMAPPED_XSTOCK_SYMBOLS = {
    "SPCXXUSD",
    "DRAMBUSD",
    "CBRSBUSD",
    "SKHYNIX/USDT:USDT",
    "OPENAI/USDT:USDT",
    "SAMSUNG/USDT:USDT",
}

# These public perpetual symbols resolve to unrelated instruments. They must
# never be scanned as the xStocks implied by their display names.
BLOCKED_XSTOCK_SYMBOLS = {
    "BZ/USDT:USDT",
    "SLX/USDT:USDT",
}


# Every tokenised-stock symbol we know of, blocked ones included. Suffix
# matching cannot tell MSTRBUSD (MSTR in BUSD) from BNBUSD (BNB in USD),
# so callers that need to split a symbol ask this registry instead.
ALL_XSTOCK_SYMBOLS = (
    set(XSTOCK_UNDERLYINGS) | UNMAPPED_XSTOCK_SYMBOLS | BLOCKED_XSTOCK_SYMBOLS
)


def is_stock_symbol(symbol):
    """True for tokenised stocks, whether or not they map to an underlying."""
    return str(symbol).upper() in ALL_XSTOCK_SYMBOLS


def is_hybrid_xstock(symbol):
    return has_underlying_mapping(symbol)


def has_underlying_mapping(symbol):
    return str(symbol).upper() in XSTOCK_UNDERLYINGS


def is_xstock(symbol):
    normalized = str(symbol).upper()
    if normalized in BLOCKED_XSTOCK_SYMBOLS:
        return False
    return normalized in XSTOCK_UNDERLYINGS or normalized in UNMAPPED_XSTOCK_SYMBOLS


def classify_us_session(now=None):
    """Return regular, extended, or closed for the US equity market clock."""
    current = _as_utc(now).astimezone(US_EASTERN)
    if current.weekday() >= 5:
        return "closed"

    local_time = current.time().replace(tzinfo=None)
    if time(9, 30) <= local_time < time(16, 0):
        return "regular"
    if time(4, 0) <= local_time < time(9, 30):
        return "extended"
    if time(16, 0) <= local_time < time(20, 0):
        return "extended"
    return "closed"


def prepare_xstock_contexts(symbols, now=None):
    """Download underlying data once and return contexts keyed by xStock."""
    requested = {
        symbol: XSTOCK_UNDERLYINGS[symbol]
        for symbol in symbols
        if symbol in XSTOCK_UNDERLYINGS
    }
    if not requested:
        return {}

    tickers = sorted(
        {
            value
            for mapping in requested.values()
            for value in (mapping["ticker"], mapping["sector"])
        }
    )
    data = yf.download(
        tickers=tickers,
        period="5d",
        interval="30m",
        group_by="ticker",
        auto_adjust=False,
        prepost=True,
        actions=False,
        threads=True,
        progress=False,
        timeout=20,
    )
    if data is None or data.empty:
        return {}

    current = _as_utc(now)
    session = classify_us_session(current)
    frames = {
        ticker: _extract_ticker_frame(data, ticker, len(tickers))
        for ticker in tickers
    }
    contexts = {}
    for symbol, mapping in requested.items():
        underlying = _frame_metrics(frames.get(mapping["ticker"]))
        sector = _frame_metrics(frames.get(mapping["sector"]))
        if underlying is None or sector is None:
            continue

        underlying_freshness_minutes = (
            current - underlying["timestamp"].to_pydatetime()
        ).total_seconds() / 60.0
        sector_freshness_minutes = (
            current - sector["timestamp"].to_pydatetime()
        ).total_seconds() / 60.0
        freshness_minutes = max(
            underlying_freshness_minutes,
            sector_freshness_minutes,
        )
        freshness_limit = 90.0 if session == "regular" else 180.0
        data_fresh = (
            session != "closed"
            and -5.0 <= freshness_minutes <= freshness_limit
        )
        contexts[symbol] = {
            "underlying": mapping["ticker"],
            "sector": mapping["sector"],
            "underlying_price": underlying["price"],
            "underlying_30m_pct": underlying["momentum_30m_pct"],
            "underlying_4h_pct": underlying["momentum_4h_pct"],
            "sector_30m_pct": sector["momentum_30m_pct"],
            "sector_4h_pct": sector["momentum_4h_pct"],
            "timestamp": underlying["timestamp"],
            "freshness_minutes": freshness_minutes,
            "data_fresh": data_fresh,
            "session": session,
        }
    return contexts


def rate_xstock_zone(
    symbol,
    zone_type,
    base_score,
    xstock_price,
    context,
    regular_min_score=5,
    extended_min_score=5,
):
    """Combine zone quality with the underlying and sector direction."""
    base = int(base_score) if base_score is not None else 4
    mapped = has_underlying_mapping(symbol)
    session = context.get("session", "unavailable") if context else "unavailable"
    minimum_score = (
        regular_min_score if session == "regular" else extended_min_score
    )
    native_score = max(1, min(base, 10))
    rating = {
        "kind": "xstock_hybrid",
        "score": native_score,
        "native_score": native_score,
        "session": session,
        "minimum_score": minimum_score,
        "alert_allowed": native_score >= minimum_score,
        "basis_pct": None,
        "context_status": "available" if context else "underlying_context_unavailable",
        "mapped": mapped,
    }
    if not mapped:
        rating["context_status"] = "underlying_unmapped"
        return rating
    if not context or not context.get("data_fresh"):
        if context:
            rating["context_status"] = "underlying_context_stale"
        return rating

    underlying_price = float(context.get("underlying_price") or 0.0)
    if underlying_price <= 0 or xstock_price <= 0:
        rating["context_status"] = "invalid_basis"
        return rating

    direction = 1.0 if zone_type == "demand" else -1.0
    score = base
    score += _direction_adjustment(
        direction,
        context.get("underlying_30m_pct"),
        0.10,
    )
    score += _direction_adjustment(
        direction,
        context.get("underlying_4h_pct"),
        0.25,
    )

    sector_30m = _aligned_value(direction, context.get("sector_30m_pct"))
    sector_4h = _aligned_value(direction, context.get("sector_4h_pct"))
    if sector_30m >= 0.10 and sector_4h >= 0.25:
        score += 1
    elif sector_30m <= -0.10 and sector_4h <= -0.25:
        score -= 1

    basis_pct = (float(xstock_price) / underlying_price - 1.0) * 100.0
    soft_basis_limit = 0.75 if session == "regular" else 1.50
    hard_basis_limit = 2.00 if session == "regular" else 3.00
    if abs(basis_pct) > soft_basis_limit:
        score -= 1

    score = max(1, min(int(score), 10))
    alert_allowed = (
        session in {"regular", "extended"}
        and abs(basis_pct) <= hard_basis_limit
        and score >= minimum_score
    )
    rating.update(
        {
            "score": score,
            "alert_allowed": alert_allowed,
            "basis_pct": basis_pct,
            "context_status": "available",
        }
    )
    return rating


def _as_utc(value):
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _extract_ticker_frame(data, ticker, ticker_count):
    if data is None or data.empty:
        return None

    if not isinstance(data.columns, pd.MultiIndex):
        return data.copy() if ticker_count == 1 else None

    for level in range(data.columns.nlevels):
        values = {
            str(value).upper()
            for value in data.columns.get_level_values(level)
        }
        if ticker.upper() not in values:
            continue
        try:
            return data.xs(ticker, axis=1, level=level, drop_level=True).copy()
        except KeyError:
            return data.xs(
                ticker.upper(),
                axis=1,
                level=level,
                drop_level=True,
            ).copy()
    return None


def _frame_metrics(frame):
    if frame is None or frame.empty:
        return None

    normalized = frame.copy()
    normalized.columns = [str(column).lower() for column in normalized.columns]
    if "close" not in normalized:
        return None

    close = pd.to_numeric(normalized["close"], errors="coerce").dropna()
    if len(close) < 9:
        return None

    timestamp = pd.Timestamp(close.index[-1])
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(timezone.utc)
    else:
        timestamp = timestamp.tz_convert(timezone.utc)
    price = float(close.iloc[-1])
    return {
        "price": price,
        "momentum_30m_pct": (price / float(close.iloc[-2]) - 1.0) * 100.0,
        "momentum_4h_pct": (price / float(close.iloc[-9]) - 1.0) * 100.0,
        "timestamp": timestamp,
    }


def _aligned_value(direction, value):
    if value is None or pd.isna(value):
        return 0.0
    return direction * float(value)


def _direction_adjustment(direction, value, threshold):
    aligned = _aligned_value(direction, value)
    if aligned >= threshold:
        return 1
    if aligned <= -threshold:
        return -1
    return 0
