# Shiva Daily Astrology

This isolated workflow posts Shiva's personalized Vedic astrology briefing to a
private Discord channel every day at 07:00 IST.

The post includes:

- overall theme
- study and career
- money and trading discipline
- health and energy
- favourable and caution periods in IST
- one action to do and one action to avoid

It intentionally excludes relationship guidance and the astrological "why"
section. Astrology is used only as a reflection and discipline prompt, never as
a trade entry, exit, stop-loss, leverage, or position-size signal.

## One-time Discord setup

1. Create a private Discord channel such as `#shiva-daily-astrology`.
2. Open **Edit Channel → Integrations → Webhooks → New Webhook**.
3. Copy the webhook URL.
4. In GitHub, open **Settings → Secrets and variables → Actions**.
5. Create a repository secret named `DISCORD_ASTROLOGY_WEBHOOK_URL` and paste
   the webhook URL as its value.
6. Open **Actions → Shiva Daily Astrology → Run workflow** to send a test post.

The webhook remains in GitHub Secrets and is never stored in the repository.
The source birth date, time, and birthplace are also not stored in the
repository; the calculation uses privacy-preserving chart anchors.

## Schedule and testing

GitHub Actions schedules in UTC, so the workflow uses `30 1 * * *`, which is
07:00 IST. GitHub may start scheduled jobs a few minutes late during busy
periods.

Preview without posting to Discord:

```bash
ASTROLOGY_DRY_RUN=true npm run astrology
```

Preview a particular date:

```bash
ASTROLOGY_DRY_RUN=true ASTROLOGY_DATE=2026-07-30 npm run astrology
```
