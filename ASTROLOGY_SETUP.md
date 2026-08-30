# Victus Astrology Reports

This isolated workflow posts Victus's personalized Vedic astrology briefing to a
private Discord channel.

Reports:

- Daily astrology: every day at 07:00 IST
- Weekly astrology: every Sunday at 19:00 IST for the next week

The daily post includes:

- Overall
- Study & Career
- Money & Trading Discipline
- Health & Energy
- Communication & People
- Favourable Period
- Caution Period
- Do Today
- Avoid Today

The weekly post includes the same main themes across all 7 upcoming days, plus
stronger days, caution days, best period of week, main focus, and avoid.

The system intentionally excludes romance content and does not produce trade
entries, exits, stop-losses, take-profits, leverage, position sizing, or
buy/sell signals.

## One-time Discord setup

1. Create a private Discord channel such as `#victus-daily-astrology`.
2. Open Edit Channel -> Integrations -> Webhooks -> New Webhook.
3. Copy the webhook URL.
4. In GitHub, open Settings -> Secrets and variables -> Actions.
5. Create a repository secret named `DISCORD_ASTROLOGY_WEBHOOK_URL` and paste
   the webhook URL as its value.
6. Open Actions -> Victus Daily Astrology -> Run workflow to send a test post.

The same webhook secret is used by both daily and weekly astrology workflows.

## Schedule and testing

GitHub Actions schedules in UTC:

- Daily: `30 1 * * *` = 07:00 IST
- Weekly: `30 13 * * 0` = 19:00 IST every Sunday

GitHub may start scheduled jobs a few minutes late during busy periods.

Run the regression tests:

```bash
npm run test:astrology
```

Preview daily without posting to Discord:

```bash
ASTROLOGY_DRY_RUN=true npm run astrology
```

Preview a particular daily date:

```bash
ASTROLOGY_DRY_RUN=true ASTROLOGY_DATE=2026-08-08 npm run astrology
```

Preview weekly without posting to Discord:

```bash
ASTROLOGY_DRY_RUN=true ASTROLOGY_WEEK_START=2026-08-10 npm run astrology:weekly
```
