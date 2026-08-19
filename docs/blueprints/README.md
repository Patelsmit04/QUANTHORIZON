# TRADEXO — MASTER ARCHITECTURE & PAGE BLUEPRINTS DIRECTORY

Welcome to the definitive, in-depth architectural and page blueprint documentation for **TRADEXO — High-Conviction Institutional Engine & Gap Predictor**.

---

## 📑 Complete Blueprint Index

| Blueprint Document | Scope & Workspaces Covered | Key Subsystems & Features |
| :--- | :--- | :--- |
| [**01. Scanner & Signals Engine**](01_SCANNER_DASHBOARD.md) | Primary Dashboard, F&O Universe Table, Marquee | 230+ F&O Stocks, 12-Column Grid, 4-Button Action Bar, Gap Probability Distribution, Real-time WebSockets |
| [**02. Index Intelligence & Macro Gate**](02_INDEX_INTELLIGENCE.md) | Nifty 50, Bank Nifty, FinNifty, Sensex, GIFT NIFTY | Multi-Index Telemetry, PCR & Max Pain, Macro Pullback Gate, Sector Weight Overrides |
| [**03. Live 1-Second Option Chain**](03_LIVE_1SEC_OPTION_CHAIN.md) | Derivatives Matrix Modal, Strike Polling | 1-Second Live Polling Loop, In-Memory Zero-Latency Cache, Official Lot Sizes, Click-to-Trade Integration |
| [**04. Paper Trading & Virtual Execution**](04_PAPER_TRADING_PORTFOLIO.md) | Virtual Options Execution Modal, Portfolio Workspace | ₹10,00,000 Virtual Capital, CE/PE Selector, Real-Time Margin Check, MTM Ledger, Target/SL Management |
| [**05. Strategies & SMC Engine**](05_STRATEGIES_ENGINE.md) | 7 Built-In Playbooks, Custom Strategy AI Builder | VWAP Pullback, Breakdown Spike, ORB 30, OI Surge, Death Cross, Volatility Straddle, Claude 3.5 Clarifier |
| [**06. Institutional Flow & Order Flow**](06_INSTITUTIONAL_AND_ORDER_FLOW.md) | Block Deals Feed, 3:15–3:25 PM Veto Layer | ₹25+ Cr Institutional Blocks, Synthetic CVD, 5-Level Depth Imbalance, 10-Minute Closing Aggression Veto |
| [**07. Accuracy, History & Calibration**](07_ACCURACY_HISTORY_CALIBRATION.md) | Win Rate Modal, Historical Calibration Ledger | 9:15 AM Auto-Evaluation, Predicted vs Actual Gap Ledger, 30-Day Walk-Forward Pillar Weight Optimizer |
| [**08. System Health & AI Sentinel**](08_SYSTEM_HEALTH_AI_SENTINEL.md) | Diagnostic Suite, Autonomous Watchdog | 19 In-Process Diagnostic Probes, Anti-Stub Detection, Stale Lock Purge, One-Click & Autonomous Healing |
| [**09. Stocks News & Global Macro**](09_NEWS_AND_GLOBAL_MACRO.md) | Corporate News Feed, Global Macroeconomic Radar | Zero-Cost Background Caching, CurrentsAPI / NewsAPI, Sentiment Classification (-1.0 to +1.0), Geopolitical Risk |
| [**10. Guide, Rules & Settings**](10_GUIDE_RULES_SETTINGS.md) | Rulebook, Methodology, CSV Export, Theme Engine | 5-Pillar Weight Matrix, Indian Market Schedule (9:00 AM – 3:30 PM), Light/Dark Themes, Video Reel |

---

## 🏛️ High-Level Technical Architecture

```
                                  +----------------------------------------------------+
                                  |            TRADEXO INSTITUTIONAL FRONTEND          |
                                  |   (Vanilla JS, Tailwind CSS, Responsive Web App)   |
                                  +-------------------------+--------------------------+
                                                            |
                             REST APIs (<2ms Fast Cache)    |    Real-Time WebSocket Streams
                                                            v
+----------------------------------------------------------------------------------------------------------------------+
|                                            FASTAPI HIGH-PERFORMANCE BACKEND                                          |
+--------------------------+------------------------------+-------------------------------+----------------------------+
| 1. SCANNER & QUANT ENGINE| 2. LIVE 1-SEC OPTION ENGINE  | 3. PAPER TRADING LEDGER       | 4. AI SENTINEL WATCHDOG    |
| - 5-Pillar Multi-Factor  | - In-Memory Matrix Resolver  | - ₹10,00,000 Virtual Capital  | - 19 Diagnostic Probes     |
| - Overnight Gap Predictor| - Black-Scholes Synthesizer  | - Dynamic Margin Verification | - Auto-Healing Mutex & DB  |
| - 3:15-3:25 PM Veto Gate | - Official F&O Lot Sizing    | - MTM Floating & Closed P&L   | - Zero External Hangs      |
+--------------------------+------------------------------+-------------------------------+----------------------------+
                                                            |
                                                            v
+----------------------------------------------------------------------------------------------------------------------+
|                                            PERSISTENCE & CACHING LAYER                                               |
| - In-Memory Fast Cache (`cache_layer.py`)               - SQLite Signal Journal (`data/signal_journal.db`)           |
| - Stock News Cache (`data/stock_news_cache.json`)       - Paper Trading Database (`data/paper_trading.db`)           |
+----------------------------------------------------------------------------------------------------------------------+
```

---

## 🔒 Strict Safety & Compliance Principles
1. **100% Simulated & Paper Trading**: Zero real money or live exchange execution APIs are connected. All margin calculations, brokerage fees, and position tracking are performed locally in a deterministic virtual sandbox.
2. **Sub-2ms Zero-Latency Responses**: All high-frequency polling (like the 1-second option chain) reads directly from local RAM, eliminating external API throttling or exchange rate-limit bans.
3. **Resilient Self-Healing**: Background watchdogs ensure orphaned mutex locks and temporary network dropped connections are instantly repaired without manual intervention.
