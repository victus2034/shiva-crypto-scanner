# discord alert — Victus Indicator Strategy

Python crypto alert bot. Watches a fixed watchlist on the `4h` timeframe, rebuilds the
active supply and demand zones from the TradingView Pine logic, and alerts when price
gets close to one of those levels. A separate, isolated 30-minute workflow uses the same
logic and watchlist but keeps its own cooldown state and its own Discord webhook.

The most active project here — 4,781 commits, and the only one with an offsite copy.

## Running it

There is a venv here (`.venv`, 48 packages, created 2026-09-01):

```powershell
.venv\Scripts\python.exe scanner.py            # continuous
.venv\Scripts\python.exe scanner.py --once     # single scan
```

Verified working 2026-09-01: a `--once` run scanned **64/64 symbols, 0 failures**
against live Binance data in ~2 minutes.

`pandas` resolved to **3.0.5**, a major version above the `>=2.0` in `requirements.txt`.
Nothing broke, but suspect it first for any dataframe-shaped bug.

## Configuration

All in `config.py`, which **is tracked in git**:

- `WATCHLIST` — the symbols scanned (the README still says "10 coins"; it is 64 as of
  2026-09-01, cut from 119 on seven-day Delta volume)
- `DELTA_LISTED_SYMBOLS` — the 31 symbols Delta India lists. Everything else scanned
  is reached through CoinSwitch, and `entry_confirm.py` tags each alert with the venue.
  Static on purpose; re-audit against Delta's `/v2/products` when the watchlist changes
- `EXCHANGE_IDS` — exchange fallback order
- `MAX_DISTANCE_PCT` — how close price must get before alerting
- `DISCORD_WEBHOOK_URL`, `DISCORD_STATUS_WEBHOOK_URL`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — only if Telegram becomes available again

All four credential fields are currently empty strings, and that is deliberate. Fill them
locally and **never commit real values** — this repo is on GitHub. Verified clean as of
2026-09-01: the only webhook URLs anywhere in the tree are `webhooks/123/token` test
placeholders in `tests/test_daily_backtest_summary.py`.

## Git

- remote: `github.com/victus2034/victus-indicator-strategy`
- branch: `main`; also `backup-before-revert`, `agent/astrology-corrections-v2`,
  `agent/daily-astrology`
- last commit Aug 31 12:36, clean tree

## Gotchas

- Alert state is gitignored and machine-local: `alert_state*.json`,
  `nse_alert_state*.json`, `crypto_alert_records*.jsonl`. Deleting these resets cooldowns
  and can cause a burst of duplicate alerts on the next run.
- The 30-minute workflow is deliberately isolated. Changing shared zone logic affects both
  it and the 4h flow — check both before assuming a fix is local.
- There is an astrology component (`astrology_engine.js`, `ASTROLOGY_SETUP.md`) with its
  own agent branches.
