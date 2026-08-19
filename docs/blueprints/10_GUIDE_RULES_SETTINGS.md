# TRADEXO PAGE BLUEPRINT: GUIDE, RULES & SETTINGS (10)

## 1. Feature Overview & Architecture
The **Guide, Trading Rules & Platform Settings** workspace (`/guide` and `/rules` or `#rulesSection` / `#guideSection`) provides the operational rulebook, quantitative methodology documentation, CSV data exports, theme personalization, and platform orientation assets.

---

## 2. The 5-Pillar Quantitative Methodology Matrix
TRADEXO filters and ranks stocks using an institutional 5-pillar mathematical model:

```
+------------------------------------------------------------------------------------+
|                                TRADEXO 5-PILLAR MODEL                              |
+-------------------+--------------------+--------------------+----------------------+
| Pillar 1: 25%     | Pillar 2: 25%      | Pillar 3: 20%      | Pillar 4: 15% | 5:15%|
| Momentum & RSI    | Trend & Volatility | Volume Surge & Liq | Derivatives   | News |
+-------------------+--------------------+--------------------+---------------+------+
```

1. **Pillar 1: Momentum & Technical Oscillators (25% Weight)**:
   - RSI (14) momentum corridor: 58–72 for optimal BTST breakouts; < 38 for STBT breakdowns.
   - MACD histogram expansion and Stochastic RSI alignment.
2. **Pillar 2: Trend & Volatility Structure (25% Weight)**:
   - Price > VWAP and Price > 20 EMA > 50 EMA.
   - SuperTrend (10, 3) bullish alignment and Bollinger Band expansion.
3. **Pillar 3: Volume Surge & Liquidity (20% Weight)**:
   - Volume Surge Ratio: Current volume compared against the 20-day rolling moving average.
   - P1 High requires >= 2.0x volume surge.
4. **Pillar 4: Derivatives & Options Matrix (15% Weight)**:
   - Put-Call Ratio (PCR) > 1.15 for BTST; PCR < 0.85 for STBT.
   - Max Pain proximity and Open Interest (OI) buildup confirmation.
5. **Pillar 5: Fundamentals & News Quality Gates (15% Weight)**:
   - Trailing P/E and quarterly revenue growth.
   - Positive AI news sentiment score (> +0.35) and absence of negative regulatory halts.

---

## 3. Strict Indian Market Session Schedule & Closing Rules
- **09:00 – 09:15 AM**: Pre-Market Session (GIFT NIFTY reconciliation & gap open discovery).
- **09:15 – 09:17 AM**: Automated Trade Evaluation Window (Grading yesterday's locked picks).
- **09:17 AM – 03:14 PM**: Regular Continuous Trading Session (Live scanning & technical setups).
- **03:14 – 03:25 PM**: **The High-Conviction BTST Power Hour**:
  - Closing Sequence Aggression Veto active.
  - Final 10-minute order depth and institutional block deal reconciliation.
- **03:25 – 03:30 PM**: **Lock Window**:
  - Top 5 candidates algorithmically locked for overnight BTST/STBT.
  - Pick entries saved to immutable `signal_journal.db`.
- **03:30 PM – 09:00 AM (Next Day)**: Market Closed (System freezes last close prices; AI Sentinel runs maintenance & walk-forward calibration).

---

## 4. Theme & Appearance Engine
- **Institutional Light Theme ("Champagne Gold & Clean Slate")**:
  - Crisp white cards (`#ffffff`), slate borders (`#e2e8f0`), deep slate typography (`#0f172a`), and refined champagne gold / amber accents (`#d97706` / `#f59e0b`).
- **Dark Theme ("Obsidian Gold")**:
  - Deep space slate background (`#020617`), card surfaces (`#0f172a`), gold accents (`#fbbf24`).
- **Persistent Theme Storage**: Saves preference in `localStorage.getItem('tradexo_theme')`.

---

## 5. CSV Watchlist Export & Platform Orientation
- **CSV Data Exporter (`exportWatchlistCsv`)**:
  - Generates downloadable CSV with Rank, Symbol, Option Type, Predicted Gap %, Priority Level, Confidence Score, Signal, LTP, Day High/Low, VWAP, Volume Spike, and RSI.
- **Platform Orientation Video Reel (`#introModal`)**:
  - Embedded cinematic overview (`TRADXO_INTRO.mp4`) detailing navigation, 4-button action bar, and 1-second option chain workflows.
