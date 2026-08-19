# TRADEXO PAGE BLUEPRINT: STRATEGIES & SMC ENGINE (05)

## 1. Feature Overview & Architecture
The **Strategies & Smart Money Concepts (SMC) Engine** (`/strategies`) houses TRADEXO's autonomous quantitative execution playbooks. It provides a multi-strategy framework spanning classical institutional setups, order block models, volatility breakouts, and natural-language custom rule generation backed by Claude 3.5 AI.

---

## 2. The 7 Built-In Core Strategies
Each strategy operates as an independent quantitative pipeline with tailored parameters, timeframes, and conviction weightings:

### Strategy A: VWAP Trend Pullback Reversal
- **Timeframe**: 5-Minute Intraday.
- **Rules**:
  - Stock is in an established intraday uptrend (Price > 21 EMA > 50 EMA).
  - Price pulls back to the VWAP line (within 0.35% band).
  - Bullish reversal candlestick forms with volume spike >= 1.5x.
- **Direction**: `CALL (CE)`. Target: +1.5%, Stop Loss: -0.75%.

### Strategy B: Tight Range Breakdown Spike
- **Timeframe**: 15-Minute Intraday.
- **Rules**:
  - Price consolidates in a narrow band (< 0.8% range for 6+ candles).
  - Sudden high-volume breakdown below range support with volume spike >= 2.0x.
  - India VIX regime confirmation (< 14.0 for standard short setups).
- **Direction**: `PUT (PE)`. Target: -2.0%, Stop Loss: +0.9%.

### Strategy C: Opening Range Breakout (ORB 30)
- **Timeframe**: First 30 Minutes (9:15 - 9:45 AM IST).
- **Rules**:
  - Establishes Day High and Day Low during the initial 30-minute window.
  - Breakout above 30-min High with 2 consecutive 5-min closes outside the range.
  - Relative volume spike > 2.2x rolling 20-day benchmark.
- **Direction**: `CALL (CE)` on upside break; `PUT (PE)` on downside break.

### Strategy D: Smart Money Open Interest (OI) Surge
- **Timeframe**: 15-Minute Rolling Futures / Options Window.
- **Rules**:
  - Intraday Open Interest increases >= 8.0% in a 15-minute window.
  - Accompanied by positive price delta (Long Buildup confirmation).
  - Positive 5-level order depth bid imbalance (> 60% bids).
- **Direction**: `CALL (CE)`. Target: +2.5%, Stop Loss: -1.0%.

### Strategy E: Institutional Death Cross Distribution
- **Timeframe**: 15-Minute Intraday.
- **Rules**:
  - 9 EMA crosses below 21 EMA with 50 EMA sloping downwards.
  - Open Interest increases >= 6.0% with negative price delta (Short Buildup).
  - Cumulative Volume Delta (CVD) divergence (Aggressive Market Sells).
- **Direction**: `PUT (PE)`. Target: -2.2%, Stop Loss: +0.8%.

### Strategy F: Pre-Event Volatility Straddle / Breakout
- **Timeframe**: EOD Prior to Earnings / Macro Announcements.
- **Rules**:
  - Implied Volatility Percentile (IVP) < 25th percentile (Cheap Options).
  - High-impact corporate result or RBI MPC rate decision within 24 hours.
  - Symmetrical compression pattern on daily chart.
- **Direction**: `VOLATILITY STRADDLE (CE + PE)`. Target: +4.0% volatility expansion.

### Strategy G: Multi-Timeframe SMC Scanner (Order Blocks & FVG)
- **Timeframe**: 5m, 15m, 1h, 4h, Daily.
- **Rules**:
  - Identifies Fair Value Gaps (FVG), Liquidity Sweeps, and Order Blocks.
  - Detects Break of Structure (BOS) and Change of Character (CHoCH).
  - High-probability mitigations aligned with institutional order flow.

---

## 3. Custom Strategy Builder & AI Rule Clarifier
- **Natural Language Query**: Users describe trading rules in plain English (e.g., *"Buy when RSI crosses 60 and volume is 3x higher than average"*).
- **Claude 3.5 Clarification Engine**: Parses input into structured JSON configuration with validation against F&O parameters.
- **Dynamic Weight Override**: Allows custom tuning of 5-pillar conviction weights.

---

## 4. Backtesting & Forward-Testing Simulator
- **Simulation Window**: Backtests up to 365 days of historical tick/candle data.
- **Performance Metrics**: Calculates Win Rate %, Profit Factor, Max Drawdown %, Sharpe Ratio, and Expectancy per trade.

---

## 5. Backend API Endpoints & Contracts
- `GET /api/strategies`: Returns all built-in and custom strategy presets and active status.
- `POST /api/strategies/create`: Creates a new user strategy draft.
- `POST /api/strategies/clarify`: Submits rule description to Claude 3.5 AI Clarification Engine.
- `POST /api/strategies/smc/backtest`: Runs multi-timeframe SMC backtest simulation.
