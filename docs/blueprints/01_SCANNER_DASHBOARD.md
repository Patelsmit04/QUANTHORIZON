# TRADEXO PAGE BLUEPRINT: SCANNER & SIGNALS ENGINE (01)

## 1. Page Overview & Purpose
The **Scanner & Signals Engine** (`/` or `/scanner` or `/signals`) is the primary landing and execution workspace of TRADEXO. It monitors the complete **NSE F&O Universe (~230+ liquid securities)** in real-time, applying an autonomous multi-pillar quantitative model to rank Indian stocks for overnight **BTST (Buy Today, Sell Tomorrow - Bullish Breakouts)** and **STBT (Sell Today, Buy Tomorrow - Bearish Distributions)**.

---

## 2. Global Shell & Navigation Elements
- **Wordmark & Logo**: Dual-theme adaptive SVG/PNG brand header (`TRADEXO — Market To Conviction`).
- **Market Status Pill (`#topbarMarketStatusBadge`)**:
  - Live state transitions: `PRE-MARKET (9:00 - 9:15 AM)`, `REGULAR_SESSION (9:15 AM - 3:14 PM)`, `POWER_HOUR (3:14 - 3:25 PM)`, `CLOSING_LOCK (3:25 - 3:30 PM)`, `MARKET_CLOSED (3:30 PM - 9:00 AM Next Day)`.
- **Top Marquee Ticker Bar (`#marqueeTrack`)**:
  - Infinite hardware-accelerated ticker streaming real-time prices and percentage changes for `NIFTY 50`, `BANK NIFTY`, `FINNIFTY`, `SENSEX`, `GIFT NIFTY`, and Top Priority P1 candidates.
- **Top Action Bar Buttons**:
  - `SCAN NOW` (`#scanBtn` / `#runScanBtn`): Triggers full 230-stock multi-pillar pipeline with adaptive timeout (180s).
  - `WIN RATE` (`#winRateBtn`): Launches Accuracy & Historical Calibration Analytics Modal.
  - `EXPORT CSV` (`#exportCsvBtn`): Downloads filtered watchlist as formatted CSV.
  - `INTRO VIDEO` (`#sidebarWatchIntroBtn`): Launches platform intro video modal with audio controls.

---

## 3. High-Conviction Metric Cards & Telemetry Grid
Clickable high-level quantitative filter cards:
1. **Total Scanned (`#totalScanned`)**: Total F&O universe count (e.g., 230+). Filters table to `ALL`.
2. **Priority 1 High (`#priority1Count`)**: Stocks meeting strict high-conviction criteria (Score >= 80, Gap >= 1.2%, Volume Surge >= 2.0x).
3. **BTST Bullish (`#btstCount`)**: Total Overnight Long Breakout candidates (`CALL (CE)`).
4. **STBT Bearish (`#stbtCount`)**: Total Overnight Short Distribution candidates (`PUT (PE)`).

---

## 4. Multi-Filter & Search Toolbar
- **Tab Filters (`.filter-tabs`)**:
  - `ALL`: Shows all scanned candidates.
  - `P1 HIGH CONVICTION`: Shows only P1 candidates with amber crown indicator.
  - `P2 MEDIUM`: Shows secondary momentum setups.
  - `BTST (BUY)`: Filters for long calls.
  - `STBT (SELL)`: Filters for short puts.
  - `TOP 5 ONLY`: Filters for the algorithmic Next-Day Best 5.
- **Search Input (`#searchInput`)**: Instant client-side search by symbol (e.g., `RELIANCE`, `TCS`, `INFY`).
- **Sort Dropdown (`#sortSelect`)**:
  - Sort by `Rank Position (Ascending)`, `Confidence Score (Descending)`, `Predicted Gap % (Descending)`, `Volume Surge (Descending)`, `LTP (High to Low)`.

---

## 5. Main Scanner Data Table (12 Columns)
| Column | Identifier | Description | Formatting |
| :--- | :--- | :--- | :--- |
| **1. RANK** | `rank_position` | Algorithm rank (#1, #2, etc.) with gold crown for Top 2 | `#1` with `badge-rank` |
| **2. TICKER** | `symbol` | NSE ticker symbol with dynamic SVG logo and phase badge | `RELIANCE` + SVG logo |
| **3. SIGNAL** | `signal` | `BTST (BUY)` or `STBT (SELL)` | `text-bullish` / `text-bearish` |
| **4. OPTION** | `option_type` | Recommended leg: `CALL (CE)` or `PUT (PE)` | `badge-call` / `badge-put` |
| **5. PRIORITY** | `priority_level` | `P1_HIGH`, `P2_MEDIUM`, `P3_WATCHLIST` | `badge-p1-high` (Amber) |
| **6. PREDICTED GAP** | `predicted_gap_pct`| ML/Heuristic overnight gap estimate | `+1.85% EST` |
| **7. LTP (₹)** | `ltp` | Last Traded Price from SmartAPI / Fast Cache | `font-mono tabular-nums` |
| **8. VOL SURGE** | `volume_spike` | Volume relative to 20-day rolling average | `2.8x VOL` |
| **9. RSI (14)** | `rsi` | 14-period Relative Strength Index | `68.4` (Cyan/Green/Red) |
| **10. PILLARS** | `pillar_scores` | 5-Pillar breakdown mini bar | Visual progress meter |
| **11. CONVICTION** | `confidence_score`| Weighted aggregate confidence (0-100%) | Amber gradient progress bar |
| **12. ACTION** | `actions` | Expand/Collapse chevron toggle | `fa-chevron-down` |

---

## 6. Expanded Accordion: 4-Button Dedicated Action Bar
Clicking any table row smoothly expands the detailed breakdown accordion featuring:
1. **LTP & Day Change Strip**: Live market price with day's point and percentage variance.
2. **Gap Probability Distribution Meter**:
   - 5 Discrete Buckets: `< -1.0%`, `-1.0% to -0.2%`, `-0.2% to +0.2% (Flat)`, `+0.2% to +1.0%`, `> +1.0% (Jackpot)`.
   - Sample size indicator: `CONFIRMED (n=64)` or `PRELIMINARY (n=12)`.
3. **The 4-Button Action Grid**:
   - **Button 1: `ANALYSIS`** (`.btn-action-analysis`): Launches the dedicated Multi-Pillar Technical Breakdown Drawer.
   - **Button 2: `⚡ PAPER TRADE`** (`.btn-action-trade`): Launches the Advanced Options Demo Trading Modal with pre-populated parameters.
   - **Button 3: `CHART`** (`.btn-action-icon`): Opens the interactive Candlestick Chart view with VWAP, TP, and SL lines.
   - **Button 4: `OPTION CHAIN`** (`.btn-action-icon`): Opens the Live 1-Second Option Chain Matrix Modal.

---

## 7. Backend API Dependencies & Endpoints
- `GET /api/scan`: Returns full scanned F&O snapshot (`scan_summary.json` cached in memory).
- `POST /api/scan/run_now`: Triggers full background scan pass immediately.
- `GET /api/live_prices`: Lightweight high-speed endpoint serving live LTP quotes for all active stocks.
- `GET /api/stock/{symbol}`: Returns deep multi-pillar telemetry, 5-level order depth imbalance, and historical technical checklist for a single symbol.
