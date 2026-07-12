# Shiva Crypto Scanner

This bot watches your fixed crypto watchlist on the `4h` timeframe, rebuilds the active supply and demand zones from your TradingView Pine logic, and alerts when price gets close to one of those levels.

## Setup

1. Install dependencies:

```powershell
pip install -r requirements.txt
```

2. Edit `config.py`:
   - set your 10 coins in `WATCHLIST`
   - set exchange fallback order in `EXCHANGE_IDS`
   - change `MAX_DISTANCE_PCT` if you want a tighter or wider alert
   - fill `DISCORD_WEBHOOK_URL` if you want Discord alerts
   - fill `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` only if Telegram is available for you again later

3. Run:

```powershell
python scanner.py
```

For a single scan:

```powershell
python scanner.py --once
```

## How alerts work

- `MAX_DISTANCE_PCT = 1.0` means alert when price is within 1% of the tracked level
- supply alerts use the zone `top`
- demand alerts use the zone `bottom`
- `ALERT_COOLDOWN_SECONDS` stops repeated alerts while price stays near the same level
- `REARM_FACTOR` makes the bot wait until price moves away before it can alert that zone again

## Discord setup

1. In your Discord server, create a channel for alerts.
2. Open the channel settings and create a webhook.
3. Paste the webhook URL into `DISCORD_WEBHOOK_URL` in `config.py`.

## Free cloud option

This project now includes a GitHub Actions workflow at `.github/workflows/scan.yml`.

- It runs `python scanner.py --once`
- it is scheduled every 20 minutes at minutes `1`, `20`, and `40`
- it can also be run manually from the Actions tab
- it commits `alert_state.json` after scans so cooldowns still work in the cloud

Recommended setup:

1. Push this project to GitHub.
2. Add repository secrets named `DISCORD_WEBHOOK_URL` and `DISCORD_STATUS_WEBHOOK_URL`.
3. Keep your scanner config in the repo.
4. Let GitHub Actions run it on schedule.

If you keep the repo private, GitHub Free includes limited Actions minutes, so reduce the schedule if needed. If the repo is public, standard GitHub-hosted Actions minutes remain free.

## Files

- `scanner.py`: main watchlist scanner and alert loop
- `config.py`: watchlist and alert settings
- `alert_state.json`: created automatically to remember which levels already alerted
