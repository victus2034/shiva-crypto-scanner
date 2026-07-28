"""Daily cross-market bias report for the Discord market-bias channel."""

from __future__ import annotations

import os
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf


MARKETS = {
    "INDIA": ("^NSEI", "NIFTY 50"),
    "US": ("^GSPC", "S&P 500"),
    "LONDON": ("^FTSE", "FTSE 100"),
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
    "london": {
        "label": "LONDON OPEN",
        "symbols": [("^FTSE", "FTSE 100")],
    },
}
INTRADAY_SECTORS = {
    "india": [
        ("^CNXFIN", "NSE FINANCIALS"),
        ("^CNXINFRA", "NSE INDUSTRIALS"),
        ("^CNXPHARMA", "NSE HEALTHCARE"),
        ("^CNXCONSUM", "NSE CONSUMER"),
        ("^CNXMETAL", "NSE MATERIALS"),
        ("^CNXAUTO", "NSE AUTOMOBILE"),
        ("^CNXENERGY", "NSE ENERGY & UTILITIES"),
        ("^CNXIT", "NSE TECHNOLOGY & TELECOM"),
    ],
    "us": [
        ("SPY", "US BROAD / INDEX"),
        ("SMH", "US AI / SEMIS / HARDWARE"),
        ("XLK", "US INTERNET / SOFTWARE / LARGE-CAP TECH"),
        ("XLY", "US CONSUMER / AUTOMOBILE"),
        ("XLF", "US FINANCIALS / CRYPTO-RELATED"),
        ("XLE", "US ENERGY"),
        ("XLB", "US MATERIALS"),
        ("XLI", "US OTHER / INDUSTRIALS"),
    ],
    "london": [],
}
SECTOR_ALERT_THRESHOLD = 2.0
TIMEZONE = ZoneInfo("Asia/Kolkata")
WEBHOOK_ENV = "DISCORD_BIAS_WEBHOOK_URL"


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


def classify_intraday(data: pd.DataFrame) -> dict:
    close = data["close"]
    last = float(close.iloc[-1])
    previous = float(close.iloc[-2])
    session_start = float(close.iloc[-min(len(close), 14)])
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


def collect_intraday(session: str) -> dict:
    if session not in INTRADAY_MARKETS:
        raise ValueError(f"unknown session: {session}")
    results = {}
    for symbol, name in INTRADAY_MARKETS[session]["symbols"]:
        results[name] = classify_intraday(fetch_intraday(symbol))
    return results


def collect_intraday_sectors(session: str) -> dict:
    if session not in INTRADAY_SECTORS:
        raise ValueError(f"unknown session: {session}")
    results = {}
    for symbol, name in INTRADAY_SECTORS[session]:
        results[name] = classify_intraday(fetch_intraday(symbol))
    return results


def build_intraday_report(
    session: str,
    results: dict,
    sector_results: dict | None = None,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(TIMEZONE)
    label = INTRADAY_MARKETS[session]["label"]
    lines = [f"MARKET BIAS | {label} | {now:%d %b %Y, %H:%M IST}"]
    for name, item in results.items():
        lines.append(f"{name}: {item['bias']} ({item['score']:+d}/2)")
        lines.append(f"Price: {item['last']:.2f} | 30m: {item['bar_pct']:+.2f}% | Session: {item['session_pct']:+.2f}%")

    sector_results = sector_results or {
        name: results[name]
        for _, name in INTRADAY_SECTORS[session]
        if name in results
    }
    sector_alerts = []
    for name, item in sector_results.items():
        move = item["session_pct"]
        if abs(move) >= SECTOR_ALERT_THRESHOLD:
            direction = "UP" if move > 0 else "DOWN"
            sector_alerts.append(f"{name}: {abs(move):.2f}% {direction}")
    lines.append(f"Sector alerts (threshold {SECTOR_ALERT_THRESHOLD:.2f}%):")
    lines.extend(sector_alerts or ["None"])
    lines.append("Rule: 30m momentum plus current-session move; context only, not an entry signal.")
    return "\n".join(lines)


def send_report(message: str) -> None:
    webhook = os.getenv(WEBHOOK_ENV, "").strip()
    if not webhook:
        raise RuntimeError(f"{WEBHOOK_ENV} is not configured")
    response = requests.post(webhook, json={"content": message}, timeout=15)
    response.raise_for_status()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", choices=["daily", "india", "us", "london"], default="daily")
    args = parser.parse_args()
    report = (
        build_report(collect())
        if args.session == "daily"
        else build_intraday_report(
            args.session,
            collect_intraday(args.session),
            collect_intraday_sectors(args.session),
        )
    )
    print(report)
    send_report(report)
