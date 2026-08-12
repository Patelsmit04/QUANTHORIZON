# TRADEXO — BTST/STBT Scanner

A quantitative scanner for NSE F&O stocks that ranks BTST (Buy Today Sell Tomorrow) and
STBT (Sell Today Buy Tomorrow) overnight setups, combining a technical 6-pillar matrix with
fundamental and news quality gates, and grading its own predictions every trading day.

> **Not investment advice.** This tool produces probability-ranked, backtested-style signals
> from technical/fundamental/news data — it does not and cannot guarantee any outcome.
> Confidence and priority scores reflect relative conviction, not certainty. Nothing here
> should be treated as personalized financial advice.

## What it does

- **6-Pillar technical matrix**: futures OI proxy, same-day volume persistence + T+1 delivery
  validation, relative strength vs Nifty 50, volume spike, Marubozu-style close position, and
  institutional flow (NSE bulk/block deals — tiered by same-day net value, direction-gated,
  buy-side weighted higher than sell-side; see `block_deal_provider.py`). Institutional Flow
  ships in **shadow mode** by default (computed and visible, excluded from the live verdict)
  until its live-snapshot-vs-official-archive reconciliation has run clean for a couple of
  weeks — see `INSTITUTIONAL_FLOW_SHADOW_MODE` in `.env.example`. Liquidity-tiered thresholds
  (TIER_1 blue-chips need less confirmation than TIER_2).
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
- **Index signals** (Nifty 50 / Bank Nifty / Sensex): a dedicated model, not the stock
  5-pillar matrix — indices report zero volume via yfinance, so volume-based pillars and VWAP
  don't apply. Built around Marubozu close position, relative strength vs Nifty (Bank
  Nifty/Sensex only), **global cues** (US markets overnight, Asian markets same-day, crude
  oil, USD/INR), macro news sentiment, and (Nifty 50/Bank Nifty only — see below) live
  **derivatives positioning** and **options Greeks outlook** — 6 pillars total.
- **Index BTST Intelligence**: a dedicated post-close run (default 3:45 PM IST, separate from
  the 3:30 PM stock lock) that fetches the live NSE option chain for Nifty 50 and Bank Nifty
  (Sensex options trade on the BSE — no verified NSE source, so this stays honestly
  unavailable for Sensex rather than faked), computes PCR, max pain, OI-buildup direction,
  OI-cluster support/resistance, and real Black-Scholes Greeks (Delta/Gamma/Theta/Vega) off
  live spot/strike/IV, and turns all of it into a structured per-index verdict: Verdict (Buy
  Call / Buy Put / Avoid), Expected Open, Confidence, Primary Reason, Greek Outlook, Key
  Overnight Catalysts, Invalidation Level, and Highest Probability BTST Trade. If the index's
  live price can't be verified, the verdict is forced to `Avoid` with
  `Primary Reason: "Unable to verify live closing price."` — never a fabricated read. Every
  night's verdict is logged (`index_verdict_journal` in the signal journal) and graded the
  next morning against the real 9:15 AM open, including whether the price landed inside the
  options-market-implied expected range.
- **Strategies**: the 5-pillar matrix + index model are configurable, not fixed. Create named
  strategies that target stocks and/or any index, toggle individual pillars on/off, override
  the confirmation-weight threshold, and turn the fundamentals/news gates on or off per
  strategy — each one tracks its own win rate and accuracy independently. Full CRUD via
  `/api/strategies` or the Strategies tab in the dashboard.
- **Paper trading**: strategies can be flagged `auto_paper_trade` to simulate acting on their
  live signals. This is **simulated only** — see the Paper Trading section below.

## Tech stack

- **Backend**: Python, FastAPI, yfinance (price data), jugaad-data (NSE delivery %),
  SQLite (signal journal), CurrentsAPI (news), optionally Postgres (see "Shared Postgres
  backend" below) if the scanner and dashboard run on separate hosts
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

> **Deployment note (2026 audit finding):** this scheduler is implemented as plain OS
> `daemon` threads started on process startup, not as externally-triggered jobs. That
> requires a **persistent host** — `python app.py` kept running on a VM / always-on
> dyno / bare-metal box through market hours. `vercel.json` in this repo deploys the app
> as a serverless function; serverless instances have no process that persists between
> requests, so the 3:14–3:40 PM closing sequence, the 5-min/1-min scan loop, and every
> "survives restarts" guarantee described above **do not run** under that deployment as
> currently configured. `GET /api/scan` and `GET /api/indices` know this and never attempt
> a live scan inline there (it would just time out) — see "Shared Postgres backend" below
> for actually serving real data from a serverless deployment instead of an empty response.

## Shared Postgres backend (optional — running the scanner and the dashboard on separate hosts)

If you want the actual autonomous scanner running on one machine (your own always-on host,
`python app.py`) and a separate stateless deployment (e.g. Vercel) serving the dashboard/API off
the SAME live data, set `DATABASE_URL` (a Postgres connection string — Neon and Vercel Postgres
both work, use their **pooled** connection string) in **both** places:

1. Create a Postgres database (e.g. a free [Neon](https://neon.tech) project, or Vercel's own
   Postgres add-on).
2. Set `DATABASE_URL` in your local `.env` (the persistent host) and in the Vercel project's
   Environment Variables — same value in both.
3. If you have existing local history you don't want to lose, run the one-time migration
   **before** your first Postgres-backed run: `python scripts/migrate_to_postgres.py` (reads
   `DATABASE_URL` from the environment; safe to re-run, it only upserts).
4. Restart the local host and redeploy Vercel. Both now read/write the same `strategies.json`,
   `trade_history.json`, `paper_trades.json`, `active_pillar_weights.json`,
   `pillar_weights_history.json`, `last_market_scan.json`, `index_btst_verdicts.json`,
   `clarification_budget.json`, `stock_news_cache.json` (all via one generic `app_state` table),
   plus the full SQLite signal journal (`signal_journal`, `signal_evaluations`,
   `index_verdict_journal`, `index_verdict_evaluations`, `notifications`) as real Postgres
   tables.

Leave `DATABASE_URL` unset (the default) to keep everything on local files/SQLite exactly as
before — nothing above is required for a normal single-host run, and every module falls back to
its pre-existing local behavior automatically. Provider-internal caches that the scanner alone
ever reads (fundamentals, OI/delivery history, the daily refresh-job lock files) intentionally
stay local-only either way — a serverless reader never touches them.

On first run, `data/` is created automatically to hold:
- `trade_history.json`, `signal_journal.db` — locked picks and graded outcomes (journal now
  tracks a `strategy_id` per signal, so each strategy's performance is queryable separately;
  the same DB also holds `index_verdict_journal`/`index_verdict_evaluations` for Index BTST
  Intelligence)
- `fundamentals_cache.json`, `stock_news_cache.json` — daily/budget-capped provider caches
- `active_pillar_weights.json`, `pillar_weights_history.json` — the auto-improve state + audit trail
- `strategies.json` — every strategy's configuration (the built-in Default 5-Pillar strategy
  is seeded automatically on first run)
- `paper_trades.json` — simulated order log (see Paper Trading below)
- `last_market_scan.json` — the persisted snapshot served off-market
- `index_btst_verdicts.json` — the latest post-close Index BTST Intelligence verdict (Nifty
  50 / Bank Nifty / Sensex), regenerated once daily
- `institutional_flow_daily.json` — today's captured bulk/block deal checkpoints (live_trigger
  / final_check / eod_archive), per-symbol aggregated net value; `institutional_flow_
  reconciliation.json` — live-vs-official-archive diff history (see `block_deal_provider.py`)

This directory is gitignored — it's runtime state, not source.

## Strategies

A **Strategy** is a named configuration layered on top of the existing scoring engines — it
does not reimplement scoring, it controls what that scoring uses:

- **target_scope**: which universe(s) it scans — `STOCKS`, `NIFTY50`, `BANKNIFTY`, `SENSEX`,
  any combination
- **active_pillars**: which of the 6 stock pillars / 6 index pillars count toward its score —
  a disabled pillar contributes zero weight, it isn't removed from the engine
- **required_weight_override**: a custom confirmation bar, or `None` to use the engine's own
  tier-based (stocks) / fixed (indices) default
- **fundamentals_gate_enabled** / **news_gate_enabled**: toggle those quality gates per strategy
- **auto_paper_trade**: simulate acting on this strategy's live signals (see below)

The built-in **Default 5-Pillar** strategy reproduces the original, pre-strategy-system
behavior exactly (every pillar active, tier-based thresholds, both gates on) — it can be
edited but not deleted, so nothing changes for you unless you create or modify a strategy.
Every strategy tracks its own win rate, directional accuracy, and paper-trade count
independently (`GET /api/strategies/{id}/performance`).

## Paper trading

`auto_paper_trade` and the `/api/strategies/{id}/execute` endpoint simulate acting on a
strategy's signals — logging a fake order to `data/paper_trades.json` — but this is
**deliberately paper-only**, not a partial implementation:

- Real retail algo trading in India requires SEBI's framework (effective Feb 2025):
  exchange-empanelled Algo IDs and broker-level registration. An app can't legally fire live
  retail algo orders through a generic broker API key without that in place.
- `execution_provider.py`'s `EXECUTION_MODE` is hardcoded to `"PAPER"`. There is no code path
  that calls a real broker network endpoint. Going live means writing a new `BrokerAdapter`
  subclass with real credentials once registration is actually in place — nothing here does
  that automatically.

## Project structure

```
app.py                        FastAPI app, scheduler threads, API routes
scoring_engine.py             The stock 5-pillar matrix
index_scoring.py              The index model (Nifty 50 / Bank Nifty / Sensex), 6 pillars
options_chain_provider.py     Live NSE index option chain (Nifty 50 / Bank Nifty only)
index_derivatives_analyzer.py PCR, max pain, OI buildup, OI-cluster support/resistance, expected move
options_greeks_analyzer.py    Real Black-Scholes Greeks (Delta/Gamma/Theta/Vega) from live IV
index_depth_analysis.py       Structured Index BTST verdict generator (post-close narrative)
strategy_manager.py           Strategy CRUD + pillar multiplier composition
execution_provider.py         Paper/simulated order execution (no real broker)
fo_universe.py                Canonical NSE F&O stock whitelist
nse_data_provider.py          OI proxy + delivery % history (jugaad-data)
fundamental_provider.py       Fundamental quality gate (yfinance)
news_provider.py              News quality gate + universe-wide cache (CurrentsAPI)
depth_analysis.py             Per-stock written narrative generator
walk_forward_validator.py     Out-of-sample validation + auto-improving pillar weights
signal_journal.py             SQLite journal of signals + graded outcomes, per strategy + index
vix_provider.py               India VIX regime classifier
json_utils.py                 Atomic JSON read/write (concurrency-safe)
pg_utils.py                   Optional shared Postgres backend (see "Shared Postgres backend")
scripts/migrate_to_postgres.py  One-time local-data -> Postgres migration
scanner.py                    Standalone CLI scan script (no server)
static/                       Dashboard (HTML/CSS/JS)
tests/                        pytest suite — `pytest tests/`
```

## Key API endpoints

| Endpoint | Description |
|---|---|
| `GET /api/scan` | Current/cached scan results for the full universe |
| `GET /api/stock/{symbol}` | Live detail + recent candles for one stock |
| `GET /api/indices` | Current Nifty 50 / Bank Nifty / Sensex signals |
| `GET /api/indices/verdict` | Latest post-close Index BTST Intelligence verdict (structured Buy Call/Buy Put/Avoid per index) |
| `POST /api/indices/verdict/run` | Manually trigger the Index BTST Intelligence run (normally runs once, ~3:45 PM IST) |
| `GET /api/indices/verdict/performance` | Directional accuracy + expected-range hit rate for past index verdicts |
| `GET /api/news` | Cached news for every F&O stock (never calls the news API live) |
| `GET /api/news/{symbol}` | Cached news for one stock |
| `GET /api/strategies` | List all strategies |
| `POST /api/strategies` | Create a strategy |
| `PUT /api/strategies/{id}` | Update a strategy |
| `DELETE /api/strategies/{id}` | Delete a strategy (built-in one is protected) |
| `GET /api/strategies/{id}/performance` | This strategy's win rate/accuracy/paper stats |
| `GET /api/strategies/{id}/signals` | This strategy's current live signals |
| `POST /api/strategies/{id}/execute` | Manually paper-execute this strategy's current signals |
| `GET /api/paper_trades` | Simulated order log, optionally filtered by strategy |
| `GET /api/performance` | Win rate, accuracy, and locked-pick history (default strategy) |
| `GET /api/validation` | Walk-forward validation, pillar hit rates, active weights + history |
| `POST /api/lock_picks` | Manually lock the current picks |
| `POST /api/evaluate_picks` | Manually run the next-day gap evaluation |

Every `POST`/`PUT`/`DELETE` endpoint above requires the `X-API-Key` header (see
`TRADEXO_API_KEY` below) if that env var is set. All `GET` endpoints stay fully open,
unauthenticated, exactly as before.

## Notes

- **Authentication (2026 audit finding):** every mutating endpoint used to be callable by
  anyone with the URL. Set `TRADEXO_API_KEY` in `.env` to require an `X-API-Key: <key>`
  header on all of them — the dashboard's own UI will prompt for this key the first time you
  try to change anything (🔑 button in the header) and remembers it in your browser's
  `localStorage` afterward. Leave it unset to keep the previous fully-open behavior (a startup
  log warning calls this out explicitly so it's never silently insecure).
- If `CURRENTS_API_KEY` isn't set, the app still runs — news gates and the News section
  just show `DATA_UNAVAILABLE`/empty state instead of failing.
- The news refresh is hard-capped at 3 full passes/day to stay within CurrentsAPI's free-tier
  daily limit (see `news_provider.py` for the exact budget math).
- Running multiple strategies doesn't multiply network calls — stock and index data are each
  fetched once per scan tick and reused across every active strategy that targets them.
- The live NSE option chain (and therefore derivatives positioning, Greeks, and the Index
  BTST Intelligence run) is only fetched once/day, during the dedicated post-close window —
  never on every scan tick. Override the run time with `INDEX_INTELLIGENCE_RUN_HOUR` /
  `INDEX_INTELLIGENCE_RUN_MINUTE` env vars (24h IST, default 15:45).
