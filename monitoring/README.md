# External Health Monitor

An availability monitor for the deployed site's `/health` endpoint that runs **entirely
outside** the monitored service, via a scheduled GitHub Actions workflow
(`.github/workflows/health-monitor.yml`). It is separate from `market-cron.yml` and
`sentinel_heartbeat.yml`, which exist to drive market-hours business logic (scanner ticks,
self-healing) — this one's only job is "is the site reachable, how fast, and for how long has
it been down", 24/7, not just during market hours.

## How it works

1. Every ~5 minutes, the workflow checks out the repo, installs `requests`, and runs
   `health_monitor.py`.
2. The script does `GET {APP_BASE_URL}/health` with a 12s timeout, retrying up to 3 times
   before scoring the run as a failure (protects against one-off network blips).
3. Result history and running stats (uptime %, avg/min/max response time, consecutive
   failures) are kept in `state.json`, persisted on a dedicated `monitoring-data` branch so it
   never pollutes `main`'s commit history.
4. A DOWN alert fires the moment consecutive failures cross the threshold (default 3); a
   RECOVERY alert (with computed downtime duration) fires on the next successful check after
   that. Not on every single failure — that would just be noise.
5. `dashboard.html` (also copied onto `monitoring-data`) reads `state.json` client-side and
   renders current status, uptime, response-time stats, and recent history. Point GitHub Pages
   at the `monitoring-data` branch to get a live URL for it (Settings → Pages → Branch:
   `monitoring-data` → `/ (root)`).

## Required setup (things I can't do for you)

**1. Repo secret for the target URL** (Settings → Secrets and variables → Actions):
- `QUANTHORIZON_APP_URL` = `https://quanthorizon-wsma.onrender.com` (no trailing slash) — reuses the
  same secret name the existing cron workflows already use, if it's already set you don't need
  to add it again.

**2. Alert channel secrets (all optional — configure whichever you want, zero is valid too):**

| Channel | Secrets needed | How to get them |
|---|---|---|
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Message [@BotFather](https://t.me/BotFather) to create a bot and get a token; message [@userinfobot](https://t.me/userinfobot) (or your bot) to find your chat ID |
| Discord | `DISCORD_WEBHOOK_URL` | Server Settings → Integrations → Webhooks → New Webhook → Copy URL |
| Slack | `SLACK_WEBHOOK_URL` | Create an Incoming Webhook app in your workspace, copy the webhook URL |

With none configured, the monitor still runs, tracks history, and updates the dashboard — it
just logs "no alert channel configured" instead of sending a message. The workflow deliberately
does not fail its own GitHub Actions job on a DOWN result (see health-monitor.yml's comments) —
that used to double as a free email fallback, but paired with Render free-tier spin-down plus
GitHub Actions' schedule trigger running well off its nominal cadence, it meant every scheduled
run found the site cold and mailed a failure notice. Pair this with a real external uptime
service (below) for alerting; this workflow's job is history/dashboard, not the alert channel.

**3. (Optional) Enable GitHub Pages** for the live dashboard: Settings → Pages → Source:
Deploy from branch → Branch: `monitoring-data` → `/ (root)`. After the first workflow run
creates that branch, this becomes available at `https://<your-username>.github.io/<repo>/`.

## Testing it

Go to Actions → "External Health Monitor & Alerting" → Run workflow, to trigger an immediate
run instead of waiting for the schedule. Check the run's logs for the structured output
(`Attempt 1/3: OK status=200 time=182ms`, etc.), and check the `monitoring-data` branch for the
updated `state.json`.

## Important: this does not guarantee 60-second monitoring

GitHub Actions' `schedule` trigger is explicitly best-effort — GitHub's own docs note runs can
be delayed, especially for public repos or during high load, and 5 minutes is the realistic
floor (this repo's other scheduled workflows already settled on 5-10 minutes for the same
reason). It will not reliably hit a true 60-second cadence.

**If you need genuine ~1-minute checks with guaranteed delivery and zero maintenance**, the
honest recommendation is a dedicated free uptime service — this is exactly what they're built
for, and none of the code above is needed to get it:

- [UptimeRobot](https://uptimerobot.com) — free tier supports 5-minute intervals (1-minute on
  paid); built-in email/Telegram/Discord/Slack alerting and a public status page.
- [Better Stack (Better Uptime)](https://betterstack.com/uptime) — free tier includes
  1-minute checks.
- [Healthchecks.io](https://healthchecks.io) — free tier, simple and reliable, good for
  "did my cron actually run" style checks too.

Point any of these at `https://quanthorizon-wsma.onrender.com/health` and you get true
~1-minute monitoring with a hosted dashboard in about two minutes of setup, no code to
maintain. Running both (this workflow for a self-owned history/log you control, plus one of
these for tight-interval alerting) is a reasonable belt-and-suspenders setup.

## What this does NOT do

It does not, and cannot, prevent a Render Free Web Service from spinning down — a health check
request may incidentally wake a sleeping instance, but that is a side effect of hitting the
service, not a supported keep-alive mechanism, and Render's own docs describe free-tier
spin-down as expected behavior. If the site needs to guarantee it never sleeps, that requires
upgrading the Render Web Service to a paid instance type — see the earlier performance/Render
diagnosis for details. This monitor's job is to tell you reliably *when* it's down and for how
long, not to stop it from happening.

## Environment variables reference

| Variable | Default | Purpose |
|---|---|---|
| `APP_BASE_URL` | — (required, or set `MONITOR_URL` directly) | Base URL of the site; `/health` is appended |
| `MONITOR_URL` | derived from `APP_BASE_URL` | Full URL to check, if you want to bypass the `/health` suffix |
| `MONITOR_TIMEOUT_SECONDS` | `12` | Per-attempt request timeout |
| `MONITOR_RETRY_ATTEMPTS` | `3` | Attempts before a single run is scored as failed |
| `MONITOR_RETRY_DELAY_SECONDS` | `5` | Delay between retry attempts within one run |
| `MONITOR_FAILURE_THRESHOLD` | `3` | Consecutive failed *runs* before a DOWN alert fires |
| `MONITOR_HISTORY_MAX_ENTRIES` | `500` | Rolling history cap in `state.json` |
| `MONITOR_STATE_FILE` | `state.json` | Where state is read/written |
| `MONITOR_SITE_LABEL` | `QUANTHORIZON WEBSITE` | Name used in alert messages |
