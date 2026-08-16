"""Daily cross-market bias report for the Discord market-bias channel."""

from __future__ import annotations

import os
import argparse
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf


MARKETS = {
    "INDIA": ("^NSEI", "NIFTY 50"),
    "US": ("^GSPC", "S&P 500"),
}
INTRADAY_MARKETS = {
    "india": {
        "label": "INDIA",
        "symbols": [("^NSEI", "NIFTY 50"), ("^NSEBANK", "NIFTY BANK"), ("^CNXIT", "NIFTY IT")],
    },
    "us": {
        "label": "US SESSION",
        "symbols": [("SPY", "S&P 500"), ("QQQ", "NASDAQ 100"), ("SMH", "AI / SEMIS"), ("XLK", "US TECH")],
    },
}
INTRADAY_SECTORS = {
    "india": [
        ("^NSEBANK", "BANK"),
        ("^CNXIT", "IT"),
        ("^CNXPHARMA", "MEDICAL"),
        ("^CNXFIN", "FINANCIALS"),
        ("^CNXINFRA", "INDUSTRIALS"),
        ("^CNXCONSUM", "CONSUMER"),
        ("^CNXMETAL", "MATERIALS"),
        ("^CNXAUTO", "AUTOMOBILE"),
        ("^CNXENERGY", "ENERGY & UTILITIES"),
    ],
    "us": [
        ("QQQ", "NASDAQ"),
        ("SMH", "AI / SEMIS"),
        ("XLK", "TECH"),
        ("XLY", "CONSUMER / AUTO"),
        ("XLF", "FINANCIALS"),
        ("XLE", "ENERGY"),
        ("XLB", "MATERIALS"),
        ("XLI", "INDUSTRIALS"),
    ],
}
SECTOR_ALERT_THRESHOLD = 1.5
TIMEZONE = ZoneInfo("Asia/Kolkata")
WEBHOOK_ENV = "DISCORD_BIAS_WEBHOOK_URL"
SESSION_WINDOWS = {
    "india": ("Asia/Kolkata", time(9, 15), time(15, 30)),
    "us": ("America/New_York", time(9, 30), time(16, 0)),
}


class SessionDataNotReady(RuntimeError):
    """Raised when a live session has not produced enough completed bars yet."""


def fetch_daily(symbol: str) -> pd.DataFrame:
    data = yf.download(
        symbol,
        period="120d",
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if data.empty:
        raise RuntimeError(f"no daily data returned for {symbol}")
    close = data["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return close.dropna().to_frame("close")


def fetch_intraday(symbol: str) -> pd.DataFrame:
    data = yf.download(
        symbol,
        period="5d",
        interval="30m",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if data.empty:
        raise RuntimeError(f"no 30m data returned for {symbol}")
    close = data["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = close.dropna()
    if len(close) < 3:
        raise RuntimeError(f"not enough 30m candles for {symbol}")
    return close.to_frame("close")


def _session_close(data: pd.DataFrame, session: str, now: datetime | None = None) -> pd.Series:
    """Return only bars from the current regular market session."""
    if session not in SESSION_WINDOWS:
        raise ValueError(f"unknown session: {session}")
    if not isinstance(data.index, pd.DatetimeIndex):
        raise RuntimeError("intraday data must use a DatetimeIndex")

    timezone_name, open_time, close_time = SESSION_WINDOWS[session]
    market_tz = ZoneInfo(timezone_name)
    current = now or datetime.now(market_tz)
    current = current.astimezone(market_tz) if current.tzinfo else current.replace(tzinfo=market_tz)
    index = data.index
    if index.tz is None:
        index = index.tz_localize("UTC")
    index = index.tz_convert(market_tz)
    close = data["close"].copy()
    close.index = index
    start = datetime.combine(current.date(), open_time, tzinfo=market_tz)
    end = datetime.combine(current.date(), close_time, tzinfo=market_tz)
    session_close = close[(close.index >= start) & (close.index <= end)].dropna()
    # Two completed candles are enough for both session and 30m momentum.
    # At the opening bar there is no prior 30m candle, so wait cleanly.
    minimum_bars = 2
    if len(session_close) < minimum_bars:
        raise SessionDataNotReady(f"no current {session} session data available")
    return session_close


def session_is_active(session: str, now: datetime | None = None) -> bool:
    """Keep external cron triggers quiet outside each session's report windows."""
    timezone_name, open_time, close_time = SESSION_WINDOWS[session]
    market_tz = ZoneInfo(timezone_name)
    current = now or datetime.now(market_tz)
    current = current.astimezone(market_tz) if current.tzinfo else current.replace(tzinfo=market_tz)
    return open_time <= current.time() < close_time and current.weekday() < 5


def classify_intraday(
    data: pd.DataFrame,
    session: str | None = None,
    now: datetime | None = None,
) -> dict:
    close = _session_close(data, session, now) if session else data["close"].dropna()
    # _session_close already enforces its own documented minimum of 2 bars
    # (session start + one completed candle). Requiring 3 here contradicted
    # that and raised an uncaught RuntimeError - instead of the handled
    # SessionDataNotReady - right at the first valid reporting window.
    if len(close) < 2:
        raise RuntimeError("not enough intraday candles")
    last = float(close.iloc[-1])
    previous = float(close.iloc[-2])
    session_start = float(close.iloc[0])
    bar_pct = (last / previous - 1) * 100
    session_pct = (last / session_start - 1) * 100
    score = sum((bar_pct > 0.15, session_pct > 0.35))
    score -= sum((bar_pct < -0.15, session_pct < -0.35))
    bias = "Bullish" if score == 2 else "Bearish" if score == -2 else "Neutral"
    return {
        "last": last,
        "bar_pct": bar_pct,
        "session_pct": session_pct,
        "score": score,
        "bias": bias,
    }


def classify_bias(data: pd.DataFrame) -> dict:
    close = data["close"]
    if len(close) < 51:
        raise RuntimeError("not enough daily candles for EMA50")
    ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
    last = float(close.iloc[-1])
    one_day_pct = (last / float(close.iloc[-2]) - 1) * 100
    five_day_pct = (last / float(close.iloc[-6]) - 1) * 100
    score = sum((last > ema20, ema20 > ema50, five_day_pct > 0))
    score -= sum((last < ema20, ema20 < ema50, five_day_pct < 0))
    bias = "Bullish" if score >= 2 else "Bearish" if score <= -2 else "Neutral"
    return {
        "last": last,
        "ema20": float(ema20),
        "ema50": float(ema50),
        "one_day_pct": one_day_pct,
        "five_day_pct": five_day_pct,
        "score": score,
        "bias": bias,
    }


def build_report(results: dict, now: datetime | None = None) -> str:
    now = now or datetime.now(TIMEZONE)
    lines = [f"MARKET BIAS | {now:%d %b %Y, %H:%M IST}"]
    scores = []
    for market, values in results.items():
        item = values["metrics"]
        scores.append(item["score"])
        lines.extend(
            [
                f"{market} ({values['name']}): {item['bias']} ({item['score']:+d}/3)",
                f"Price: {item['last']:.2f} | 1D: {item['one_day_pct']:+.2f}% | 5D: {item['five_day_pct']:+.2f}%",
            ]
        )
    combined = sum(scores)
    overall = "Bullish" if combined >= 4 else "Bearish" if combined <= -4 else "Mixed / Neutral"
    lines.append(f"Overall: {overall}")
    lines.append("Rule: price vs EMA20, EMA20 vs EMA50, and 5D return.")
    return "\n".join(lines)


def collect() -> dict:
    results = {}
    for market, (symbol, name) in MARKETS.items():
        results[market] = {"name": name, "metrics": classify_bias(fetch_daily(symbol))}
    return results


def collect_intraday(session: str, now: datetime | None = None) -> dict:
    if session not in INTRADAY_MARKETS:
        raise ValueError(f"unknown session: {session}")
    results = {}
    for symbol, name in INTRADAY_MARKETS[session]["symbols"]:
        results[name] = classify_intraday(fetch_intraday(symbol), session=session, now=now)
    return results


def collect_intraday_sectors(session: str, now: datetime | None = None) -> dict:
    if session not in INTRADAY_SECTORS:
        raise ValueError(f"unknown session: {session}")
    results = {}
    for symbol, name in INTRADAY_SECTORS[session]:
        results[name] = classify_intraday(fetch_intraday(symbol), session=session, now=now)
    return results


def build_intraday_report(
    session: str,
    results: dict,
    sector_results: dict | None = None,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(TIMEZONE)
    label = INTRADAY_MARKETS[session]["label"]
    primary_name, primary_item = next(iter(results.items())) if results else (label, None)
    header_label = label.replace(" SESSION", "")
    lines = [f"{header_label} | {now:%d %b %Y, %H:%M IST}"]
    if primary_item:
        lines.append(f"{primary_name}: {primary_item['bias']}")
        lines.append(
            f"30m: {primary_item['bar_pct']:+.2f}% | "
            f"Session: {primary_item['session_pct']:+.2f}%"
        )

    sector_results = sector_results or {
        name: results[name]
        for _, name in INTRADAY_SECTORS[session]
        if name in results
    }
    sector_alerts = []
    for name, item in sector_results.items():
        move = item["session_pct"]
        if abs(move) >= SECTOR_ALERT_THRESHOLD:
            sector_alerts.append(
                f"{name} | 30m: {item['bar_pct']:+.2f}% | "
                f"Session: {item['session_pct']:+.2f}%"
            )
    lines.append(f"Sector alerts (threshold {SECTOR_ALERT_THRESHOLD:.2f}%):")
    lines.extend(sector_alerts or ["None"])
    return "\n".join(lines)


def send_report(message: str, *, allow_status_fallback: bool = False) -> None:
    webhook = os.getenv(WEBHOOK_ENV, "").strip()
    if not webhook and allow_status_fallback:
        webhook = os.getenv("DISCORD_STATUS_WEBHOOK_URL", "").strip()
    if not webhook:
        if allow_status_fallback:
            raise RuntimeError(
                f"{WEBHOOK_ENV} and DISCORD_STATUS_WEBHOOK_URL are not configured"
            )
        raise RuntimeError(f"{WEBHOOK_ENV} is not configured")
    for attempt in range(3):
        response = requests.post(webhook, json={"content": message}, timeout=15)
        if response.status_code == 429 and attempt < 2:
            retry_after = response.headers.get("Retry-After")
            try:
                delay = min(float(retry_after), 30.0)
            except (TypeError, ValueError):
                delay = 2.0 * (attempt + 1)
            import time as _time
            _time.sleep(max(delay, 0.1))
            continue
        response.raise_for_status()
        return


def build_force_test_report(session: str, now: datetime | None = None) -> str:
    """Build a clearly labeled Discord delivery test without using market data."""
    if session == "india":
        results = {
            "NIFTY 50": {
                "bias": "Bearish",
                "score": -2,
                "last": 24850.0,
                "bar_pct": -0.42,
                "session_pct": -1.18,
            }
        }
        sectors = {
            "BANK": {"bar_pct": -2.00, "session_pct": -2.35},
            "MEDICAL": {"bar_pct": 1.52, "session_pct": 2.10},
            "IT": {"bar_pct": -1.80, "session_pct": -2.62},
        }
    elif session == "us":
        results = {
            "S&P 500": {
                "bias": "Bearish",
                "score": -2,
                "last": 6280.0,
                "bar_pct": -0.55,
                "session_pct": -1.40,
            }
        }
        sectors = {
            "NASDAQ": {"bar_pct": -1.10, "session_pct": -2.18},
            "AI / SEMIS": {"bar_pct": -1.95, "session_pct": -3.05},
            "FINANCIALS": {"bar_pct": -1.05, "session_pct": -2.24},
            "ENERGY": {"bar_pct": 1.20, "session_pct": 2.40},
        }
    else:
        raise ValueError(f"force test is not supported for {session}")

    report = build_intraday_report(session, results, sectors, now=now)
    return "FORCE TEST - NOT LIVE MARKET DATA\n\n" + report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", choices=["daily", "india", "us"], default="daily")
    parser.add_argument("--force-test", choices=["india", "us"], help="send a labeled Discord delivery test")
    args = parser.parse_args()
    if args.force_test:
        report = build_force_test_report(args.force_test)
    else:
        if args.session != "daily" and not session_is_active(args.session):
            print(f"{args.session} session is closed; no report sent.")
            raise SystemExit(0)
        try:
            report = build_report(collect()) if args.session == "daily" else build_intraday_report(
                args.session,
                collect_intraday(args.session),
                collect_intraday_sectors(args.session),
            )
        except SessionDataNotReady as error:
            print(f"{error}; waiting for completed 30m candles.")
            raise SystemExit(0)
    print(report)
    # The fallback is limited to an explicit force test; live reports still
    # require the dedicated market-bias webhook.
    send_report(report, allow_status_fallback=bool(args.force_test))
