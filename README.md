# QUANTHORIZON — BTST/STBT Scanner

A quantitative scanner for NSE F&O stocks that ranks BTST (Buy Today Sell Tomorrow) and
STBT (Sell Today Buy Tomorrow) overnight setups, combining a technical 5-pillar matrix with
fundamental and news quality gates, and grading its own predictions every trading day.

> **Not investment advice.** This tool produces probability-ranked, backtested-style signals
> from technical/fundamental/news data — it does not and cannot guarantee any outcome.
> Confidence and priority scores reflect relative conviction, not certainty. Nothing here
> should be treated as personalized financial advice.

## What it does

- **5-Pillar technical matrix**: futures OI proxy, same-day volume persistence + T+1 delivery
  validation, relative strength vs Nifty 50, volume spike, and Marubozu-style close position.
  Liquidity-tiered thresholds (TIER_1 blue-chips need less confirmation than TIER_2).
- **Fundamental quality gate**: P/E, ROE, debt/equity, earnings growth — caps conviction on
  structurally weak businesses, never manufactures it on strong technicals alone.
- **News quality gate**: transparent, keyword-based read of recent headlines per stock (via
  [CurrentsAPI](https://currentsapi.services)) — same cap-only discipline as the fundamentals
  gate. Every flag traces back to the specific headline/keyword that raised it.
- **Auto-improving pillar weights**: once 30+ signals have been graded, each pillar's real
  hit rate is recomputed daily and nudges its scoring weight up or down, capped at ±15%/day
  so a single lucky/unlucky streak can't whipsaw live scoring.
- **Autonomous schedule**: scans every 5 min (9:15 AM–2:30 PM) and every 1 min during power
  hour (2:30–3:30 PM IST), locks the day's BTST/STBT picks at 3:30 PM with a full written
  depth-analysis per stock, and grades yesterday's picks against the real 9:15 AM open in a
  tight 9:15–9:17 AM window the next morning.
- **News section**: covers the entire F&O universe (~210 stocks), not just the day's picks.
  Refreshed by a budget-capped background job (max 3 passes/day) — page views never call the
  news API directly, so it costs the same whether one person or ten thousand check it.

## Tech stack

- **Backend**: Python, FastAPI, yfinance (price data), jugaad-data (NSE delivery %),
  SQLite (signal journal), CurrentsAPI (news)
- **Frontend**: static HTML/CSS/JS — no build step, no framework

## Prerequisites

- Python 3.11+
- A free [CurrentsAPI](https://currentsapi.services) key (only required for the news
  features — the rest of the app runs without it)

## Setup

```bash
git clone https://github.com/Patelsmit04/QUANTHORIZON.git
cd QUANTHORIZON

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

Copy the env template and add your CurrentsAPI key:

```bash
cp .env.example .env
# then edit .env and set CURRENTS_API_KEY=<your key>
```

## Running it

```bash
python app.py
```

The dashboard is served at **http://127.0.0.1:8000**. A background thread starts
automatically on launch and runs the scan/lock/evaluate schedule described above for as
long as the process is running — leave it running through market hours for it to actually
scan, lock, and grade picks on schedule.

On first run, `data/` is created automatically to hold:
- `trade_history.json`, `signal_journal.db` — locked picks and graded outcomes
- `fundamentals_cache.json`, `stock_news_cache.json` — daily/budget-capped provider caches
- `active_pillar_weights.json`, `pillar_weights_history.json` — the auto-improve state + audit trail
- `last_market_scan.json` — the persisted snapshot served off-market

This directory is gitignored — it's runtime state, not source.

## Project structure

```
app.py                     FastAPI app, scheduler threads, API routes
scoring_engine.py          The 5-pillar matrix
fo_universe.py             Canonical NSE F&O stock whitelist
nse_data_provider.py       OI proxy + delivery % history (jugaad-data)
fundamental_provider.py    Fundamental quality gate (yfinance)
news_provider.py           News quality gate + universe-wide cache (CurrentsAPI)
depth_analysis.py          Per-stock written narrative generator
walk_forward_validator.py  Out-of-sample validation + auto-improving pillar weights
signal_journal.py          SQLite journal of signals + graded outcomes
vix_provider.py            India VIX regime classifier
json_utils.py              Atomic JSON read/write (concurrency-safe)
scanner.py                 Standalone CLI scan script (no server)
static/                    Dashboard (HTML/CSS/JS)
```

## Key API endpoints

| Endpoint | Description |
|---|---|
| `GET /api/scan` | Current/cached scan results for the full universe |
| `GET /api/stock/{symbol}` | Live detail + recent candles for one stock |
| `GET /api/news` | Cached news for every F&O stock (never calls the news API live) |
| `GET /api/news/{symbol}` | Cached news for one stock |
| `GET /api/performance` | Win rate, accuracy, and locked-pick history |
| `GET /api/validation` | Walk-forward validation, pillar hit rates, active weights + history |
| `POST /api/lock_picks` | Manually lock the current picks |
| `POST /api/evaluate_picks` | Manually run the next-day gap evaluation |

## Notes

- If `CURRENTS_API_KEY` isn't set, the app still runs — news gates and the News section
  just show `DATA_UNAVAILABLE`/empty state instead of failing.
- The news refresh is hard-capped at 3 full passes/day to stay within CurrentsAPI's free-tier
  daily limit (see `news_provider.py` for the exact budget math).
