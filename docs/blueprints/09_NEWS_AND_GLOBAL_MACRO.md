# TRADEXO PAGE BLUEPRINT: STOCKS NEWS & GLOBAL MACRO (09)

## 1. Feature Overview & Architecture
The **News & Global Macroeconomic Intelligence Engine** (`/stocksNews` and `/globalNews`) provides AI-scored corporate news, earnings developments, and geopolitical macroeconomic data across the complete Indian financial landscape.

### Dual-Layer Architecture:
1. **Per-Stock Corporate News (`/stocksNews`)**: Serves company-specific regulatory filings, corporate quarterly results, block deals, and management interviews for all 230+ F&O stocks.
2. **Global Macroeconomic & Geopolitical Feed (`/globalNews`)**: Monitors central bank policies (RBI MPC, US Federal Reserve, ECB), crude oil Brent benchmarks, US 10-Year Treasury Yields, and global equity index futures (Dow, S&P 500, Nasdaq, Nikkei, FTSE).

---

## 2. API Quota & Zero-Cost Caching Architecture
- **CurrentsAPI & NewsAPI Integration**: Configured with smart budget-aware background caching (`data/stock_news_cache.json`).
- **Zero API Overdraft**: Frontend page views and client refreshes read 100% from local memory cache, consuming **zero external API credits** on repeated page views.
- **Scheduled Background Refresh**: An autonomous background worker refreshes high-conviction P1/P2 tickers during market hours every 15 minutes, preserving API monthly budgets.

---

## 3. News Feed UI & Sentiment Classifier
Each news card features rich institutional metadata:
- **Headline & Excerpt**: Clean typography with source attribution (Moneycontrol, Economic Times, Livemint, Bloomberg, Reuters).
- **Sentiment Badge**:
  - `STRONG_BULLISH` (Emerald): Positive earnings surprise, order win, management upgrade.
  - `MILD_BULLISH` (Light Green): General positive industry development.
  - `NEUTRAL` (Slate): Corporate announcements, AGM dates.
  - `BEARISH` (Rose): Earnings miss, promoter selling, regulatory scrutiny.
- **Sentiment Score (-1.00 to +1.00)**: Quantitative numerical score feeding directly into Pillar 5 (Fundamentals & News Quality Gate).
- **Time Elapsed**: Relative timestamp (e.g., `12m ago`, `1h ago`).
- **Direct External Link**: Clickable link opening full article in a new secure tab (`rel="noopener noreferrer"`).

---

## 4. Macroeconomic Impact on Overnight BTST Setups
- **High-Impact Macro Flag**: If a major interest rate decision, Union Budget announcement, or election outcome is scheduled overnight:
  - System flags `HIGH_MACRO_EVENT_RISK`.
  - Tightens overnight position sizing recommendation by 50%.
  - Widens stop-loss recommendations to prevent premature shakeouts from opening volatility spikes.

---

## 5. Backend API Endpoints & Contracts
- `GET /api/news`: Returns per-stock corporate news cache for all scanned F&O stocks.
- `GET /api/news/{symbol}`: Returns recent headlines and sentiment score for a specific ticker.
- `GET /api/news/global`: Returns live global macroeconomic and financial headlines.
