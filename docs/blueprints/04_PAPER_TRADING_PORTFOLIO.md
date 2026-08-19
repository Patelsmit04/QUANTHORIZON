# TRADEXO PAGE BLUEPRINT: PAPER TRADING & VIRTUAL OPTIONS EXECUTION (04)

## 1. Feature Overview & Purpose
The **Paper Trading Portfolio & Virtual Options Execution Engine** (`/paperTrading` or `#optionsDemoTradeModal` / `#orderTicketModal`) provides institutional-grade virtual trading simulation without exposing user capital to real financial risk.

### Core Guarantees:
- **Strictly Simulated (DEMO ONLY)**: No actual broker orders or API keys with execution privileges are used.
- **₹10,00,000 Starting Virtual Capital**: Every virtual account begins with ₹10 Lakhs in simulated cash.
- **Institutional Cost & Slippage Model**:
  - Brokerage: Flat ₹20.00 per executed order.
  - Securities Transaction Tax (STT): 0.1% on trade turnover.
  - Market Order Slippage: Random realistic variance between 0.05% and 0.10%.

---

## 2. Advanced Options Demo Trading Modal (`#optionsDemoTradeModal`)
Engineered specifically for derivatives traders to execute options contracts with complete precision:

### Form Inputs & Controls:
1. **Option Leg Type Toggle (`#optTypeToggleGroup`)**:
   - `CALL (CE)`: Bullish long breakout setup (Emerald theme).
   - `PUT (PE)`: Bearish short distribution setup (Rose theme).
2. **Strike Price Dropdown (`#optTradeStrikeSelect`)**:
   - Auto-populated with 15 strikes centered around ATM (At-The-Money).
   - Clearly flags `(ATM)`, `(ITM CE / OTM PE)`, and `(OTM CE / ITM PE)`.
3. **Live Premium Quote Card**:
   - Displays live ticking contract premium (LTP) formatted in amber typography.
4. **Number of Lots Stepper (`#optLotsInput`)**:
   - Steppers (`-` / `+`) and direct numeric entry.
   - **Lot Multiplier**: Automatically multiplies selected lots by the official lot size of the asset (e.g., NIFTY ×25, BANKNIFTY ×15, RELIANCE ×250, TCS ×175).
   - Shows Total Quantity (Units).
5. **Real-Time Margin & Cost Verification**:
   - `Premium Cost = Total Quantity * Option Premium`
   - `Simulated Fees = Flat ₹20 Brokerage + 0.1% STT`
   - `Total Margin Required = Premium Cost + Simulated Fees`
   - **Strict Safety Gate**: If `Total Margin Required > Available Virtual Cash`, the modal displays `⚠️ INSUFFICIENT VIRTUAL CAPITAL` and disables the execute button.
6. **Execution Button (`#executeOptionsTradeBtn`)**:
   - Triggers simulated execution and logs trade to `paper_positions` table in SQLite database.

---

## 3. Paper Trading Portfolio Workspace (`/paperTrading`)
Provides full position lifecycle management, Mark-to-Market (MTM) ledger, and analytics:

### Metric Cards:
- **Total Portfolio Equity**: `Cash Balance + Invested Margin + Live Unrealized MTM P&L`.
- **Available Cash**: Unallocated virtual capital available for new margin.
- **Realized P&L**: Net closed trade profit/loss after fees.
- **Unrealized MTM P&L**: Live ticking floating profit/loss across all open positions.
- **Total Brokerage Paid**: Accumulated virtual regulatory charges and brokerage.
- **Win Rate %**: Percentage of closed trades ending in profit.

### Active Positions Table:
- **Position ID & Symbol**: Contract identifier (e.g., `POS-RELIANCE 2980 CE-1724068200000`).
- **Entry Price vs Current LTP**: Real-time tick tracking.
- **Net MTM P&L & Return %**: Net of estimated exit charges.
- **Dynamic Action**:
  - `MODIFY TARGET / SL`: Launches `#editPositionModal` to adjust TP1 (+30%), TP2 (+60%), or SL (-30%).
  - `CLOSE POSITION`: Closes trade at current market price and credits cash back to virtual balance.

---

## 4. Backend API Endpoints & Contracts
- `GET /api/paper_trading/portfolio`: Returns complete account balance, open positions with live MTM P&L, and closed trade history.
- `POST /api/paper-trade/execute` or `POST /api/paper_trading/order`: Opens a new virtual position after margin verification.
- `POST /api/paper_trading/close/{position_id}`: Closes an open position at current market price.
- `POST /api/paper_trading/update/{position_id}`: Updates Target 1, Target 2, or Stop Loss.
