"""Daily cross-market bias report for the Discord market-bias channel."""

from __future__ import annotations

import os
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


def send_report(message: str) -> None:
    webhook = os.getenv(WEBHOOK_ENV, "").strip()
    if not webhook:
        raise RuntimeError(f"{WEBHOOK_ENV} is not configured")
    response = requests.post(webhook, json={"content": message}, timeout=15)
    response.raise_for_status()


if __name__ == "__main__":
    report = build_report(collect())
    print(report)
    send_report(report)
