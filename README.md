# TRADEXO — Institutional BTST/STBT & Multi-Strategy Quantitative Engine

A quantitative algorithmic trading and market intelligence platform for the Indian Equity Markets (National Stock Exchange of India — NSE). TRADEXO scans all 210 NSE F&O Whitelisted stocks and major benchmark indices (NIFTY 50, BANK NIFTY, SENSEX, GIFT NIFTY), combining a 6-pillar technical matrix with institutional block deal tracking, multi-timeframe Smart Money Concepts (SMC), an intraday strategy engine, and transparent mathematical accuracy calibration.

> **Disclaimer:** Not investment advice. This software produces probability-ranked, backtested-style quantitative signals from technical, derivative, and institutional flow data — it does not guarantee future financial returns. Confidence and priority scores reflect relative quantitative conviction, not certainty.

---

## Key Subsystems & Capabilities

- **6-Pillar Stock Quantitative Matrix**: Futures Open Interest (OI) accumulation/short-covering segregation, same-day volume persistence + T+1 delivery validation, Relative Strength vs NIFTY 50, 3:15–3:25 PM volume surge ratio, Marubozu close range position, and institutional block deal tracking (Pillar 6).
- **Institutional Flow & Block Deal Engine (`block_deal_provider.py`)**: Real-time tracking of NSE Bulk & Block deals:
  - `Bulk Deals`: Normal order book trades $\ge 0.5\%$ of equity (minimum threshold ₹10 Cr).
  - `Block Deals`: Dedicated negotiation window trades meeting the SEBI minimum floor of **₹25 Cr** (`TIER_MODERATE_CR = 25.0`, `TIER_STRONG_CR = 100.0`).
  - Ships with automated EOD archive reconciliation diffing.
- **6-Pillar Index Model (`index_scoring.py`)**: Dedicated index derivatives matrix across Marubozu Close, Relative Strength vs Nifty spread, Global Cues (DOW, NASDAQ, NIKKEI, HANGSENG, Crude, USD/INR), Macro News NLP Sentiment, Derivatives Positioning (PCR, Max Pain, OI concentration), and Greeks Outlook (Black-Scholes Delta, Gamma, Theta, Vega from live IV).
- **8 Active Quantitative Strategies**:
  1. `default-5-pillar`: Built-in multi-pillar matrix with liquidity-tiered thresholds.
  2. `smc-institutional-v1`: Smart Money Concepts (BOS, CHoCH, Order Blocks, FVGs, Liquidity Sweeps).
  3. `vwap-pullback-v1`: 5m Intraday Bullish Pullback to VWAP/20 EMA with RSI reversal.
  4. `breakdown-spike-v1`: 5m Intraday Range Breakdown confirmed by 1.5x volume expansion.
  5. `orb-v1`: 30-Minute Opening Range Breakout.
  6. `oi-surge-v1`: 15-Minute Price & Futures OI Surge targeting 1-strike OTM Calls.
  7. `death-cross-v1`: 15-Minute 5/20 EMA Death Cross with short OI build-up.
  8. `volatility-straddle-v1`: Pre-Event Low-IV ATM Straddles.
- **Ultra-Fast 5-Second Real-Time Refresh**:
  - Non-blocking `<10ms` in-memory live price endpoint (`/api/live_prices`).
  - Server-side `Cache-Control: no-store, no-cache, must-revalidate` and client-side `_t=${Date.now()}` query param.
  - Authentic exchange quotes during market hours with off-market simulated dynamic micro-ticks.
- **Multi-Timeframe SMC Scanner Engine (`smc_scanner.py`)**: Continuous background scanning across 1m, 3m, 5m, 15m, 1h, 4h, and 1d candles.
- **9:15 AM Opening Gap Calibration Engine**: Grades yesterday's 3:25 PM picks against actual 9:15 AM opening ticks, calculating Prediction Variance Error, Accuracy Score %, and Jackpot/Win/Loss distribution.
- **Zerodha Kite Order Flow & Staged Orders (`zerodha_order_flow_provider.py`)**: 3:15–3:25 PM closing aggression order flow tracking and structured broker order slips.
- **Web Audio API Sound Synthesis**: Dual-frequency 587.33 Hz ($D_5$) to 880.00 Hz ($A_5$) sine wave chimes for real-time alerts.

---

## Application UI — 12 Navigation Views

1. **Scanner (`scanner`)**: Main BTST / STBT scanner dashboard, Top Marquee Index Ticker Bar, Metric Cards, 12-Column Institutional Table, and All 210 Live Stock Cards.
2. **Index Intelligence (`indices`)**: Deep benchmark analysis, Greeks, PCR, Max Pain, and post-close BTST verdicts.
3. **Live Trade (`liveTrades`)**: Simulated paper-trading execution console and open positions monitor.
4. **Strategies (`strategies`)**: Multi-strategy studio to toggle weights, scopes, and active pillars.
5. **Stocks News (`stocksNews`)**: Universe-wide stock news NLP sentiment analysis.
6. **Global & Macro News (`globalNews`)**: S&P 500, India VIX, macro catalysts, and interest rate monitor.
7. **Institutional Flow (`institutionalFlow`)**: Real-time NSE Bulk/Block deal tracker and FII/DII net flows.
8. **Order Flow (`orderFlow`)**: Zerodha Kite tick-level closing aggression and delta volume analysis.
9. **Accuracy & Win Rate (`accuracy`)**: Split accuracy performance (Stocks vs Indices) and win-rate trends.
10. **History & Calibration (`history`)**: Historical ledger of locked trades and 9:15 AM realized gap scores.
11. **Guide / Export / Settings (`guide`)**: Data export tools, manual controls, and platform documentation.
12. **Rules (`rules`)**: Institutional Quantitative Trading Handbook and operational rulebook.

---

## Tech Stack

- **Backend**: Python 3.10+, FastAPI, Uvicorn, yfinance (price data), jugaad-data (NSE delivery & archives), SQLite / PostgreSQL (signal journal), CurrentsAPI (news).
- **Frontend**: Vanilla HTML5, CSS3 (Glassmorphism design system), Vanilla JavaScript (ES6+), Lightweight Charts (TradingView), Web Audio API.

---

## Installation & Local Setup

```bash
git clone https://github.com/Patelsmit04/QUANTHORIZON.git
cd QUANTHORIZON

python -m venv venv
# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/macOS:
# source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Start the application:
```bash
python app.py
```
Access the dashboard at **http://127.0.0.1:8000**.

---

## Operational Daily Market Schedule (IST)

- **08:30 – 09:00 AM**: Pre-Market GIFT Nifty scraping and queue initialization.
- **09:15:00 AM**: Market open & automated hard browser refresh.
- **09:15 – 09:17 AM**: 9:15 AM Gap Analysis window evaluates yesterday's 3:25 PM picks.
- **09:15 AM – 03:30 PM**: 5-second live price tape, 30-second SMC scan passes, 60-second strategy engine scans.
- **02:40 PM**: Preliminary Index BTST Intelligence signals activated.
- **03:14:00 PM**: 3:14 PM pre-close snapshot freezes candidate stocks before closing auction.
- **03:25:00 PM**: Auto-lock sequence snapshots 3:25 PM picks.
- **03:30:00 PM**: Market Closing Bell lock persists picks to trade history and signal journal.
- **03:30+ PM**: Post-close Index BTST Intelligence generates final overnight index verdicts.

---

## Master API Reference

| Endpoint | Method | Description |
| :--- | :---: | :--- |
| `/api/scan` | `GET` | Full 6-pillar scan results for all 210 F&O stocks |
| `/api/live_prices` | `GET` | Non-blocking 5s live price feed (aliases: `/api/live-stocks`, `/api/stocks/live`) |
| `/api/indices` | `GET` | Real-time index ticker quotes (alias: `/api/indices/live`) |
| `/api/indices/verdict` | `GET` | Post-close structured Index BTST Intelligence verdicts |
| `/api/accuracy/split` | `GET` | Split performance metrics (Stocks vs Indices) |
| `/api/performance` | `GET` | Historical trade metrics, win rates, and prediction accuracy |
| `/api/notifications` | `GET` | Strategy alerts, unread counts, and notification journal |
| `/api/strategies` | `GET/POST` | Strategy management CRUD and activation toggles |
| `/api/chart/{symbol}` | `GET` | Interactive candlestick OHLC data |
| `/api/order_flow_all` | `GET` | Zerodha Kite order flow aggression analysis |
| `/api/lock_picks` | `POST` | Manually triggers the 3:25 PM pick lock sequence |
| `/api/evaluate_picks`| `POST` | Manually triggers 9:15 AM gap accuracy evaluation |
| `/ws/live` | `WebSocket` | Real-time push stream for alerts, locks, and sequence steps |

---
*TRADEXO Engine Version: 18.2.0 (Institutional Production Release)*
