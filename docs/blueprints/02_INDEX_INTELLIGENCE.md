# TRADEXO PAGE BLUEPRINT: INDEX INTELLIGENCE & MACRO GATE (02)

## 1. Page Overview & Purpose
The **Index Intelligence** workspace (`/indices` or `/index-intelligence`) provides real-time quantitative analysis, options derivatives telemetry, and institutional sentiment tracking across the primary Indian benchmark indices:
- **NIFTY 50 (`^NSEI`)**
- **BANK NIFTY (`^NSEBANK`)**
- **FINNIFTY (`NIFTY_FIN_SERVICE`)**
- **MIDCPNIFTY (`NIFTY_MIDCAP_SELECT`)**
- **SENSEX (`^BSESN`)**
- **GIFT NIFTY (`GIFTNIFTY=F`)**

It serves as the **Macro Gatekeeper** for the entire platform. If major indices exhibit heavy distribution or macro pullbacks, conviction scores on individual equities are automatically adjusted to prevent bull traps.

---

## 2. Global Index Intelligence Cards (6 Index Matrices)
Each benchmark index is rendered in a dedicated institutional telemetry card:
1. **Header Block**: Index Title, live LTP, Day Change (Points & %), and Technical Trend Badge (`STRONG_BULLISH`, `MILD_BULLISH`, `NEUTRAL`, `BEARISH`).
2. **Options Derivatives Telemetry**:
   - **Put-Call Ratio (PCR)**: Measured across all strikes. PCR > 1.2 indicates strong put-writing support; PCR < 0.8 indicates aggressive call writing resistance.
   - **Max Pain Strike**: Strike price where option writers/institutions experience minimal loss at expiration.
   - **ATM Implied Volatility (IV)**: Live options implied volatility compared against India VIX regime.
3. **Technical Momentum Indicators**:
   - **RSI (14)**: Current momentum oscillator score.
   - **VWAP Alignment**: Distance from intraday Volume Weighted Average Price.
   - **EMA Stack**: Exponential Moving Average alignment (9 EMA > 21 EMA > 50 EMA).
4. **Directional BTST/STBT Verdict**:
   - Explicit algorithm recommendation: `CALL (CE) FAVORABLE`, `PUT (PE) FAVORABLE`, or `CASH / NO OVERNIGHT BIAS`.

---

## 3. GIFT NIFTY Macro Overnight Gate
- **Dual Session Coverage**:
  - Session 1: 6:30 AM – 3:40 PM IST (Day Session).
  - Session 2: 4:35 PM – 2:45 AM IST (International Evening Session).
- **Macro Gate Logic**:
  - When GIFT NIFTY drops >= 0.75% during European/US hours, individual stock P1 High Conviction setups are automatically capped to P2 Medium to safeguard trader capital from global macro gap-downs.
  - Automatically suppresses false breakout alerts during high-volatility global events.

---

## 4. Benchmark Weight Overrides & Multi-Index Correlation
- Displays real-time weighted contribution to Nifty 50:
  - **Financial Services (HDFCBANK, ICICIBANK, SBIN, AXISBANK)**: ~33.5%
  - **Information Technology (TCS, INFY, WIPRO, HCLTECH)**: ~14.2%
  - **Oil & Gas / Energy (RELIANCE, ONGC, NTPC)**: ~11.8%
  - **Automobiles & Consumer Goods (TATAMOTORS, MARUTI, ITC)**: ~10.5%
- Identifies intraday sector rotation and divergence between Nifty 50 and Bank Nifty.

---

## 5. Backend API Endpoints & Contracts
- `GET /api/indices`: Returns live multi-index snapshot with PCR, Max Pain, Trend Verdicts, and technical indicators.
- `GET /api/gift_nifty/live`: Returns live GIFT NIFTY quote, current trading session status, and macro gate state.
- `GET /api/option-chain/NIFTY`: Returns complete NIFTY 50 per-strike options chain.
- `GET /api/option-chain/BANKNIFTY`: Returns complete BANK NIFTY per-strike options chain.
