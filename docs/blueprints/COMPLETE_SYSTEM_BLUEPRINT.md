# TRADEXO — COMPLETE SYSTEM ARCHITECTURAL BLUEPRINT & QUANTITATIVE FORMULARY
**Version:** 50.1.0 (Production Institutional Grade)  
**System Class:** High-Conviction Institutional Momentum Engine, Overnight Gap Predictor & Virtual Derivatives Execution Sandbox  
**Asset Universe:** National Stock Exchange of India (NSE) F&O Universe (230+ Highly Liquid Equities & Benchmark Indices)  
**Document Type:** Unified Master Architectural Blueprint, Quantitative Formulary & Subsystem Specification

---

# 1. EXECUTIVE SUMMARY & SYSTEM PHILOSOPHY

**TRADEXO** is an institutional quantitative trading, diagnostics, risk analytics, and paper trading workstation designed specifically for the Indian derivatives (F&O) equity markets. The architecture solves the latency, rate-limiting, and execution friction challenges inherent in high-conviction retail and prop desk trading:

1. **BTST / STBT Overnight Gap Exploitation**: Predicts 9:15 AM opening price dislocations (gaps) from closing order flow, institutional accumulation, delivery shifts, and derivatives positioning between 3:15 PM and 3:30 PM IST.
2. **Sub-2ms Zero-Latency Pipeline**: All high-frequency client requests (including the 1-second live option chain) are resolved from local in-memory RAM caches (`cache_layer.py`), completely decoupling frontend polling from upstream broker rate limits.
3. **100% Deterministic Virtual Sandbox (Paper Trading)**: A closed-loop simulated execution environment with realistic slippage variance, official F&O contract lot multipliers, flat regulatory exchange fees, and real-time Mark-to-Market (MTM) ledger.
4. **Autonomous AI Sentinel & Self-Healing Watchdog**: A 19-probe diagnostic suite and 10-phase waterfall health watchdog that proactively detects and repairs database mutex locks, stale processes, and WebSocket disconnections in real-time.
5. **Decoupled Resilient Client Architecture**: Front-end event loops and workspace navigation are decoupled from data-fetching threads, guaranteeing that navigation and UI operations never freeze even if backend APIs experience network delays.

---

# 2. HIGH-LEVEL SYSTEM ARCHITECTURE & DATA FLOW PIPELINE

```
+----------------------------------------------------------------------------------------------------------------------+
|                                            TRADEXO INSTITUTIONAL APP SHELL                                           |
|                           (Vanilla JS, Custom Responsive CSS, Google Fonts: Inter & JetBrains Mono)                  |
+----------------------------------------------------------------------------------------------------------------------+
           |                                                      |                                     |
 REST Fast APIs (<2ms)                                  WebSocket Stream (/ws/live)              UI State & Navigation
           v                                                      v                                     v
+----------------------------------------------------------------------------------------------------------------------+
|                                           FASTAPI HIGH-PERFORMANCE BACKEND                                           |
|                                                   (`app.py` - Port 8000)                                             |
+--------------------------+------------------------------+-------------------------------+----------------------------+
| 1. SCANNER & QUANT ENGINE| 2. LIVE 1-SEC OPTION ENGINE  | 3. PAPER TRADING LEDGER       | 4. AI SENTINEL WATCHDOG    |
| - 5-Pillar Multi-Factor  | - In-Memory Matrix Resolver  | - ₹10,00,000 Virtual Capital  | - 19 Diagnostic Probes     |
| - Overnight Gap Predictor| - Black-Scholes Synthesizer  | - Dynamic Margin Verification | - Auto-Healing Mutex & DB  |
| - 3:15-3:25 PM Veto Gate | - Official F&O Lot Sizing    | - MTM Floating & Closed P&L   | - 10-Phase Waterfall Engine|
+--------------------------+------------------------------+-------------------------------+----------------------------+
           |                                                      |                                     |
           +------------------------------+-----------------------+-------------------------------------+
                                          v
+----------------------------------------------------------------------------------------------------------------------+
|                                              PERSISTENCE & CACHING HIERARCHY                                         |
+----------------------------------------------------------------------------------------------------------------------+
| - `cache_layer.py`: Fast in-memory cache (<2ms latency, thread-safe memory dictionaries, auto-TTL purge)            |
| - `data/paper_trading.db`: SQLite ACID database storing paper account balances, positions, fees, and order tickets   |
| - `data/signal_journal.db`: SQLite database storing historical signals, evaluations, and accuracy telemetry          |
| - `data/stock_news_cache.json`: Background-cached corporate headlines preventing external API overdraft             |
| - `data/system_health_log.json`: Rolling diagnostic log, market transitions, cold starts, and audit archive          |
| - `data/active_pillar_weights.json`: Dynamic walk-forward calibrated weights                                         |
+----------------------------------------------------------------------------------------------------------------------+
```

### 2.1 In-Memory Fast Cache Hierarchy
- **Zero-Latency Serving**: Client polling every 1000ms hits in-memory dictionaries. No direct HTTP calls are made to external broker APIs on user request.
- **Cache Invalidation & TTL**: 
  - Live prices: TTL = 1 second.
  - Option Chain Matrix: TTL = 1 second.
  - 5-Pillar Scan Snapshot: TTL = 60 seconds (or on-demand force scan).
  - Corporate News: TTL = 15 minutes.

### 2.2 Market Timing & State Transitions (IST Schedule)
All backend crons and UI status pills synchronize to Indian Standard Time (UTC + 5:30):
- `09:00 – 09:15 AM`: **PRE-MARKET** — GIFT NIFTY gap discovery and morning sentiment reconciliation.
- `09:15 – 09:17 AM`: **AUTO-EVALUATION** — Automated evaluation of yesterday's locked BTST picks against 9:15 AM market opening prices.
- `09:17 AM – 03:14 PM`: **REGULAR_SESSION** — Continuous scanning across the 230+ F&O universe.
- `03:14 – 03:25 PM`: **POWER_HOUR** — High-conviction BTST window. 3:15–3:25 PM Closing Sequence Aggression Veto active.
- `03:25 – 03:30 PM`: **CLOSING_LOCK** — Top picks algorithmically locked and recorded into `signal_journal.db`.
- `03:30 PM – 09:00 AM`: **MARKET_CLOSED** — Off-market snapshot freeze; AI Sentinel executes maintenance and walk-forward calibration.

---

# 3. COMPLETE QUANTITATIVE FORMULARY & MATHEMATICAL FOUNDATIONS

---

## 3.1 Paper Trading, Virtual Execution & Cost Model

The paper trading engine (`paper_trading_service.py`) simulates realistic order execution without exposing real capital. It accurately models exchange frictions, slippage, and statutory charges.

### A. Capital & Position Sizing
- **Starting Virtual Capital ($C_0$)**: $₹10,00,000.00$ (Ten Lakhs INR).
- **Contract Quantity ($Q$)**:
  $$Q = \text{Lots} \times \text{Lot Size}$$
  *Where Lot Size is derived from official NSE F&O definitions (e.g., NIFTY = 25, BANKNIFTY = 15, FINNIFTY = 25, RELIANCE = 250, TCS = 175, INFY = 400).*
- **Risk-Allocated Position Sizing ($Q_{risk}$)**:
  When using Risk % Allocation ($R_{\%} \in \{0.5\%, 1.0\%, 2.0\%, 3.0\%\}$):
  $$\text{Risk Capital} = C_{\text{equity}} \times \frac{R_{\%}}{100}$$
  $$\text{Per-Share Risk} = |P_{\text{entry}} - P_{\text{SL}}|$$
  $$Q_{\text{calculated}} = \left\lfloor \frac{\text{Risk Capital}}{\text{Per-Share Risk} \times \text{Lot Size}} \right\rfloor \times \text{Lot Size}$$
  *(Enforces minimum $Q = \text{Lot Size}$ and checks available margin bounds).*

### B. Execution Price with Dynamic Market Slippage
Market orders execute against a non-linear slippage model simulating bid-ask spread crossing:
$$\text{slippage\_pct} \sim \mathcal{U}(0.0005, 0.0010) \quad [0.05\% \text{ to } 0.10\%]$$
- **For BUY / CALL Orders (Slippage increases purchase price)**:
  $$P_{\text{entry}} = \text{round}\left(P_{\text{raw}} \times (1 + \text{slippage\_pct}), 2\right)$$
- **For SELL / PUT Orders (Slippage decreases fill price)**:
  $$P_{\text{entry}} = \text{round}\left(P_{\text{raw}} \times (1 - \text{slippage\_pct}), 2\right)$$
- **For LIMIT Orders**:
  $$P_{\text{entry}} = P_{\text{limit}} \quad (\text{Zero slippage; fills at exact specified price}).$$

### C. Institutional Fee & Regulatory Cost Structure
TRADEXO simulates standard Indian regulatory exchange tariffs:
1. **Flat Brokerage ($B$)**: Flat $₹20.00$ per executed order.
2. **Securities Transaction Tax ($STT$)**: $0.1\%$ ($0.0010$) on executed trade turnover.
   $$\text{Turnover} = P_{\text{exec}} \times Q$$
   $$STT = \text{round}(\text{Turnover} \times 0.0010, 2)$$
3. **Total Order Entry Fee ($C_{\text{entry}}$)**:
   $$C_{\text{entry}} = B + STT_{\text{entry}} = ₹20.00 + \text{round}(P_{\text{entry}} \times Q \times 0.0010, 2)$$
4. **Total Order Exit Fee ($C_{\text{exit}}$)**:
   $$C_{\text{exit}} = B + STT_{\text{exit}} = ₹20.00 + \text{round}(P_{\text{exit}} \times Q \times 0.0010, 2)$$
5. **Round-Trip Trading Charges ($C_{\text{roundtrip}}$)**:
   $$C_{\text{roundtrip}} = C_{\text{entry}} + C_{\text{exit}}$$

### D. Margin Verification & Account Allocation Gate
Prior to recording an order in `paper_positions`, an atomic margin check is executed:
$$\text{Required Margin } (M_{\text{req}}) = (P_{\text{entry}} \times Q) + C_{\text{entry}}$$
- **Safety Gate**:
  $$\text{If } C_{\text{available}} < M_{\text{req}} \implies \mathbf{REJECT\ ORDER\ (\text{"Insufficient Virtual Funds"})}$$
- **On Fill**:
  $$C_{\text{available}}^{\text{new}} = C_{\text{available}} - M_{\text{req}}$$
  $$\text{Total Brokerage Paid}^{\text{new}} = \text{Total Brokerage Paid} + C_{\text{entry}}$$

### E. Live Mark-to-Market (MTM) Floating P&L
$$\Delta P = \begin{cases} 
P_{\text{LTP}} - P_{\text{entry}} & \text{for BUY / CALL / BTST} \\
P_{\text{entry}} - P_{\text{LTP}} & \text{for SELL / PUT / STBT}
\end{cases}$$
$$\text{Gross MTM} = \Delta P \times Q$$
$$\text{Est. Exit Charges } (C_{\text{exit}}^{\text{est}}) = ₹20.00 + \text{round}(P_{\text{LTP}} \times Q \times 0.0010, 2)$$
$$\mathbf{\text{Net Unrealized MTM P\&L}} = \text{round}\left(\text{Gross MTM} - C_{\text{exit}}^{\text{est}}, 2\right)$$
$$\text{Unrealized P\&L \%} = \text{round}\left(\frac{\Delta P}{P_{\text{entry}}} \times 100, 2\right)$$

### F. Realized P&L upon Position Closure
When a position is closed manually or via Target/SL trigger:
$$\text{Exit Slippage } (\text{slippage}_{\text{exit}}) \sim \mathcal{U}(0.0005, 0.0010)$$
$$P_{\text{exit}} = \begin{cases}
\text{round}\left(P_{\text{LTP}} \times (1 - \text{slippage}_{\text{exit}}), 2\right) & \text{for BUY (Selling out)} \\
\text{round}\left(P_{\text{LTP}} \times (1 + \text{slippage}_{\text{exit}}), 2\right) & \text{for SELL (Covering)}
\end{cases}$$
$$\Delta P_{\text{final}} = \begin{cases} 
P_{\text{exit}} - P_{\text{entry}} & \text{for BUY} \\
P_{\text{entry}} - P_{\text{exit}} & \text{for SELL}
\end{cases}$$
$$\text{Gross Realized P\&L} = \Delta P_{\text{final}} \times Q$$
$$C_{\text{exit}} = ₹20.00 + \text{round}(P_{\text{exit}} \times Q \times 0.0010, 2)$$
$$\mathbf{\text{Net Realized P\&L}} = \text{round}\left(\text{Gross Realized P\&L} - C_{\text{exit}}, 2\right)$$
$$\text{Returned Capital} = \max\left(0.0, (P_{\text{entry}} \times Q) + \text{Gross Realized P\&L} - C_{\text{exit}}\right)$$
$$C_{\text{available}}^{\text{new}} = C_{\text{available}} + \text{Returned Capital}$$

### G. Aggregate Portfolio Analytics
$$\text{Invested Margin} = \sum_{p \in \text{Open}} (P_{\text{entry}, p} \times Q_p)$$
$$\text{Total Portfolio Equity} = C_{\text{available}} + \text{Invested Margin} + \sum_{p \in \text{Open}} \text{Net MTM}_p$$
$$\text{Total Realized P\&L} = \sum_{t \in \text{Closed}} \text{Net Realized P\&L}_t$$
$$\text{Total Cumulative P\&L} = \text{Total Realized P\&L} + \sum_{p \in \text{Open}} \text{Net MTM}_p$$
$$\text{Total Return on Capital \%} = \text{round}\left(\frac{\text{Total Cumulative P\&L}}{C_0} \times 100, 2\right)$$
$$\text{Win Rate \%} = \text{round}\left(\frac{\sum [ \text{Net Realized P\&L} > 0 ]}{\text{Total Closed Trades}} \times 100, 1\right)$$

---

## 3.2 5-Pillar Confirmation Matrix & Scoring Mechanics

The core engine (`scoring_engine.py`) subjects all 230+ F&O stocks to a multi-factor confirmation filter:

```
+---------------------------------------------------------------------------------------------+
|                                  TRADEXO 5-PILLAR MODEL                                     |
+----------------------+----------------------+----------------------+------------------------+
| Pillar 1: 25% Weight | Pillar 2: 25% Weight | Pillar 3: 20% Weight | Pillar 4: 15% | P5: 15%|
| Momentum (RSI/MACD)  | Trend (VWAP/EMA)     | Volume Surge (20-Day)| Derivatives   | News   |
+----------------------+----------------------+----------------------+---------------+--------+
```

### Pillar Formulations & Normalized Scoring:
1. **Pillar 1: Momentum & Oscillators ($S_1 \in [0, 100]$, Base Weight $w_1 = 0.25$)**:
   - Evaluates 14-period RSI, MACD histogram, and Stochastic RSI.
   - For BTST: Optimum RSI corridor is $58 \le \text{RSI} \le 72$. If $\text{RSI} > 80$, overbought penalty applied.
   - For STBT: Optimum RSI is $\text{RSI} \le 38$.
2. **Pillar 2: Trend & Volatility Structure ($S_2 \in [0, 100]$, Base Weight $w_2 = 0.25$)**:
   - Price alignment relative to VWAP, 21 EMA, 50 EMA, and SuperTrend (10, 3).
   - Bullish confirmation: $\text{Price} > \text{VWAP} > \text{EMA}_{21} > \text{EMA}_{50}$.
3. **Pillar 3: Volume Surge & Liquidity ($S_3 \in [0, 100]$, Base Weight $w_3 = 0.20$)**:
   - Compares cumulative volume to 20-day rolling simple moving average volume:
     $$\text{Volume Surge Ratio } (V_R) = \frac{\text{Volume}_{\text{today}}}{\text{SMA}_{20}(\text{Volume})}$$
     $$S_3 = \min\left(100, \max\left(0, (V_R - 1.0) \times 50\right)\right)$$
4. **Pillar 4: Derivatives Positioning & OI Matrix ($S_4 \in [0, 100]$, Base Weight $w_4 = 0.15$)**:
   - Put-Call Ratio (PCR) and Open Interest (OI) buildup:
     $$\text{PCR} = \frac{\sum \text{Put OI}}{\sum \text{Call OI}}$$
   - BTST favorable when $\text{PCR} \ge 1.15$ with Call Long Buildup ($\Delta \text{OI} > 0, \Delta P > 0$).
   - STBT favorable when $\text{PCR} \le 0.80$ with Put Long Buildup.
5. **Pillar 5: Fundamentals & News Quality Gate ($S_5 \in [0, 100]$, Base Weight $w_5 = 0.15$)**:
   - Incorporates automated NLP sentiment score $\sigma \in [-1.0, +1.0]$:
     $$S_5 = 50 + (\sigma \times 50)$$
   - Invalidation gate: Severe negative regulatory disclosures automatically trigger zero score.

### Aggregate Confidence Score:
$$\text{Confidence Score} = \sum_{i=1}^{5} (w_i \times S_i)$$
- **Priority Tier Classification**:
  - `P1_HIGH`: Confidence Score $\ge 80.0$, Predicted Gap $\ge 1.20\%$, and Volume Surge $\ge 2.0\times$.
  - `P2_MEDIUM`: Confidence Score $\ge 65.0$ and Volume Surge $\ge 1.3\times$.
  - `P3_WATCHLIST`: All remaining qualifying setups.

---

## 3.3 Probability-Bucketed Overnight Gap Prediction

Rather than a single volatile point estimate, TRADEXO projects gap probabilities across 4 discrete intervals based on historical empirical distributions:
- **Bucket 1 ($0.0\% - 1.0\%$ Gap)**: High base probability for large-cap equities.
- **Bucket 2 ($1.0\% - 2.0\%$ Gap)**: Standard breakout continuation corridor.
- **Bucket 3 ($2.0\% - 3.0\%$ Gap)**: High-conviction catalyst breakouts.
- **Bucket 4 ($3.0\%+$ Jackpot)**: Extreme institutional momentum and earnings surprises.

$$\text{Predicted Gap \%} = \sum_{b=1}^{4} \left( P(\text{Bucket}_b) \times \text{Midpoint}_b \right) \times \text{MacroAdjustmentFactor}$$

---

## 3.4 Synthetic CVD & 5-Level Order Book Depth Imbalance

To detect institutional accumulation between 3:15 PM and 3:25 PM, TRADEXO calculates Cumulative Volume Delta (CVD) based on the Lee-Ready trade classification rule:
$$\Delta V_t = \begin{cases} 
+V_t & \text{if } P_t > P_{t-1} \text{ or } (P_t = P_{t-1} \text{ and tick was at Ask}) \\
-V_t & \text{if } P_t < P_{t-1} \text{ or } (P_t = P_{t-1} \text{ and tick was at Bid})
\end{cases}$$
$$\text{CVD}_T = \sum_{t=1}^{T} \Delta V_t$$

### 5-Level Market Depth Imbalance Ratio:
$$\text{Depth Imbalance} = \frac{\sum_{i=1}^{5} \text{BidQty}_i}{\sum_{i=1}^{5} \text{AskQty}_i}$$
- **Closing Aggression Veto Gate (3:15–3:25 PM)**:
  - If BTST candidate shows Depth Imbalance $< 0.85$ and 10-minute CVD is negative, conviction is **VETOED**.

---

## 3.5 Black-Scholes Options Pricing & Greeks Engine

When live exchange option feeds are closed or unverified, the statistical Black-Scholes engine synthesizes continuous option prices and Greeks:
$$d_1 = \frac{\ln(S / K) + (r + \frac{\sigma^2}{2})T}{\sigma \sqrt{T}}, \quad d_2 = d_1 - \sigma \sqrt{T}$$
- **Call Price ($C$)**: $C = S \cdot N(d_1) - K \cdot e^{-rT} \cdot N(d_2)$
- **Put Price ($P$)**: $P = K \cdot e^{-rT} \cdot N(-d_2) - S \cdot N(-d_1)$
- **Greeks**:
  - $\text{Delta}_{\text{Call}} = N(d_1), \quad \text{Delta}_{\text{Put}} = N(d_1) - 1$
  - $\text{Gamma} = \frac{N'(d_1)}{S \sigma \sqrt{T}}$
  - $\text{Theta}_{\text{Call}} = -\frac{S N'(d_1) \sigma}{2 \sqrt{T}} - r K e^{-rT} N(d_2)$
  - $\text{Vega} = S \sqrt{T} N'(d_1)$

---

## 3.6 7 Built-In Core Institutional Strategies & SMC

1. **VWAP Trend Pullback Reversal (5m)**: Intraday uptrend ($P > \text{EMA}_{21} > \text{EMA}_{50}$), pullback to VWAP $\pm 0.35\%$, bullish reversal candle, volume spike $\ge 1.5\times$. Direction: `CALL (CE)`.
2. **Tight Range Breakdown Spike (15m)**: Range $< 0.8\%$ for 6+ bars, breakdown below support, volume spike $\ge 2.0\times$, India VIX $< 14.0$. Direction: `PUT (PE)`.
3. **Opening Range Breakout (ORB 30)**: Breakout above 30-min opening range with 2 consecutive 5-min closes outside the band and volume spike $> 2.2\times$.
4. **Smart Money Open Interest (OI) Surge (15m)**: OI increases $\ge 8.0\%$ in 15 mins with positive price delta and bid depth imbalance $> 60\%$. Direction: `CALL (CE)`.
5. **Institutional Death Cross Distribution (15m)**: 9 EMA crosses below 21 EMA with downward 50 EMA, OI surge $\ge 6.0\%$ on negative delta. Direction: `PUT (PE)`.
6. **Pre-Event Volatility Straddle**: Implied Volatility Percentile $< 25\%$, major corporate announcement or RBI MPC meeting within 24 hours. Strategy: `STRADDLE (CE + PE)`.
7. **Multi-Timeframe SMC Scanner**: Identifies Fair Value Gaps (FVG), Liquidity Sweeps, Order Blocks, and Break of Structure (BOS).

---

## 3.7 9:15 AM Auto-Evaluation & Dynamic Walk-Forward Optimizer

### Automated Trade Evaluation (9:15–9:17 AM):
$$\text{Variance Error} = |\text{Predicted Gap \%} - \text{Actual Opening Gap \%}|$$
$$\text{Direction Accuracy} = \begin{cases} 
\text{True} & \text{if } \text{sign}(\text{Actual Gap}) = \text{sign}(\text{Predicted Gap}) \\
\text{False} & \text{otherwise}
\end{cases}$$
- **Trade Win Criteria**: Hypothetical trade exit at 9:15 AM yields $> +0.50\%$ net return after deducting $0.10\%$ slippage and $₹40$ round-trip charges.

### Dynamic Walk-Forward Weight Optimizer:
Re-calibrates pillar weights using a 30-day rolling out-of-sample window ($N \ge 30$ sample guardrail):
$$W_i^{\text{new}} = \text{clamp}\left( W_i^{\text{current}} \times \left(1.0 + \text{clamp}\left(\frac{\text{HitRate}_i - \text{Benchmark}}{100.0}, -0.15, +0.15\right)\right), 0.50, 1.50 \right)$$
*(Maximum daily adjustment strictly capped at $\pm 15\%$ to prevent overfitting).*

---

## 3.8 Autonomous Health Scoring & 10-Phase Waterfall Engine

$$\text{Composite Health Score} = \sum_{k=1}^{4} (0.25 \times \text{Score}_{\text{Category } k}) - \text{Penalty}_{\text{MidMarketColdStarts}}$$
- **Category 1**: Core Scheduling (9:15 AM Eval, 3:25 PM Snapshot, 3:30 PM Lock).
- **Category 2**: Data Integrity & Anti-Stub Validation.
- **Category 3**: Frontend API Latencies ($< 500\text{ms}$).
- **Category 4**: Notifications & SQLite Journal Integrity.

---

# 4. EXHAUSTIVE PAGE & SUBSYSTEM BLUEPRINTS (01 TO 10)

---

## 4.1 Global Navigation Shell, Topbar & Hardware-Accelerated Marquee

- **Header Wordmark & Brand Frame**: Dual-theme adaptive SVG brand logo with tagline `"Market To Conviction"`.
- **Top Marquee Ticker Bar (`#marqueeTrack`)**:
  - Infinite hardware-accelerated horizontal scrolling strip.
  - Displays real-time prices and percentage changes for: `NIFTY 50`, `BANK NIFTY`, `FINNIFTY`, `SENSEX`, `GIFT NIFTY`, and Top P1 candidates.
- **Market Status Pill (`#topbarMarketStatusBadge`)**:
  - Live IST status indicator: `PRE-MARKET`, `REGULAR_SESSION (LIVE)`, `POWER_HOUR`, `CLOSING_LOCK`, `MARKET_CLOSED`.
- **Top Action Bar Buttons**:
  - `FORCE SCAN NOW` (`#scanBtn`): Triggers full 230-stock scan pass with 180s adaptive timeout.
  - `WIN RATE` (`#winRateBtn`): Opens the Accuracy & Calibration Analytics Modal.
  - `EXPORT CSV` (`#exportCsvBtn`): Downloads filtered watchlist as formatted CSV.
  - `PLATFORM INTRO` (`#sidebarWatchIntroBtn`): Launches platform intro video modal.
- **Left Navigation Rail & Mobile Drawer (`#appSidebar`)**:
  - Single authoritative navigation source for both desktop sidebar and mobile full-height drawer.
  - Decoupled event binding attached at the very top of execution to prevent UI freezes.

---

## 4.2 Blueprint 01: Scanner & Signals Engine (`data-section="scanner"`)

### High-Conviction Telemetry Metric Cards:
1. **Total Scanned (`#totalScanned`)**: Total F&O stocks currently indexed ($230+$).
2. **Priority 1 High Conviction (`#priority1Count`)**: Stocks meeting strict criteria (Score $\ge 80$, Gap $\ge 1.2\%$, Vol Surge $\ge 2.0\times$).
3. **BTST Bullish (`#btstCount`)**: Count of overnight long breakout setups (`CALL / CE`).
4. **STBT Bearish (`#stbtCount`)**: Count of overnight short distribution setups (`PUT / PE`).

### Multi-Filter & Search Toolbar:
- **Pills**: `ALL`, `P1 HIGH CONVICTION`, `P2 MEDIUM`, `BTST (BUY)`, `STBT (SELL)`, `TOP 5 ONLY`.
- **Search Box (`#searchInput`)**: Instant client-side search by symbol.
- **Sort Dropdown (`#sortSelect`)**: Sorts by Rank, Confidence Score, Predicted Gap, Volume Surge, or LTP.

### 12-Column Scanner Data Table:
| # | Column | Identifier | Description | Visual Formatting |
| :--- | :--- | :--- | :--- | :--- |
| **1** | **RANK** | `rank_position` | Algorithm rank (#1, #2) | `#1` with amber crown for Top 2 |
| **2** | **TICKER** | `symbol` | Symbol name, SVG logo, and phase badge | `RELIANCE` + Stock Logo |
| **3** | **SIGNAL** | `signal` | `BTST (BUY)` or `STBT (SELL)` | `text-bullish` / `text-bearish` |
| **4** | **OPTION** | `option_type` | Contract type (`CALL (CE)` or `PUT (PE)`) | Emerald / Rose pill |
| **5** | **PRIORITY** | `priority_level` | Priority classification | `P1_HIGH` (Amber badge) |
| **6** | **PREDICTED GAP**| `predicted_gap_pct`| Expected overnight gap % | `+1.85% EST` |
| **7** | **LTP (₹)** | `ltp` | Last Traded Price (`.ltp-cell`) | `font-mono tabular-nums` |
| **8** | **VOL SURGE** | `volume_spike` | Surge relative to 20-day average | `2.8x VOL` |
| **9** | **RSI (14)** | `rsi` | 14-period RSI | Cyan / Green / Red badge |
| **10**| **PILLARS** | `pillar_scores` | 5-Pillar mini visual progress bar | Multi-segment progress bar |
| **11**| **CONVICTION** | `confidence_score`| Weighted aggregate confidence (0-100%) | Amber gradient progress meter |
| **12**| **ACTION** | `actions` | Expand/collapse chevron | `fa-chevron-down` |

### Expandable Accordion & 4-Button Dedicated Action Bar:
Clicking any table row reveals:
- **Gap Probability Meter**: Visual histogram across 4 intervals ($0-1\%, 1-2\%, 2-3\%, 3\%+$).
- **The 4-Button Action Grid**:
  1. `ANALYSIS`: Opens the Multi-Pillar Technical Breakdown Drawer.
  2. `⚡ PAPER TRADE`: Pre-populates and launches the Options Demo Trading Modal.
  3. `CHART`: Displays interactive Candlestick Chart with VWAP and SL/TP lines.
  4. `OPTION CHAIN`: Opens live 1-second option chain matrix for the selected symbol.

---

## 4.3 Blueprint 02: Index Intelligence & Macro Gate (`data-section="indices"`)

- **Multi-Index Telemetry Cards**: Live tracking of `NIFTY 50`, `BANK NIFTY`, `FINNIFTY`, `MIDCPNIFTY`, `SENSEX`, and `GIFT NIFTY`.
- **Derivatives Sentiment Gauges**:
  - Put-Call Ratio (PCR) with visual sentiment gauge.
  - Max Pain Strike where option writers experience minimum loss.
  - ATM Implied Volatility (IV).
- **GIFT NIFTY Macro Overnight Gate**:
  - Monitors Session 1 (Day) and Session 2 (International Evening).
  - If GIFT NIFTY drops $\ge 0.75\%$ during European/US hours, individual stock P1 setups are capped to P2 to protect capital against global gap-downs.
- **Sector Weight Overrides**: Real-time contribution breakdown of Financials, IT, Oil & Gas, and Autos.

---

## 4.4 Blueprint 03: Live 1-Second Option Chain & Matrix (`data-section="liveTrades"`)

- **1-Second High-Frequency Polling Loop**: In-memory zero-latency option chain resolver.
- **Header Telemetry**: Underlying Spot LTP, Official Contract Lot Size, Aggregate PCR, and Max Pain strike.
- **Expiry Selector (`#ocExpirySelect`)**: Dropdown auto-populated with weekly and monthly expirations.
- **9-Column Matrix Layout**:
  - **CALLS (CE) Left**: Open Interest (OI), Change in OI, Volume, LTP.
  - **Center Strike**: Strike price with gold highlight on At-The-Money (ATM) row.
  - **PUTS (PE) Right**: LTP, Volume, Change in OI, Open Interest (OI).
- **Click-to-Trade**: Clicking any Call LTP or Put LTP cell immediately launches the Virtual Options Execution Modal pre-filled with the exact contract parameters.

---

## 4.5 Blueprint 04: Paper Trading Portfolio & MTM Ledger (`data-section="paperTrading"`)

- **Portfolio Executive HUD**:
  - Total Portfolio Equity ($₹10,00,000$ base + Realized P&L + MTM).
  - Available Virtual Cash.
  - Invested Margin.
  - Realized Profit/Loss.
  - Floating Mark-to-Market (MTM) P&L.
  - Total Brokerage Paid.
  - Win Rate %.
- **Active Positions Table**:
  - Contract ID, Symbol, Leg, Entry Price, Live LTP, Net MTM P&L (₹ and %), Est. Exit Charges, Target 1, Target 2, Stop Loss.
  - Actions: `MODIFY TARGET / SL` and `CLOSE POSITION`.
- **Closed Trades Ledger**:
  - Immutable historical record of closed virtual trades with timestamps, charges, and realized return.

---

## 4.6 Blueprint 05: Strategies & SMC Playbook Engine (`data-section="strategies"`)

- **7 Institutional Strategy Cards**: Active/Scanning indicators, entry rules, risk-reward ratios, and live signal counters.
- **Custom Strategy AI Builder**:
  - Natural-language rule prompt.
  - Integrated AI Clarification engine (Claude 3.5) converting English descriptions into structured JSON configurations.
- **Strategy Signal Stream**: Real-time chronological alert feed across all active playbooks.

---

## 4.7 Blueprint 06: Institutional Block Deals & Order Flow Veto Layer (`data-section="institutionalFlow"`)

- **₹25+ Crore Block Deals Feed**: Filtered institutional transactions from official exchange disclosures.
- **Closing Sequence Aggression Veto (3:15–3:25 PM)**:
  - Veto Badge: `CONFIRMED` or `VETOED`.
  - 5-Level Market Depth Imbalance Ratio bar.
  - 10-minute inferred delta bars (1-minute bars tracking buyer vs seller aggression).
  - Algorithmic explanation of institutional tape behavior.

---

## 4.8 Blueprint 07: Accuracy, History & Calibration Analytics (`data-section="accuracy"`)

- **4 Split Accuracy Meters**:
  - P1 High-Conviction Accuracy %.
  - Overall Platform Win Rate %.
  - Average Predicted Gap Variance (Mean Absolute Error).
  - Jackpot Trade Frequency (+1.5%+ gap realization).
- **Historical Evaluation Ledger**:
  - Trade Date, Symbol, Signal, Conviction Score, Predicted Gap, Actual Gap, Variance Error, Outcome Badge.
- **Dynamic Walk-Forward Weight Optimizer**:
  - Active weights for the 5 technical pillars with automated daily calibration history.

---

## 4.9 Blueprint 08: System Health & AI Sentinel Center (`data-section="systemHealth"`)

- **Hero Kill-Switch Banner & Schedule Vitals**:
  - Emergency Safe Pause / Resume toggle.
  - Countdown to upcoming market milestones (09:00, 09:15, 15:25, 15:30).
  - Active worker threads (24 background threads).
- **The 19 Diagnostic Probes Grid**:
  - Probes for Scan Engine, Live Prices, Index Intel, Gift Nifty, Option Chain, Paper Trading, Strategies, Block Deals, News, Performance, Calibration, SQLite Integrity, Fast Cache, Lock Mutex, Market Feed, Timers, WebSockets, and Backups.
- **Autonomous & 1-Click Self-Healing**:
  - Purges orphaned lockfiles, repairs corrupted indexes, re-synthesizes missing caches without restarting the web server.
- **Live System Terminal & Rolling Console**:
  - Dark terminal window with live log stream, search filter, severity tabs, and auto-scroll.

---

## 4.10 Blueprint 09: Stocks News & Global Macro Radar (`data-section="stocksNews"`)

- **Zero-Cost Caching Engine**: Background worker caches news into `stock_news_cache.json`, consuming zero external API quotas on user page views.
- **Algorithmic Sentiment Scoring**:
  - NLP score from $-1.00$ to $+1.00$ feeding into Pillar 5.
  - Badges: `STRONG_BULLISH`, `MILD_BULLISH`, `NEUTRAL`, `BEARISH`.
- **Global Macroeconomic Radar**:
  - US Indexes (Dow, S&P, Nasdaq), Crude Oil Brent, US 10-Yr Yield, USD/INR.
  - Overnight Macro Risk Flag tightening position sizing during high-risk global events.

---

## 4.11 Blueprint 10: Guide, Rules & Settings (`data-section="guide"` & `data-section="rules"`)

- **5-Pillar Methodology Documentation**: Comprehensive visual explanation of scoring formulas.
- **Market Schedule Rulebook**: Detailed timetable for Pre-Market, Regular Session, Power Hour, and Closing Lock.
- **Theme & Appearance Engine**:
  - Institutional Light Theme: White cards, clean slate borders, deep slate text, champagne gold accents.
  - Dark Theme: Deep space slate background, Obsidian card surfaces, gold accents.
  - Persistent preference stored in `localStorage`.
- **Data Export**: Full system database backup and CSV watchlist export.

---

# 5. UNIVERSAL MODALS, DRAWERS & OVERLAYS SPECIFICATIONS

1. **Advanced Options Demo Trading Modal (`#optionsDemoTradeModal`)**:
   - `CALL (CE)` vs `PUT (PE)` toggle.
   - Strike dropdown auto-populated with 15 strikes centered around ATM.
   - Live option premium LTP quote.
   - Lot stepper with dynamic multiplication by official asset lot size.
   - Real-time margin validation: If `Margin Required > Available Cash`, disables execution.
2. **Institutional Order Ticket Modal (`#orderTicketModal`)**:
   - Equity and stock trading ticket supporting MARKET (with slippage) and LIMIT orders.
   - Sizing controls: Risk % allocation ($0.5\%, 1.0\%, 2.0\%, 3.0\%$) vs. Fixed Quantity steppers.
3. **Technical Breakdown Drawer (`#modalAnalysisDrawer`)**:
   - Multi-pillar checklist, 5-level depth imbalance bar, and 10-minute closing delta bars.
4. **Position SL / TP Edit Modal (`#editPositionModal`)**:
   - Dialog to modify Target 1, Target 2, and Stop Loss on active open positions.
5. **Win Rate Analytics Modal (`#winRateModal`)**:
   - High-conviction win rate gauges and historical evaluation ledger.
6. **Strategy Form & AI Clarification Modal (`#strategyFormModal`)**:
   - Custom strategy builder with Claude 3.5 AI clarification prompt.
7. **Platform Intro Video Overlay (`#tradexoIntroOverlay`)**:
   - High-definition video player overlay with audio controls.

---

# 6. FRONTEND DESIGN SYSTEM & TYPOGRAPHY STANDARDS

### 6.1 Typography Hierarchy
- **Body & Interface Text**: **'Inter'**, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif.
- **Numeric & Derivatives Data**: **'JetBrains Mono'**, 'Fira Code', monospace with `font-variant-numeric: tabular-nums`.
- **Brand Wordmark**: **'Syne'**, 'Inter', sans-serif.

### 6.2 Master CSS Design Tokens (`styles.css`)
```css
:root, [data-theme="dark"], html.dark-mode {
    --bg-base: #0b0f19;
    --bg-surface: #111827;
    --border-subtle: #1f2937;
    --accent-gold: #d4af37;
    --bullish-green: #10b981;
    --bearish-red: #f43f5e;
    --text-primary: #f9fafb;
    --text-muted: #9ca3af;
    --font-heading: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --font-body: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --font-mono: 'JetBrains Mono', 'Fira Code', ui-monospace, SFMono-Regular, monospace;
}
```

### 6.3 Resilient Initialization Standard
All event listeners and navigation bindings are encapsulated in `initAppNavigationAndActions()` at the very top of the client script execution, wrapped in an isolated `try...catch` block. This guarantees that user interactions, tab switching, and modal triggers function independently of background data-fetching networks.
