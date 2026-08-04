import yfinance as yf
import pandas as pd
import warnings
import time
from scoring_engine import evaluate_5_pillar_matrix
from nse_data_provider import get_per_stock_oi_data, get_per_stock_delivery_data
from fo_universe import get_canonical_fo_tickers

# Suppress warnings for cleaner terminal output
warnings.filterwarnings('ignore')

# 1. Canonical Whitelisted NSE F&O Tickers (Yahoo Finance format requires .NS for NSE)
fo_tickers = get_canonical_fo_tickers()

print("Initializing 5-Pillar Data Stream... Fetching Live Market Data & Nifty 50 Benchmark...")

# Download intraday data for tickers + Nifty 50 benchmark
tickers_to_fetch = fo_tickers + ["^NSEI"]
data = yf.download(tickers_to_fetch, period="1d", interval="5m", group_by="ticker", progress=False)

nifty_df = None
if "^NSEI" in data.columns.levels[0]:
    nifty_df = data["^NSEI"]

# Fetch per-stock NSE OI proxy + Delivery data
print("Fetching per-stock NSE OI & Delivery history (jugaad_data)...")
nse_cache = {}
for ticker in fo_tickers:
    clean_sym = ticker.replace(".NS", "")
    try:
        oi = get_per_stock_oi_data(clean_sym)
        delivery = get_per_stock_delivery_data(clean_sym)
        nse_cache[clean_sym] = {"oi_data": oi, "delivery_data": delivery}
    except Exception:
        nse_cache[clean_sym] = {"oi_data": None, "delivery_data": None}
    time.sleep(0.2)

flagged_signals = []

print("\n" + "="*70)
print(" 3:15 PM INSTITUTIONAL 5-PILLAR MATRIX SCANNER ")
print("="*70)

for ticker in fo_tickers:
    try:
        if ticker in data.columns.levels[0]:
            stock_df = data[ticker].dropna()
        else:
            continue

        clean_sym = ticker.replace(".NS", "")
        nse_stock = nse_cache.get(clean_sym, {})

        res = evaluate_5_pillar_matrix(
            symbol=ticker,
            df_stock=stock_df,
            df_nifty=nifty_df,
            oi_data=nse_stock.get("oi_data"),
            delivery_data=nse_stock.get("delivery_data"),
            oi_magnitude_mult=1.5
        )

        if res["signal"] != "NEUTRAL":
            flagged_signals.append(res)
            print(f"\n[+] {res['symbol']} -> {res['signal']} | {res['option_type']}")
            print(f"    Tier: {res['liquidity_tier']} | Confirmed: {res['confirmed_pillars_count']} pillars ({res['confirmed_pillars_weight']} weight / {res['required_pillars']} req)")
            print(f"    Pillars: {', '.join(res['confirmed_pillars'])}")
            print(f"    OI: {res['oi_magnitude']['data_status']} | actual={res['oi_magnitude']['actual_oi_pct']}% | avg10d={res['oi_magnitude']['avg_10d_oi_pct']}% | threshold={res['oi_magnitude']['threshold']}%")
            print(f"    Delivery T+1: {res['delivery_t1_validation']['data_status']} | pct={res['delivery_t1_validation'].get('delivery_pct')} | avg10d={res['delivery_t1_validation'].get('avg_10d_delivery_pct')}")
            print(f"    Expiry Discount: {res['expiry_discount_applied']} | Est. Gap: {res['predicted_gap_pct']}% | Confidence: {res['confidence_score']}%")

    except Exception as e:
        continue

print("\n" + "="*70)
if not flagged_signals:
    print("No stocks met the Liquidity-Tiered 5-Pillar Confirmation Threshold today.")
print("="*70 + "\n")