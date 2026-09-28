import os
import re
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

INDEX_EXCLUSIONS = {'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'NIFTY50', 'BANKEX'}

def normalize_svg_content(content: bytes) -> bytes:
    """Ensure SVG has a viewBox attribute for perfect responsive scaling."""
    text = content.decode('utf-8', errors='ignore')
    if 'viewBox' not in text and 'viewbox' not in text:
        w_match = re.search(r'width=[\"\']([0-9\.]+)[\"\']', text)
        h_match = re.search(r'height=[\"\']([0-9\.]+)[\"\']', text)
        if w_match and h_match:
            w = w_match.group(1)
            h = h_match.group(1)
            text = re.sub(r'<svg\b', f'<svg viewBox="0 0 {w} {h}"', text, count=1)
        else:
            text = re.sub(r'<svg\b', '<svg viewBox="0 0 18 18"', text, count=1)
    return text.encode('utf-8')

def main():
    print("=== TRADEXO STOCK LOGO ACQUISITION PIPELINE ===")
    
    output_dir = os.path.join(os.path.dirname(__file__), "..", "static", "logos")
    os.makedirs(output_dir, exist_ok=True)
    print(f"Target directory: {os.path.abspath(output_dir)}")

    # 1. Gather all unique stock symbols in TRADEXO
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    symbols = set()
    source_files = [
        'last_market_scan.json',
        'stock_news_cache.json',
        'fundamentals_cache.json',
        'trade_history.json',
        'block_deals_cache.json'
    ]
    for fn in source_files:
        fp = os.path.join(data_dir, fn)
        if not os.path.exists(fp):
            continue
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                d = json.load(f)
            if isinstance(d, dict):
                if 'stocks' in d:
                    symbols.update(s['symbol'] for s in d['stocks'] if 'symbol' in s)
                if 'cache' in d:
                    symbols.update(d['cache'].keys())
                if 'trades' in d:
                    symbols.update(t.get('symbol') for t in d['trades'] if 'symbol' in t)
                if 'deals' in d:
                    symbols.update(deal.get('symbol') for deal in d['deals'] if 'symbol' in deal)
        except Exception as e:
            print(f"Error reading {fn}: {e}")

    # Clean symbols
    clean_symbols = sorted(list(set([
        s.replace('.NS', '').replace('.BO', '').upper().strip()
        for s in symbols
        if s and len(s) < 20 and s not in INDEX_EXCLUSIONS
    ])))
    print(f"Total unique symbols to acquire: {len(clean_symbols)}")

    # 2. Fetch remote logos metadata catalog
    catalog_url = "https://raw.githubusercontent.com/dharunashokkumar/indian-listed-company-logos/main/data/logos.json"
    print(f"Fetching logos metadata catalog from {catalog_url} ...")
    req = urllib.request.Request(catalog_url, headers={'User-Agent': 'TradexoBot/1.0'})
    with urllib.request.urlopen(req) as resp:
        catalog = json.loads(resp.read().decode('utf-8'))
    
    # Map ticker -> relative file
    nse_catalog = {}
    for entry in catalog.get('logos', []):
        t = entry.get('ticker', '').upper().strip()
        f = entry.get('file', '')
        if t and f:
            nse_catalog[t] = f
            norm = t.replace('_', '-').replace('&', '')
            nse_catalog[norm] = f

    aliases = {
        'BAJAJ-AUTO': 'BAJAJ_AUTO',
        'NAM-INDIA': 'NAM_INDIA',
        'M&M': 'M_M',
        'M&MFIN': 'M_MFIN',
        'L&TFH': 'L_TFH',
        'MCDOWELL-N': 'MCDOWELL_N',
        'LIQUIDBEES': 'NAM_INDIA',
        'PREMIER': 'PREMIERENE'
    }

    special_sources = {
        'ANGELONE': 'https://upload.wikimedia.org/wikipedia/commons/6/6d/Angel_One_Logo.svg'
    }

    download_tasks = []
    base_raw_url = "https://raw.githubusercontent.com/dharunashokkumar/indian-listed-company-logos/main/"

    for sym in clean_symbols:
        dest_path = os.path.join(output_dir, f"{sym}.svg")
        
        # Check special sources first
        if sym in special_sources:
            download_tasks.append((sym, dest_path, special_sources[sym]))
            continue

        target_key = aliases.get(sym, sym)
        if target_key in nse_catalog:
            rel_file = nse_catalog[target_key]
            remote_url = base_raw_url + rel_file
            download_tasks.append((sym, dest_path, remote_url))
        elif sym.replace('-', '_') in nse_catalog:
            rel_file = nse_catalog[sym.replace('-', '_')]
            remote_url = base_raw_url + rel_file
            download_tasks.append((sym, dest_path, remote_url))
        elif sym.replace('_', '-') in nse_catalog:
            rel_file = nse_catalog[sym.replace('_', '-')]
            remote_url = base_raw_url + rel_file
            download_tasks.append((sym, dest_path, remote_url))
        else:
            print(f"Warning: No catalog entry found for {sym}")

    print(f"Queued {len(download_tasks)} logos for parallel download.")

    # 3. Concurrent Download
    def download_one(task):
        sym, dest, url = task
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read()
            if b'<svg' in content.lower():
                normalized = normalize_svg_content(content)
                with open(dest, 'wb') as f:
                    f.write(normalized)
                return sym, True, len(normalized), None
            else:
                return sym, False, 0, "Not an SVG"
        except Exception as e:
            return sym, False, 0, str(e)

    success_count = 0
    fail_count = 0
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(download_one, t): t[0] for t in download_tasks}
        for future in as_completed(futures):
            sym, success, size, err = future.result()
            if success:
                success_count += 1
            else:
                fail_count += 1
                print(f"Failed to download {sym}: {err}")

    print(f"\nDownload summary: {success_count} succeeded, {fail_count} failed.")
    
    # 4. Generate manifest
    local_files = [f for f in os.listdir(output_dir) if f.endswith('.svg')]
    manifest = {
        "count": len(local_files),
        "available_symbols": sorted([f.replace('.svg', '') for f in local_files])
    }
    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)
    print(f"Updated manifest at {manifest_path} with {len(local_files)} verified stock logos.")

if __name__ == '__main__':
    main()
