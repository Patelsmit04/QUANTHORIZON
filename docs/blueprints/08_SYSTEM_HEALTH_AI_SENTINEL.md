# TRADEXO PAGE BLUEPRINT: SYSTEM HEALTH & AI SENTINEL (08)

## 1. Feature Overview & Architecture
The **System Health & Autonomous AI Sentinel** (`/system-health` or `#systemHealthSection`) is the automated self-monitoring, diagnostic, and self-healing watchdog for TRADEXO. It operates 24/7, proactively running 19 diagnostic probes across network feeds, databases, background workers, and memory caches.

### Key Autonomous Capabilities:
1. **19 In-Process Diagnostic Probes**: Checks every critical endpoint (`/api/scan`, `/api/indices`, `/api/block-deals`, `/api/gift_nifty/live`, `/api/performance`, `/api/strategies`, `/api/news`, `/api/option-chain/NIFTY`, etc.).
2. **Anti-Stub & Real-Data Validation**: Flags and detects any mock stubs, stale data (>30m old), or unverified responses.
3. **Idempotent One-Click & Autonomous Self-Healing**: Automatically clears stale scan locks, repairs corrupt SQLite schema indexes, creates atomic database backups (`.bak`), and refreshes stale memory caches without restarting the server.
4. **Resilient Fast Diagnostic Protocol**: Bypasses slow external HTTP loops by calling in-process FastAPI endpoint functions with safety timeouts (<2.5s per probe), ensuring zero browser timeout aborts (`signal is aborted without reason` eliminated).

---

## 2. Telemetry Gauges & Status Indicators
- **Overall System Vitality (`#sentinelOverallStatus`)**:
  - `OPTIMAL (ALL SYSTEMS HEALTHY)` (Emerald Green).
  - `DEGRADED (ACTION REQUIRED)` (Amber Gold).
  - `CRITICAL (HEALING IN PROGRESS)` (Rose Red).
- **Core Subsystem Health Metrics**:
  - **Memory Cache Latency**: Average fast_cache fetch speed (e.g., `0.85 ms`).
  - **Active WebSocket Clients**: Number of live streaming browser sessions connected to `/ws/live`.
  - **Signal Journal Database Size**: Current SQLite file footprint and active transactions.
  - **Background Worker State**: Cron scheduler heartbeat status (`Active`, `Last Run: 15:25 IST`).

---

## 3. The 19 Diagnostic Probes Grid
Each probe is rendered with status badge, response latency (ms), and payload verification:

| # | Probe Name | Target Component | Verification Check |
| :--- | :--- | :--- | :--- |
| **1** | `SCAN_ENGINE_PROBE` | `/api/scan` | Validates active F&O snapshot and 5-pillar scores |
| **2** | `LIVE_PRICES_PROBE` | `/api/live_prices` | Checks in-memory fast_cache for ticking LTPs |
| **3** | `INDEX_INTEL_PROBE` | `/api/indices` | Verifies NIFTY 50, Bank Nifty, PCR, and Max Pain |
| **4** | `GIFT_NIFTY_PROBE` | `/api/gift_nifty/live` | Checks NSE IFSC Gift Nifty day/evening stream |
| **5** | `OPTION_CHAIN_PROBE` | `/api/option-chain/NIFTY` | Verifies 1-second options matrix and strike steps |
| **6** | `PAPER_TRADING_PROBE`| `/api/paper_trading/portfolio` | Checks virtual margin balance and open positions |
| **7** | `STRATEGIES_PROBE` | `/api/strategies` | Verifies all 7 built-in SMC algorithms |
| **8** | `BLOCK_DEALS_PROBE` | `/api/block-deals` | Checks ₹25+ Cr institutional block deals cache |
| **9** | `STOCK_NEWS_PROBE` | `/api/news` | Checks per-stock background news cache file |
| **10** | `GLOBAL_NEWS_PROBE` | `/api/news/global` | Verifies macroeconomic event headlines |
| **11** | `PERFORMANCE_PROBE` | `/api/performance` | Checks 9:15 AM win rate ledger |
| **12** | `CALIBRATION_PROBE` | `/api/validation` | Checks 30-day walk-forward pillar weights |
| **13** | `SIGNAL_JOURNAL_PROBE`| `signal_journal.db` | Verifies SQLite connectivity and ACID integrity |
| **14** | `FAST_CACHE_PROBE` | `cache_layer.py` | Validates in-memory TTL dictionary and purge |
| **15** | `LOCK_MUTEX_PROBE` | `scan.lock` | Checks for stale scan locks older than 5 minutes |
| **16** | `ANGEL_ONE_FEED_PROBE`| SmartAPI / yfinance | Checks market data fallback gateway |
| **17** | `CLOSING_TIMER_PROBE`| 3:15–3:25 PM Gate | Checks precision closing sequence timers |
| **18** | `WS_BROADCAST_PROBE` | `/ws/live` | Tests broadcast queue without memory leaks |
| **19** | `BACKUP_STORE_PROBE` | `data/backup_*.db` | Verifies automated atomic backup generation |

---

## 4. Autonomous & Manual Self-Healing Workflow
1. **Interactive Controls**:
   - `RUN FULL DIAGNOSTIC SCAN` (`#sentinelRunScanBtn`): Triggers in-process audit of all 19 probes.
   - `HEAL ALL DETECTED ISSUES` (`#sentinelHealAllBtn`): Executes atomic remediation pipeline.
2. **Self-Healing Actions**:
   - Cleans up abandoned `scan.lock` files left by unexpected process interrupts.
   - Re-synthesizes missing option chains or news caches.
   - Creates point-in-time timestamped backup of `signal_journal.db`.
   - Purges corrupt cache keys while preserving active market ticks.

---

## 5. Backend API Endpoints & Contracts
- `GET /api/system/health`: Returns current status of all 19 probes and overall system vitality.
- `POST /api/system/heal`: Executes autonomous self-healing and returns remediation logs.
- `GET /api/system/logs`: Streams live application logs with error highlighting.
