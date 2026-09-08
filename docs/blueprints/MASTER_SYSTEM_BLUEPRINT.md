# TRADEXO — DEFINITIVE MASTER ARCHITECTURAL BLUEPRINT & QUANTITATIVE FORMULARY
**Version:** 47.0.0 (Institutional Production Grade)  
**System Class:** High-Conviction Institutional Momentum Engine, Overnight Gap Predictor & Virtual Options Execution Sandbox  
**Asset Universe:** National Stock Exchange of India (NSE) F&O Universe (230+ Highly Liquid Equities & Major Indices)  

---

# EXECUTIVE SUMMARY & SYSTEM PHILOSOPHY

**TRADEXO** is an institutional quantitative trading, diagnostics, and risk analytics workstation tailored for the Indian derivatives (F&O) equity markets. The system specializes in:
1. **BTST / STBT Gap Exploitation**: Predicting 9:15 AM opening price dislocations (gaps) from closing order flow, institutional accumulation, delivery shifts, and derivatives positioning between 3:15 PM and 3:30 PM IST.
2. **Sub-2ms Zero-Latency Execution Pipeline**: In-memory caching and tick processing ensuring real-time response times without exchange rate-limiting.
3. **100% Deterministic Virtual Sandbox (Paper Trading)**: A closed-loop simulated execution environment with realistic slippage, official F&O contract lot multipliers, flat regulatory fees, and real-time Mark-to-Market (MTM) ledger.
4. **Autonomous AI Sentinel & Self-Healing Watchdog**: 10-phase waterfall diagnostic suite and 4-pillar health watchdog that detects and repairs database mutex locks, stale processes, and WebSocket disconnections in real-time.

---

# TABLE OF CONTENTS
1. [PART 1: QUANTITATIVE FORMULARY & MATHEMATICAL FOUNDATIONS](#part-1-quantitative-formulary--mathematical-foundations)
   - 1.1 Paper Trading, Virtual Execution & Cost Model
   - 1.2 5-Pillar Confirmation Matrix & Scoring Mechanics
   - 1.3 Probability-Bucketed Overnight Gap Prediction
   - 1.4 Synthetic CVD & 5-Level Order Book Depth Imbalance
   - 1.5 Black-Scholes Options Pricing & Greeks Engine
   - 1.6 7 Institutional Intraday Strategy Playbooks & SMC
   - 1.7 9:15 AM Auto-Evaluation & Walk-Forward Weight Optimizer
   - 1.8 Autonomous Health Scoring & 10-Phase Waterfall Engine
2. [PART 2: SYSTEM ARCHITECTURE & DATA FLOW PIPELINE](#part-2-system-architecture--data-flow-pipeline)
   - 2.1 Backend Micro-Engine Architecture
   - 2.2 Data Ingestion & Caching Hierarchy
   - 2.3 Frontend Reactive Shell & Design System
3. [PART 3: EXHAUSTIVE PAGE & SECTION BLUEPRINTS (BIG TO SMALL)](#part-3-exhaustive-page--section-blueprints-big-to-small)
   - 3.1 Global Navigation Shell, Marquee & Telemetry Topbar
   - 3.2 Page 1: Scanner & Signals Engine
   - 3.3 Page 2: Index Intelligence & Macro Gate
   - 3.4 Page 3: Live 1-Second Option Chain & Matrix
   - 3.5 Page 4: Paper Trading Portfolio & MTM Ledger
   - 3.6 Page 5: Strategies & SMC Playbook Engine
   - 3.7 Page 6: Stocks News & Sentiment Radar
   - 3.8 Page 7: Global & Macro Telemetry
   - 3.9 Page 8: Institutional Flow & Block Deals Radar
   - 3.10 Page 9: Order Flow & Closing Aggression Veto
   - 3.11 Page 10: Accuracy & Win Rate Analytics
   - 3.12 Page 11: History, Signal Journal & Calibration
   - 3.13 Page 12: System Health & AI Sentinel Center
   - 3.14 Page 13: Guide, Methodology & System Settings
   - 3.15 Universal Modals, Drawers & Overlays

---

# PART 1: QUANTITATIVE FORMULARY & MATHEMATICAL FOUNDATIONS

---

## 1.1 Paper Trading, Virtual Execution & Cost Model

The paper trading engine (`paper_trading_service.py`) simulates realistic order execution without exposing live capital to financial risk. It accounts for real-world exchange frictions: market order slippage, exchange charges, and Securities Transaction Tax (STT).

### A. Capital & Position Sizing
- **Starting Virtual Capital ($C_0$)**: $₹10,00,000.00$ (Ten Lakhs INR).
- **Contract Quantity ($Q$)**:
  $$Q = \text{Lots} \times \text{Lot Size}$$
  *Where Lot Size is derived from official NSE F&O definitions (e.g., NIFTY = 25, BANKNIFTY = 15, RELIANCE = 250, INFY = 400).*
- **Risk-Allocated Position Sizing ($Q_{risk}$)**:
  When using Risk % Allocation ($R_{\%} \in \{0.5\%, 1.0\%, 2.0\%, 3.0\%\}$):
  $$\text{Risk Capital} = C_{\text{equity}} \times \frac{R_{\%}}{100}$$
  $$\text{Per-Share Risk} = |P_{\text{entry}} - P_{\text{SL}}|$$
  $$Q_{\text{calculated}} = \left\lfloor \frac{\text{Risk Capital}}{\text{Per-Share Risk} \times \text{Lot Size}} \right\rfloor \times \text{Lot Size}$$
  *(Enforces minimum $Q = \text{Lot Size}$ and checks margin bounds).*

---

### B. Execution Price with Dynamic Market Slippage
Market orders execute against a non-linear slippage model simulating bid-ask spread crossing and liquidity depth impact:
$$\text{slippage\_pct} \sim \mathcal{U}(0.0005, 0.0010) \quad [0.05\% \text{ to } 0.10\%]$$

- **For BUY / CALL Orders (Slippage increases purchase price)**:
  $$P_{\text{entry}} = \text{round}\left(P_{\text{raw}} \times (1 + \text{slippage\_pct}), 2\right)$$
- **For SELL / PUT Orders (Slippage decreases fill price)**:
  $$P_{\text{entry}} = \text{round}\left(P_{\text{raw}} \times (1 - \text{slippage\_pct}), 2\right)$$
- **For LIMIT Orders**:
  $$P_{\text{entry}} = P_{\text{limit}} \quad (\text{Zero slippage; fills at exact specified price}).$$

---

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

---

### D. Margin Verification & Account Allocation Gate
Prior to recording an order in `paper_positions`, the system executes an atomic margin check:
$$\text{Required Margin } (M_{\text{req}}) = (P_{\text{entry}} \times Q) + C_{\text{entry}}$$
- **Safety Gate**:
  $$\text{If } C_{\text{available}} < M_{\text{req}} \implies \mathbf{REJECT\ ORDER\ (\text{"Insufficient Virtual Funds"})}$$
- **On Fill**:
  $$C_{\text{available}}^{\text{new}} = C_{\text{available}} - M_{\text{req}}$$
  $$\text{Total Brokerage Paid}^{\text{new}} = \text{Total Brokerage Paid} + C_{\text{entry}}$$

---

### E. Live Mark-to-Market (MTM) Floating P&L
For every active position open in the portfolio, real-time MTM is continuously computed:
$$\Delta P = \begin{cases} 
P_{\text{LTP}} - P_{\text{entry}} & \text{for BUY / CALL / BTST} \\
P_{\text{entry}} - P_{\text{LTP}} & \text{for SELL / PUT / STBT}
\end{cases}$$
$$\text{Gross MTM} = \Delta P \times Q$$
$$\text{Est. Exit Charges } (C_{\text{exit}}^{\text{est}}) = ₹20.00 + \text{round}(P_{\text{LTP}} \times Q \times 0.0010, 2)$$
$$\mathbf{\text{Net Unrealized MTM P\&L}} = \text{round}\left(\text{Gross MTM} - C_{\text{exit}}^{\text{est}}, 2\right)$$
$$\text{Unrealized P\&L \%} = \text{round}\left(\frac{\Delta P}{P_{\text{entry}}} \times 100, 2\right)$$

---

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
$$\text{Realized P\&L \%} = \text{round}\left(\frac{\text{Gross Realized P\&L}}{P_{\text{entry}} \times Q} \times 100, 2\right)$$

---

### G. Aggregate Portfolio Analytics
$$\text{Invested Margin} = \sum_{p \in \text{Open}} (P_{\text{entry}, p} \times Q_p)$$
$$\text{Total Portfolio Equity} = C_{\text{available}} + \text{Invested Margin} + \sum_{p \in \text{Open}} \text{Net MTM}_p$$
$$\text{Total Realized P\&L} = \sum_{t \in \text{Closed}} \text{Net Realized P\&L}_t$$
$$\text{Total Cumulative P\&L} = \text{Total Realized P\&L} + \sum_{p \in \text{Open}} \text{Net MTM}_p$$
$$\text{Total Return on Capital \%} = \text{round}\left(\frac{\text{Total Cumulative P\&L}}{C_0} \times 100, 2\right)$$
$$\text{Win Rate \%} = \text{round}\left(\frac{\sum [ \text{Net Realized P\&L} > 0 ]}{\text{Total Closed Trades}} \times 100, 1\right)$$

---

## 1.2 5-Pillar Confirmation Matrix & Scoring Mechanics

The core engine (`scoring_engine.py`) subjects all 230+ F&O stocks to a multi-factor confirmation filter.

### Pillar Breakdown & Formulations

```
+-----------------------------------------------------------------------------------------------+
|                               THE 5-PILLAR CONFIRMATION MATRIX                                 |
+-----------------------------------+-----------------------------------------------------------+
| Pillar 1: Futures Open Interest   | ΔPrice x ΔOI Quadrant Analysis (Long/Short Buildup)       |
| Pillar 2: Volume Persistence      | Trailing Volume >= 1.5x Baseline & Delivery >= 1.15x      |
| Pillar 3: Relative Strength (RS)  | |Stock %Δ - Nifty %Δ| >= 0.4% with directional alignment  |
| Pillar 4: Volume Surge Ratio      | 5-Minute Volume Surge >= 1.8x against 20-EMA Baseline     |
| Pillar 5: Marubozu Range Position | Intraday Range Close >= 98.0% (Bullish) or <= 2.0% (Bear) |
| Pillar 6: Institutional Flow      | Tiered Block Deals (₹25Cr - ₹150Cr+) Directional Filter   |
+-----------------------------------+-----------------------------------------------------------+
```

#### Pillar 1: Futures OI & Price Relationship ($W_1 = 1.0$)
Analyzes the derivatives participant positioning:
$$\Delta \text{Price} = P_{\text{Close}} - P_{\text{OpenSession}}, \quad \Delta \text{OI} = \text{OI}_{\text{current}} - \text{OI}_{\text{session\_open}}$$
1. **Long Buildup (Bullish BTST)**: $\Delta \text{Price} > 0 \land \Delta \text{OI} > 1.5 \times \overline{\Delta \text{OI}}_{10d}$
2. **Short Buildup (Bearish STBT)**: $\Delta \text{Price} < 0 \land \Delta \text{OI} > 1.5 \times \overline{\Delta \text{OI}}_{10d}$
3. **Short Covering**: $\Delta \text{Price} > 0 \land \Delta \text{OI} < 0$ (Cautious Bullish)
4. **Long Unwinding**: $\Delta \text{Price} < 0 \land \Delta \text{OI} < 0$ (Cautious Bearish)
- **Monthly Expiry Window Dampener**:
  On monthly expiry day (last Tuesday of the month for NSE stock F&O) and $+2$ sessions post-expiry:
  $$W_1^{\text{effective}} = W_1 \times 0.50 \quad (\text{Roll-over noise protection}).$$

#### Pillar 2: Volume Persistence & Delivery % Validation ($W_2 = 1.0$)
Validates whether smart money is genuinely carrying positions overnight:
$$V_{\text{trailing}} \ge 1.5 \times V_{\text{session\_baseline}}$$
$$\text{Delivery Ratio} = \frac{\text{Delivery \% Today}}{\overline{\text{Delivery \%}}_{10d}} \ge 1.15$$
- If both volume and delivery confirm: $W_2^{\text{effective}} = 1.0$.
- If delivery contradicts the volume signal: $W_2^{\text{effective}} = 0.50$.

#### Pillar 3: Relative Strength vs Nifty 50 Index ($W_3 = 1.0$)
$$\text{RS}_{\text{Nifty}} = \text{Stock \% Change} - \text{Nifty 50 \% Change}$$
- **Bullish BTST Confirmation**: $\text{RS}_{\text{Nifty}} \ge +0.40\%$ (Stock outperforming index).
- **Bearish STBT Confirmation**: $\text{RS}_{\text{Nifty}} \le -0.40\%$ (Stock underperforming index).

#### Pillar 4: Volume Surge vs Baseline ($W_4 = 1.0$)
Measures the aggressiveness of late-session order placement:
$$\text{Surge Ratio} = \frac{\max(V_{\text{last\_4\_candles}})}{V_{\text{SMA20\_baseline}}} \ge 1.80\times$$

#### Pillar 5: Normalized Marubozu Range Position ($W_5 = 1.0$)
Measures where the stock is trading relative to its complete daily range:
$$\text{Range Position \%} = \frac{P_{\text{LTP}} - P_{\text{DailyLow}}}{P_{\text{DailyHigh}} - P_{\text{DailyLow}}} \times 100\%$$
- **Bullish Marubozu (Closing at extreme high)**: $\text{Range Position \%} \ge 98.0\%$
- **Bearish Marubozu (Closing at absolute low)**: $\text{Range Position \%} \le 2.0\%$

#### Pillar 6: Institutional Flow & Bulk/Block Deals ($W_6 \in [0.5, 1.5]$)
Aggregates same-day institutional block deals:
- Tier 1: ₹25 Cr to ₹50 Cr $\implies W_6 = 0.50$
- Tier 2: ₹50 Cr to ₹150 Cr $\implies W_6 = 1.00$
- Tier 3: > ₹150 Cr $\implies W_6 = 1.50$
- Directional alignment required; sell-side weight is dampened by $0.70\times$ due to institutional index rebalancing frequency.

---

### Liquidity Tier Gating & Verdict Logic
The stock universe is divided into two distinct liquidity tiers:
1. **TIER 1 (Top 30 Liquid Mega-Caps & Nifty 50 Constituents)**:
   $$\text{Threshold Gate: } W_{\text{confirmed}} \ge 3.0 \text{ Pillars}$$
2. **TIER 2 (Rest of NSE F&O Universe — ~200 Mid-Cap/Liquid F&O)**:
   $$\text{Threshold Gate: } W_{\text{confirmed}} \ge 4.0 \text{ Pillars}$$

$$\text{Verdict} = \begin{cases}
\text{BTST (BUY)} & \text{if } W_{\text{confirmed}} \ge W_{\text{required}} \land \text{Bias} == \text{Bullish} \land \text{Veto} == \text{False} \\
\text{STBT (SELL)} & \text{if } W_{\text{confirmed}} \ge W_{\text{required}} \land \text{Bias} == \text{Bearish} \land \text{Veto} == \text{False} \\
\text{NEUTRAL / WATCHLIST} & \text{otherwise}
\end{cases}$$

### Quantitative Confidence Score (0% – 100%)
$$\text{Base Score} = 40.0 + \left( \frac{W_{\text{confirmed}}}{W_{\text{required}}} \times 40.0 \right)$$
$$\text{Confidence Score} = \min\left(95.0, \text{round}(\text{Base Score} + \text{Bonus}_{\text{Pillar5}} + \text{Bonus}_{\text{MacroGate}}, 1)\right)$$

---

## 1.3 Probability-Bucketed Overnight Gap Prediction

The gap prediction engine (`gap_bucket_engine.py`) models expected opening price gaps across 4 discrete intervals:
- **Bucket 1 ($B_1$)**: $0.0\% \text{ to } 1.0\%$ (Modest Gap)
- **Bucket 2 ($B_2$)**: $1.0\% \text{ to } 2.0\%$ (Standard Gap)
- **Bucket 3 ($B_3$)**: $2.0\% \text{ to } 3.0\%$ (Strong Gap)
- **Bucket 4 ($B_4$)**: $> 3.0\%$ (Jackpot Gap)

### Empirical Analog Matching
1. Searches historical signal journal database for matching evaluations:
   $$\text{Analog Filter}: (\text{Symbol} == s) \land (\text{Direction} == d) \land (\text{Score} \in [\text{Score}-10, \text{Score}+10])$$
2. If total historical sample count $N_{\text{sample}} \ge 20$, compute Laplace-smoothed empirical probabilities:
   $$P(B_k) = \frac{\text{Count}(B_k) + 1}{N_{\text{sample}} + 4}$$
   *(Marked as `CONFIRMED (Empirical)` on UI).*
3. If $N_{\text{sample}} < 20$, uses a model-estimated distribution centered on the predicted gap:
   $$P_{\text{raw}}(B_k) = \exp\left( -\frac{(\text{Midpoint}(B_k) - \text{Gap}_{\text{pred}})^2}{2 \sigma_{\text{gap}}^2} \right)$$
   With deterministic ticker-specific entropy salt to prevent identical visual curves:
   $$\text{Salt} = \frac{\text{int}(\text{SHA256}(s)[:8], 16)}{2^{32} - 1}$$
   *(Marked as `PRELIMINARY (Estimated)` on UI).*

---

## 1.4 Synthetic CVD & 5-Level Order Book Depth Imbalance

To avoid expensive proprietary order flow data feeds, TRADEXO implements the **Lee-Ready Tick Rule** on real-time L2 depth streams (`synthetic_cvd_engine.py`):

### Lee-Ready Tick Rule Aggressor Classification
For every incoming tick at time $t$ with price $P_t$, best bid $B_t$, and best ask $A_t$:
$$\text{Aggressor Direction } (D_t) = \begin{cases}
+1 \text{ (BUY Aggressor)} & \text{if } P_t \ge A_t \text{ (Buyer lifted ask)} \\
-1 \text{ (SELL Aggressor)} & \text{if } P_t \le B_t \text{ (Seller hit bid)} \\
+1 & \text{if } B_t < P_t < A_t \land P_t > P_{t-1} \text{ (Uptick)} \\
-1 & \text{if } B_t < P_t < A_t \land P_t < P_{t-1} \text{ (Downtick)} \\
D_{t-1} & \text{if } P_t == P_{t-1} \text{ (Zero-tick)}
\end{cases}$$

### Cumulative Volume Delta (CVD)
Ticks are accumulated into 1-minute buckets $m$:
$$\Delta_m = \sum_{t \in m} (D_t \times \text{Volume}_t)$$
$$\text{CVD}_T = \sum_{m=1}^{T} \Delta_m$$

### 5-Level Order Book Depth Imbalance
From the top 5 levels of the limit order book:
$$\text{BidQty}_{5L} = \sum_{k=1}^{5} \text{BidQty}_k, \quad \text{AskQty}_{5L} = \sum_{k=1}^{5} \text{AskQty}_k$$
$$\text{Depth Ratio} = \frac{\text{BidQty}_{5L}}{\text{AskQty}_{5L}}$$
$$\text{Bid \%} = \frac{\text{BidQty}_{5L}}{\text{BidQty}_{5L} + \text{AskQty}_{5L}} \times 100\%, \quad \text{Ask \%} = 100\% - \text{Bid \%}$$

### 3:15 PM – 3:25 PM Closing Sequence Veto Gate
Between 3:15 PM and 3:25 PM IST (Power Hour Closing):
$$\text{Closing Delta } (\Delta_{\text{close}}) = \sum_{m=3:15}^{3:25} \Delta_m$$
- **BTST VETO TRIGGER**: If a bullish setup displays $\Delta_{\text{close}} < 0$ OR $\text{Bid \%} < 40.0\%$ $\implies \mathbf{VETOED\ (\text{"Overruled by Institutional Order Flow"})}$.
- **STBT VETO TRIGGER**: If a bearish setup displays $\Delta_{\text{close}} > 0$ OR $\text{Ask \%} < 40.0\%$ $\implies \mathbf{VETOED}$.

---

## 1.5 Black-Scholes Options Pricing & Greeks Engine

Derivatives metrics (`options_greeks_analyzer.py`) use standard closed-form Black-Scholes equations for European-style Indian index and stock options:

### Equations
$$d_1 = \frac{\ln(S / K) + \left(r + \frac{\sigma^2}{2}\right)T}{\sigma \sqrt{T}}, \quad d_2 = d_1 - \sigma \sqrt{T}$$
*Where:*
- $S$ = Spot price (LTP of underlying asset)
- $K$ = Strike price
- $T$ = Days to expiry / 365.0
- $\sigma$ = Implied Volatility (IV % / 100.0 from NSE exchange feed)
- $r$ = Risk-free rate (Fixed benchmark assumption: $0.07$ or $7.0\%$ RBI yield)

### Greeks Formulations
- **Delta ($\Delta$)**:
  $$\Delta_{\text{CE}} = \mathcal{N}(d_1), \quad \Delta_{\text{PE}} = \mathcal{N}(d_1) - 1$$
- **Gamma ($\Gamma$)**:
  $$\Gamma = \frac{\mathcal{N}'(d_1)}{S \sigma \sqrt{T}}$$
- **Theta ($\Theta$ per calendar day)**:
  $$\Theta_{\text{CE, annual}} = -\frac{S \mathcal{N}'(d_1) \sigma}{2\sqrt{T}} - r K e^{-r T} \mathcal{N}(d_2)$$
  $$\Theta_{\text{PE, annual}} = -\frac{S \mathcal{N}'(d_1) \sigma}{2\sqrt{T}} + r K e^{-r T} \mathcal{N}(-d_2)$$
  $$\Theta_{\text{per\_day}} = \frac{\Theta_{\text{annual}}}{365.0}$$
- **Vega ($\nu$ per 1% IV shift)**:
  $$\text{Vega} = \frac{S \mathcal{N}'(d_1) \sqrt{T}}{100.0}$$

---

## 1.6 7 Institutional Intraday Strategy Playbooks & SMC

The strategy engine (`strategy_engine_rules.py` & `smc_strategy.py`) executes 7 rule-based quantitative playbooks:

1. **VWAP Pullback (`vwap-pullback-v1`)**:
   - Condition: Price pulls back to within $0.20\%$ of intraday VWAP ($|P - \text{VWAP}| / \text{VWAP} \le 0.002$).
   - Filter: $45.0 \le \text{RSI}(14) \le 55.0$ and Volume $\ge 1.2\times$ 20-EMA.
2. **Breakdown Spike (`breakdown-spike-v1`)**:
   - Condition: Breaks intraday support low with volume $\ge 2.0\times$ 20-EMA.
   - Filter: Bearish candle spread $> 1.5\times$ ATR(14).
3. **Opening Range Breakout 30 (`orb-v1`)**:
   - Condition: High/Low established between 9:15 AM and 9:45 AM IST.
   - Trigger: Candle closes above ORB High (BUY) or below ORB Low (SELL) with volume confirmation. Enforces strict single-trigger-per-day rule.
4. **Open Interest Surge (`oi-surge-v1`)**:
   - Condition: 15-minute OI expansion $\ge +10.0\%$ with directional price movement ($> +0.5\%$ for CALL, $< -0.5\%$ for PUT).
5. **Death Cross / Golden Cross (`death-cross-v1`)**:
   - Condition: 50-period EMA crossing 200-period EMA on 15m/1h timeframe.
6. **Volatility Straddle (`volatility-straddle-v1`)**:
   - Condition: India VIX $\le 13.0$ or IV percentile $< 20.0\%$ ahead of major scheduled macro events (RBI Policy, Union Budget, US FOMC).
7. **SMC Order Block & Fair Value Gap (FVG)**:
   - Identifies institutional displacement candles where Candle 1 High and Candle 3 Low leave an unfilled gap (FVG). Evaluates institutional re-tests of mitigating Order Blocks.

---

## 1.7 9:15 AM Auto-Evaluation & Walk-Forward Weight Optimizer

### 9:15 AM Evaluation Logic
At 9:15:05 AM IST every trading morning, the system reconciles yesterday's 3:30 PM signals against market open prices:
$$\text{Realized Gap \%} = \frac{P_{\text{Open, 9:15 AM}} - P_{\text{Close, 3:30 PM Yesterday}}}{P_{\text{Close, 3:30 PM Yesterday}}} \times 100\%$$
- **Directional Accuracy**:
  $$\text{Correct} = \begin{cases}
  \text{True} & \text{if } \text{Signal} == \text{BTST} \land \text{Realized Gap \%} > 0 \\
  \text{True} & \text{if } \text{Signal} == \text{STBT} \land \text{Realized Gap \%} < 0 \\
  \text{False} & \text{otherwise}
  \end{cases}$$
- **Trade Win Criteria**:
  A signal is marked a `TRADE_WIN` if hypothetical trade exit at 9:15 AM yields $> +0.50\%$ net return after deducting $0.10\%$ slippage and $₹40$ round-trip charges.

### Dynamic Walk-Forward Weight Optimizer (`walk_forward_validator.py`)
Re-calibrates individual pillar weights based on a 30-day rolling out-of-sample window ($N \ge 30$ sample guardrail):
$$W_i^{\text{new}} = \text{clamp}\left( W_i^{\text{current}} \times \left(1.0 + \text{clamp}\left(\frac{\text{HitRate}_i - \text{Benchmark}}{100.0}, -0.15, +0.15\right)\right), 0.50, 1.50 \right)$$
- Protects against over-fitting: Maximum daily weight shift is strictly capped at $\pm 15\%$.

---

## 1.8 Autonomous Health Scoring & 10-Phase Waterfall Engine

The diagnostics engine (`ai_sentinel.py`) computes a real-time composite health index:
$$\text{Composite Health Score} = \sum_{k=1}^{4} (0.25 \times \text{Score}_{\text{Category } k}) - \text{Penalty}_{\text{MidMarketColdStarts}}$$
- **Category 1: Core Scheduling**: 9:15 AM evaluation, 3:25 PM snapshot, 3:30 PM lock cron execution.
- **Category 2: Data Integrity & Anti-Stub**: Validates zero dummy or synthetic fallback values during market hours.
- **Category 3: Frontend APIs**: Latency benchmarking across all `/api` endpoints ($< 500\text{ms}$ nominal).
- **Category 4: Notifications & Journals**: Integrity of SQLite databases, WAL mode, and WebSocket broadcast queues.

### 10-Phase Waterfall Telemetry
1. **Phase 1: Broker Gateway Check**: Angel One SmartAPI authentication, session tokens, and connection mode.
2. **Phase 2: Fast-Cache Integrity**: RAM cache response times ($< 2\text{ms}$) and symbol count ($210+$ symbols).
3. **Phase 3: Database Mutex Audit**: SQLite concurrency, write locks, and auto-purging of orphaned lockfiles.
4. **Phase 4: WebSocket Backpressure**: Tick queue buffer status and broadcast consumer health.
5. **Phase 5: Fast-Path Heartbeat**: REST API latency verification.
6. **Phase 6: Heavy Worker State**: Thread pool allocation (24 background worker threads).
7. **Phase 7: Execution Math Gate**: Virtual paper trading ledger verification and balance reconciliation.
8. **Phase 8: News Quota Guard**: Upstream news provider rate-limits and caching freshness.
9. **Phase 9: Self-Healing Dispatcher**: Autonomous resolution of discovered anomalies.
10. **Phase 10: Live Telemetry Stream**: Active client broadcast verification.

---

# PART 2: SYSTEM ARCHITECTURE & DATA FLOW PIPELINE

```
+----------------------------------------------------------------------------------------------------------------+
|                                              TRADEXO APP SHELL                                                 |
|                               (Vanilla JavaScript, Custom CSS, Institutional Theme)                           |
+----------------------------------------------------------------------------------------------------------------+
             |                                                  |                                 |
   REST Requests (<2ms)                                 WebSocket Ticker Stream           DOM UI State Updates
             v                                                  v                                 v
+----------------------------------------------------------------------------------------------------------------+
|                                           FASTAPI APPLICATION BACKEND                                          |
|                                               (`app.py` - Port 8000)                                           |
+--------------------+-------------------------+------------------------+----------------------------------------+
| 1. SCANNER ENGINE  | 2. LIVE OPTION CHAIN    | 3. PAPER TRADING ENGINE| 4. AI SENTINEL ENGINE                  |
| - 5-Pillar Matrix  | - 1-Second Polling Loop | - Virtual Portfolio HUD| - 10-Phase Waterfall Engine            |
| - Gap Forecaster   | - Black-Scholes Greeks  | - ₹10L Starting Cash   | - Autonomous Self-Healing              |
| - 3:15 Veto Engine | - Strike Selector (ATM) | - Real-time MTM Ledger | - Live Rolling Console Log             |
+--------------------+-------------------------+------------------------+----------------------------------------+
             |                                                  |                                 |
             +-------------------------+------------------------+---------------------------------+
                                       |
                                       v
+----------------------------------------------------------------------------------------------------------------+
|                                         PERSISTENCE & CACHING HIERARCHY                                        |
+----------------------------------------------------------------------------------------------------------------+
| - `cache_layer.py`: Fast in-memory cache (<2ms latency, thread-safe memory dictionaries)                       |
| - `data/paper_trading.db`: SQLite database storing paper account balances, positions, fees, and order tickets  |
| - `data/signal_journal.db`: SQLite database storing historical signals, evaluations, and accuracy telemetry    |
| - `data/system_health_log.json`: Rolling diagnostic log, market transitions, cold starts, and audit archive   |
| - `data/active_pillar_weights.json`: Dynamic walk-forward calibrated weights                                  |
+----------------------------------------------------------------------------------------------------------------+
```

---

# PART 3: EXHAUSTIVE PAGE & SECTION BLUEPRINTS (BIG TO SMALL)

---

## 3.1 Global Navigation Shell, Marquee & Telemetry Topbar

- **Header Wordmark & Brand Frame**: Dual-theme adaptive SVG logo with tagline `"Market To Conviction"`.
- **Top Marquee Ticker Bar (`#marqueeTrack`)**:
  - Infinite hardware-accelerated horizontal scrolling strip.
  - Streams live ticker quotes for: `NIFTY 50`, `BANK NIFTY`, `FINNIFTY`, `SENSEX`, `GIFT NIFTY`, and Top Priority P1 candidates with color-coded point and percentage changes.
- **Market Status Pill (`#topbarMarketStatusBadge`)**:
  - Dynamically updates based on Indian Standard Time:
    - `09:00 - 09:15 AM`: `PRE-MARKET` (Amber)
    - `09:15 AM - 03:14 PM`: `REGULAR_SESSION (LIVE)` (Emerald)
    - `03:14 - 03:25 PM`: `POWER_HOUR (CLOSING AGGRESSION)` (Gold)
    - `03:25 - 03:30 PM`: `CLOSING_LOCK (OVERNIGHT FREEZE)` (Purple)
    - `03:30 PM - 09:00 AM`: `MARKET_CLOSED (OFF-MARKET SNAPSHOT)` (Muted Slate)
- **Top Action Bar Buttons**:
  - `FORCE SCAN NOW` (`#scanBtn`): Triggers immediate 230-stock scan cycle.
  - `WIN RATE` (`#winRateBtn`): Launches Accuracy Analytics modal.
  - `EXPORT CSV` (`#exportCsvBtn`): Downloads active watchlist as CSV.
  - `PLATFORM INTRO` (`#sidebarWatchIntroBtn`): Launches cinematic overview video.
- **Left Navigation Sidebar (`#appSidebar`)**:
  - Houses 14 section navigation buttons with active states, icons, and drawer toggle controls.

---

## 3.2 Page 1: Scanner & Signals Engine (`data-section="scanner"`)

### A. High-Conviction Telemetry Metric Cards
Four top-level overview cards:
1. **Total Scanned (`#totalScanned`)**: Total F&O stocks currently indexed ($230+$).
2. **Priority 1 High Conviction (`#priority1Count`)**: Stocks meeting strict high-conviction criteria (Score $\ge 80$, Gap $\ge 1.2\%$, Vol Surge $\ge 2.0\times$).
3. **BTST Bullish (`#btstCount`)**: Count of overnight long breakout setups (`CALL / CE`).
4. **STBT Bearish (`#stbtCount`)**: Count of overnight short distribution setups (`PUT / PE`).

### B. Multi-Filter & Search Toolbar
- **Tab Filter Pills**: `ALL`, `P1 HIGH CONVICTION`, `P2 MEDIUM`, `BTST (BUY)`, `STBT (SELL)`, `TOP 5 ONLY`.
- **Search Box (`#searchInput`)**: Real-time ticker filter by name or symbol.
- **Sort Dropdown (`#sortSelect`)**: Sorts by Rank, Confidence Score, Predicted Gap, Volume Surge, or LTP.

### C. Main Scanner Data Table (12 Columns)
1. **RANK**: Algorithm rank (`#1`, `#2`) with gold crown for Top 2.
2. **TICKER**: Symbol, SVG logo, and phase badge.
3. **SIGNAL**: `BTST (BUY)` (Emerald) or `STBT (SELL)` (Rose).
4. **OPTION**: Suggested contract type (`CALL (CE)` or `PUT (PE)`).
5. **PRIORITY**: `P1_HIGH`, `P2_MEDIUM`, or `P3_WATCHLIST`.
6. **PREDICTED GAP**: Expected overnight gap % (`+1.85% EST`).
7. **LTP (₹)**: Last Traded Price in monospace tabular typography.
8. **VOL SURGE**: Intraday surge relative to baseline (e.g., `2.8x VOL`).
9. **RSI (14)**: Wilder's smoothed 14-period RSI.
10. **PILLARS**: 5-Pillar visual mini progress bar.
11. **CONVICTION**: Progress meter showing aggregate confidence score ($0-100\%$).
12. **ACTION**: Expand/collapse chevron.

### D. Expandable Row Accordion & 4-Button Action Bar
Clicking any table row reveals:
- **Gap Probability Meter**: Visual histogram across 4 gap intervals ($0-1\%, 1-2\%, 2-3\%, 3\%+$) with analog sample count.
- **The 4-Button Dedicated Action Bar**:
  1. `ANALYSIS`: Opens multi-pillar technical breakdown drawer.
  2. `⚡ PAPER TRADE`: Pre-populates and launches the Options Demo Trading Modal.
  3. `CHART`: Displays interactive candlestick chart with VWAP and SL/TP lines.
  4. `OPTION CHAIN`: Opens live 1-second option chain matrix for the symbol.

---

## 3.3 Page 2: Index Intelligence & Macro Gate (`data-section="indices"`)

- **Multi-Index Telemetry Cards**: Live tracking of `NIFTY 50`, `BANK NIFTY`, `FINNIFTY`, `SENSEX`, and `GIFT NIFTY`.
- **Derivatives Sentiment Gauges**:
  - **Put-Call Ratio (PCR)**: Real-time PCR calculation ($< 0.70$ Bearish, $0.70 - 1.30$ Neutral, $> 1.30$ Bullish).
  - **Max Pain**: Strike price where option writers face minimum payout at expiry.
- **Macro Pullback Gate HUD**:
  - Analyzes global catalysts: GIFT Nifty dislocation, India VIX ($> 20.0$ Volatility Alert), Dow Futures, Crude Oil, USD/INR.
  - Automatically dampens bullish BTST scores when global macro conditions indicate gap-down vulnerability.
- **Sector Weight Overrides**: Visual contribution breakdown of Banking, IT, Energy, Auto, and FMCG sectors.

---

## 3.4 Page 3: Live 1-Second Option Chain & Matrix (`data-section="liveTrades"`)

- **1-Second High-Frequency Polling Loop**: In-memory zero-latency option chain resolver.
- **Header Telemetry**: Underlying Spot LTP, Official Contract Lot Size, Aggregate PCR, and Max Pain strike.
- **Expiry Selector**: Dropdown auto-populated with weekly and monthly contract expiry dates.
- **Double-Sided Options Matrix Table**:
  - **CALLS (CE) Left Side**: Open Interest (OI), Change in OI, Volume, LTP (Green highlight).
  - **Center Strike Pillar**: Center column showing strike prices, with At-The-Money (ATM) row highlighted in gold.
  - **PUTS (PE) Right Side**: LTP (Red highlight), Volume, Change in OI, Open Interest (OI).
- **Click-to-Trade Integration**: Clicking any Call or Put LTP immediately opens the Virtual Options Execution Modal pre-filled with the exact strike and contract type.

---

## 3.5 Page 4: Paper Trading Portfolio & MTM Ledger (`data-section="paperTrading"`)

- **Portfolio Executive HUD**:
  - **Total Portfolio Equity**: Live total account value ($C_{\text{available}} + \text{Invested Margin} + \text{Net MTM}$).
  - **Available Virtual Cash**: Unallocated capital available for new margin.
  - **Invested Margin**: Total capital allocated to active positions.
  - **Realized P&L**: Net cumulative closed trade profit/loss after fees.
  - **Unrealized MTM P&L**: Real-time ticking floating profit/loss across all open positions.
  - **Total Brokerage Paid**: Accumulated virtual regulatory charges and brokerage.
  - **Win Rate %**: Percentage of closed trades ending in profit.
- **Active Positions Table**:
  - Lists open contracts with ID, Symbol, Leg, Entry Price, Current Price (LTP), Net Unrealized P&L (₹ and %), Est. Exit Charges, Target 1, Target 2, and Stop Loss.
  - Actions: `MODIFY TARGET / SL` (launches modal) and `CLOSE POSITION` (liquidates trade at live market price).
- **Closed Trades Ledger**:
  - Historical archive of closed paper positions showing Entry, Exit, Net Realized P&L, Charges Paid, and execution timestamps.

---

## 3.6 Page 5: Strategies & SMC Playbook Engine (`data-section="strategies"`)

- **7 Institutional Strategy Cards**:
  - Status indicators (Active / Inactive / Scanning).
  - Description, entry rules, risk-reward ratio, and live signal counter.
- **Custom Strategy AI Builder**:
  - Natural-language interface allowing users to define custom quantitative rules.
  - Integrated AI Clarifier (Claude/GPT) to refine ambiguous entry/exit logic and convert it into deterministic python execution rules.
- **Strategy Signal Stream**:
  - Chronological feed of recent trade alerts generated across all active strategies.

---

## 3.7 Page 6: Stocks News & Sentiment Radar (`data-section="stocksNews"`)

- **Corporate News Feed**: Real-time corporate announcements, earnings releases, and board meetings.
- **Algorithmic Sentiment Classification**:
  - NLP score ranging from $-1.00$ (Deeply Bearish) to $+1.00$ (Strongly Bullish).
  - Visual badges: `BULLISH` (Emerald), `BEARISH` (Rose), `NEUTRAL` (Slate).
- **F&O Ticker Tagging**: Automatically maps news items to specific NSE F&O tickers and cross-references active scanner conviction.

---

## 3.8 Page 7: Global & Macro Telemetry (`data-section="globalNews"`)

- **World Indices Radar**: US Markets (S&P 500, Nasdaq, Dow Jones), European Bourses (FTSE, DAX), and Asian Markets (Nikkei, Hang Seng, GIFT Nifty).
- **Macro Indicators**: India VIX, US 10-Year Treasury Yield, Brent Crude Oil ($/bbl), and USD/INR exchange rate.
- **Geopolitical & Calendar Events**: Scheduled economic releases (US CPI, RBI MPC, FOMC rate decisions).

---

## 3.9 Page 8: Institutional Flow & Block Deals Radar (`data-section="institutionalFlow"`)

- **Large Block Transactions Feed**: Filters and highlights institutional deals $> ₹25 \text{ Cr}$.
- **Institutional Accumulation Tracker**: Aggregates net institutional buying/selling per symbol.
- **Institutional Directional Gate**: Validates whether institutional volume confirms or contradicts retail price action.

---

## 3.10 Page 9: Order Flow & Closing Aggression Veto (`data-section="orderFlow"`)

- **Synthetic CVD Live Chart**: 1-minute cumulative volume delta line chart tracking net buying/selling pressure.
- **5-Level Order Book Depth Imbalance Visualizer**: Real-time bid vs. ask depth ratio bar.
- **3:15 – 3:25 PM Power Hour Closing Aggression Panel**:
  - Displays closing 10-minute delta bars.
  - Veto status indicator (`CONFIRMED` or `VETOED BY ORDER FLOW`).

---

## 3.11 Page 10: Accuracy & Win Rate Analytics (`data-section="accuracy"`)

- **Overall Win Rate Gauge**: Circular visual meter showing historical direction accuracy % and trade win %.
- **Liquidity Tier Breakdown**: Win rate comparison between TIER 1 (Mega-Caps) vs TIER 2 (Mid-Caps).
- **Gap Realization Distribution**: Histogram of predicted vs. actual gap realization.
- **Historical Hit-Rate by Pillar**: Performance ranking showing which of the 5 pillars generated the highest win rate over the last 30 days.

---

## 3.12 Page 11: History, Signal Journal & Calibration (`data-section="history"`)

- **Complete Signal Journal Table**: Full chronological archive of every BTST/STBT signal generated by TRADEXO.
- **Predicted vs. Actual Ledger**: Details 3:30 PM predicted gap vs. next-day 9:15 AM opening price.
- **Walk-Forward Calibration HUD**: Displays active dynamic pillar weight multipliers and date of last recalibration.

---

## 3.13 Page 12: System Health & AI Sentinel Center (`data-section="systemHealth"`)

- **Command Toolbar & Cadence Manager**:
  - Connection beacon (`TELEMETRY LIVE`).
  - Auto-refresh cadence selector (`10s`, `30s`, `60s`, `OFF`) with visual animated 1-second countdown circle.
- **Hero Kill-Switch Banner & Engine Vitals HUD**:
  - Safe Pause / Resume control button.
  - Real-time countdown to next market milestone (`09:00 AM Pre-Market`, `09:15 AM Evaluation`, `15:25 PM Snapshot`, `15:30 PM Lock`).
  - Active worker thread counter (24 background worker threads).
  - SQLite ACID storage confirmation badge.
- **Executive Telemetry Cards**:
  - Health Score Multi-Ring SVG Gauge ($0-100\%$) with 4-pillar mini-score breakdown.
  - Market State & Schedule Mode with live ticking IST clock.
  - Overnight Lock & Evaluation Stats (Count of locked picks, graded trades, gap win rate).
  - Dyno Watchdog & Keepalive Uptime (Mid-market cold start counter, total starts, cached symbols).
- **AI Sentinel & Auto-Healing Center**:
  - 4 Category status cards (Core Scheduling, Data Integrity, Frontend APIs, Notifications & Journals).
  - Real-time Auto-Healing event feed and 1-click `"TRIGGER AI SELF-HEAL NOW"` action button.
- **10-Phase Waterfall Engine**:
  - Interactive status filters: `ALL`, `OPTIMAL`, `ISSUES`.
  - Step-by-step telemetry list showing phase number, name, target latency, measured latency, status badge, and auto-heal hooks.
- **Live System Terminal & Rolling Console**:
  - macOS/Bloomberg-styled dark console (`#0f172a` glass with traffic lights).
  - Streams live logs from `/api/system/logs` with real-time text search filter, severity tabs (`ALL`, `INFO`, `WARN`, `ERROR`), 1-click clipboard copy, and toggleable auto-scroll.
- **Daily Health Audit Archive Table**:
  - Historical archive of daily health audit reports with date search filter and 1-click JSON export.

---

## 3.14 Page 13: Guide, Methodology & System Settings (`data-section="guide"` & `data-section="rules"`)

- **5-Pillar Methodology Documentation**: Complete illustrated guide explaining each quantitative pillar.
- **Indian Market Schedule Reference**: Detailed breakdown of pre-market, regular session, power hour, closing lock, and off-market freeze.
- **System Settings & Data Management**:
  - Full system JSON/CSV database export buttons.
  - Cache purge and re-indexing controls.
  - Theme switcher (Champagne Gold Dark Mode vs. Clean Slate Light Mode).

---

## 3.15 Universal Modals, Drawers & Overlays

1. **Institutional Order Ticket Modal (`#orderTicketModal`)**:
   - Equity and stock trading ticket supporting MARKET (with slippage) and LIMIT orders.
   - Sizing controls: Risk % allocation ($0.5\%, 1.0\%, 2.0\%, 3.0\%$) vs. Fixed Quantity steppers.
   - Live cost and margin estimation box with real-time margin check.
2. **Advanced Options Demo Trading Modal (`#optionsDemoTradeModal`)**:
   - Specialized derivatives order ticket for CALL (CE) and PUT (PE) contracts.
   - Strike dropdown auto-centered around ATM, live option premium LTP, lot steppers with official multipliers, and margin validation.
3. **Position SL / TP Edit Modal (`#editPositionModal`)**:
   - Quick-modification dialog to adjust Target 1, Target 2, and Stop Loss on open positions.
4. **Live 1-Second Option Chain Modal (`#optionChainModal`)**:
   - Full-screen modal housing the complete 1-second ticking option chain matrix with strike and expiry controls.
5. **Technical Breakdown Drawer (`#modalAnalysisDrawer`)**:
   - Deep-dive panel displaying individual pillar checklists, 5-level depth imbalance bar, and 10-minute delta bars.
6. **Cinematic Intro Video Overlay (`#tradexoIntroOverlay`)**:
   - High-definition platform introduction video player.
