# TRADEXO PAGE BLUEPRINT: LIVE 1-SECOND OPTION CHAIN (03)

## 1. Feature Overview & Architecture
The **Live 1-Second Option Chain** (`#optionChainModal` and `/api/option-chain/{symbol}`) delivers institutional-speed, zero-latency options matrix telemetry for all Indian benchmark indices and individual F&O equities.

### Key Architectural Tenets:
1. **Zero-Latency In-Memory Serving**: All requests are served from `fast_cache` / RAM (<2ms response time). The browser's 1-second polling loop never makes blocking calls to external broker APIs, completely eliminating rate-limiting risks.
2. **Deterministic Synthesizer Fallback**: If live market feeds are closed, on holiday, or unverified, a statistical Black-Scholes approximation engine synthesizes a live option chain around the asset's current LTP, allowing 24/7 continuous demo options trading.
3. **Seamless Jitter-Free UI**: Utilizes CSS `font-variant-numeric: tabular-nums` and sticky column/header positioning so numeric updates every second do not shift scroll positions or jitter table layouts.

---

## 2. Options Matrix Layout & Column Mapping
The interface renders a classic 9-column options matrix:

```
+------------------------------------+----------+------------------------------------+
|            CALLS (CE)              |  STRIKE  |             PUTS (PE)              |
+--------+----------+--------+-------+----------+-------+--------+----------+--------+
|   OI   | CHNG OI  | VOLUME |  LTP  |  PRICE   |  LTP  | VOLUME | CHNG OI  |   OI   |
+--------+----------+--------+-------+----------+-------+--------+----------+--------+
```

| Column | Position | Description | Interactive Behavior |
| :--- | :--- | :--- | :--- |
| **CE Open Interest (OI)** | Left (Col 1) | Total active call contracts | Tabular number formatting |
| **CE Change in OI** | Left (Col 2) | Intraday addition/reduction in Call OI | Green if positive, Red if negative |
| **CE Total Volume** | Left (Col 3) | Contracts traded today | Monospace numeric string |
| **CE LTP (₹)** | Left (Col 4) | Last Traded Premium for Call leg | **Clickable**: Stages instant Demo CE Order |
| **STRIKE PRICE** | Center (Col 5) | Exercise strike price | Highlights ATM strike in gold badge |
| **PE LTP (₹)** | Right (Col 6) | Last Traded Premium for Put leg | **Clickable**: Stages instant Demo PE Order |
| **PE Total Volume** | Right (Col 7) | Contracts traded today | Monospace numeric string |
| **PE Change in OI** | Right (Col 8) | Intraday addition/reduction in Put OI | Green if positive, Red if negative |
| **PE Open Interest (OI)** | Right (Col 9) | Total active put contracts | Tabular number formatting |

---

## 3. Highlighting & Visual Styling
- **ATM Strike Row (`.oc-atm-row`)**: Gold highlight (`#fffbeb` background, `#b45309` bold text, `#fde68a` border) with `ATM` badge.
- **In-The-Money (ITM) Shading**:
  - Call ITM (Strike < Underlying): Soft emerald gradient (`rgba(236, 253, 245, 0.45)`).
  - Put ITM (Strike > Underlying): Soft rose gradient (`rgba(255, 241, 242, 0.45)`).
- **Out-Of-The-Money (OTM) Shading**: Clean slate background (`#ffffff` / `#f8fafc`).

---

## 4. Header Bar Analytics & Controls
- **Symbol & Underlying Quote**: Displays symbol name with live underlying spot LTP.
- **Official Lot Size**: Dynamically populated (e.g., NIFTY: 25, BANKNIFTY: 15, FINNIFTY: 25, RELIANCE: 250, TCS: 175, INFY: 400).
- **PCR Ratio**: Total Put Open Interest / Total Call Open Interest.
- **Max Pain Level**: Calculated strike where total option holder payout is minimized.
- **Expiry Date Dropdown (`#ocExpirySelect`)**: Allows filtering by weekly and monthly expiration cycles.
- **Live Stream Indicator**: Animated pulsing green dot (`1-SEC LIVE`).

---

## 5. Direct Execution Integration
Clicking any **Call LTP** or **Put LTP** cell automatically launches the **Advanced Options Demo Trading Modal** pre-filled with:
- Contract Symbol (`SYMBOL STRIKE TYPE`, e.g., `RELIANCE 2980 CE`)
- Selected Strike Price
- Recommended Option Leg (`CE` or `PE`)
- Current Live Premium Quote
- Default 1 Lot with symbol's official lot size multiplier.
