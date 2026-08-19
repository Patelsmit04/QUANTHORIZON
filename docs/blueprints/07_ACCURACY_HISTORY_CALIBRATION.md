# TRADEXO PAGE BLUEPRINT: ACCURACY, HISTORY & CALIBRATION (07)

## 1. Feature Overview & Architecture
The **Accuracy, History & Dynamic Calibration Engine** (`/accuracy` or `/history` or `#winRateModal`) provides verifiable forward-testing validation of TRADEXO's quantitative predictions.

### Key Autonomous Engines:
1. **9:15–9:17 AM Auto-Evaluation Engine**: Every morning, as market open prices arrive, the system automatically compares the **Predicted Overnight Gap %** against the **Actual Opening Gap %** for all picks locked the previous day.
2. **Signal Journal & SQLite Ledger**: Every locked trade is permanently stored in `data/signal_journal.db` with entry price, actual open price, variance error, and outcome badge.
3. **Dynamic Walk-Forward Pillar Weight Optimizer**: Once 30+ trades are evaluated, the algorithm recomputes the real statistical hit rate of each of the 5 technical pillars and dynamically tunes scoring weights (capped at ±15%/day to prevent overfitting).

---

## 2. Split Accuracy Grid (4 Benchmark Meters)
Rendered at the top of the Accuracy & Calibration workspace:
1. **P1 High-Conviction Accuracy**: Historical win rate of top-priority trades (e.g., `87.4% Win Rate`).
2. **Overall Platform Win Rate**: Aggregate accuracy across all locked BTST/STBT picks (e.g., `79.2%`).
3. **Average Predicted Gap Variance**: Mean absolute deviation between prediction and reality (e.g., `±0.32% Error`).
4. **Jackpot Trade Frequency**: Percentage of picks generating greater than **+1.5% overnight gap** (Crown badge).

---

## 3. Historical Evaluation Ledger Table
| Column | Field | Description |
| :--- | :--- | :--- |
| **DATE** | `trade_date` | Date of locked pick (YYYY-MM-DD). |
| **SYMBOL** | `symbol` | Stock ticker with option type (`CE` / `PE`). |
| **SIGNAL** | `signal` | `BTST (BUY)` or `STBT (SELL)`. |
| **CONVICTION** | `confidence_score` | Original algorithm score at 3:25 PM lock. |
| **PREDICTED GAP** | `predicted_gap_pct` | Estimated overnight opening gap (e.g., `+1.80%`). |
| **ACTUAL GAP** | `actual_gap_pct` | Real market open gap at 9:15 AM (e.g., `+2.10%`). |
| **VARIANCE ERROR** | `variance_error` | `|Predicted - Actual|` (e.g., `0.30%`). |
| **OUTCOME** | `outcome` | `JACKPOT WIN (+1.5%+)`, `WIN (+0.5%+)`, `NEUTRAL (Flat)`, `LOSS`. |

---

## 4. Dynamic Pillar Weight Optimizer (`/api/validation`)
- **Pillar 1: Technical & Momentum (RSI + MACD + Stochastics)**: Default 25%.
- **Pillar 2: Trend & Volatility (VWAP + Moving Averages + SuperTrend)**: Default 25%.
- **Pillar 3: Volume Surge & Liquidity (Rolling 20-Day Spike)**: Default 20%.
- **Pillar 4: Open Interest & Option Chain (PCR + Max Pain + IV)**: Default 15%.
- **Pillar 5: Fundamentals & News Quality Gates (P/E + Earnings + Headlines)**: Default 15%.
- **Daily Calibration Nudge**: Automatically shifts weight allocation toward pillars with highest empirical predictive correlation.

---

## 5. Backend API Endpoints & Contracts
- `GET /api/performance`: Returns overall win rate statistics, win/loss breakdown, and historical calibration curves.
- `GET /api/trade_history`: Returns paginated list of all evaluated historical BTST picks.
- `POST /api/lock_picks`: Locks today's candidate picks at 3:25/3:30 PM.
- `POST /api/evaluate_picks`: Runs opening gap analysis and grades pending trades at 9:15 AM.
- `GET /api/validation`: Returns 30-day walk-forward weight adjustment logs.
