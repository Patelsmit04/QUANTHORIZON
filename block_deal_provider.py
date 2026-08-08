"""
INSTITUTIONAL FLOW PROVIDER — NSE Bulk & Block Deal Scraper
==============================================================================
Feeds Pillar 6: Institutional Flow (see scoring_engine.py) from NSE's bulk and block deal
data. The two are regulatorily distinct and are fetched/labelled separately (deal_type: "bulk"
or "block"), then aggregated together per symbol:

- BULK deal: any trade(s) in a stock during NORMAL market hours that together exceed 0.5% of
  the company's total shares — happens inside the regular order book, so it's a real trade
  print the moment the threshold is crossed.
- BLOCK deal: a large trade (SEBI minimum currently Rs 25 crore, per SEBI's Oct 8, 2025
  circular effective Dec 7, 2025 — verify against the current circular if this file is being
  revisited long after that, since the threshold has been revised before) executed through a
  dedicated negotiation window, within a +/-3% band around a reference price. Confirmed against
  NSE's circular/FAQ (Aug 2026 research): morning window 8:45-9:00 AM IST (reference = prior
  close), afternoon window 2:05-2:20 PM IST (reference = 1:45-2:00 PM 15-min VWAP). A block deal
  does not exist until its window closes — there is nothing to scrape before 2:20 PM for the
  afternoon session.

TWO DATA SOURCES, DELIBERATELY KEPT SEPARATE (see reconciliation below):
1. LIVE SNAPSHOT — nseindia.com's live large-deal API (the same endpoint nsepython/nselib wrap:
   /api/snapshot-capital-market-largedeal?bandtype=bulk_deals|block_deals). jugaad_data (this
   project's usual NSE library, chosen elsewhere in the codebase because it avoids Cloudflare
   403s — see nse_data_provider.py) does not wrap this endpoint at all, so this module reuses
   jugaad_data's NSELive class purely for its already-working session/cookie bootstrap and
   extends its route table with this one extra route, rather than hand-rolling a second
   Cloudflare-safe session from scratch.
   FIELD-NAME CAVEAT (updated after a live smoke test, Aug 2026): the live JSON uses "watp"
   (Weighted Average Trade Price) and "qty", not the archive's "Trade Price / Wght. Avg. Price"
   wording — both are now in _PRICE_KEYS. _extract_deal_rows()/_parse_deal_records() are written
   defensively either way (case/punctuation-insensitive key matching across multiple plausible
   field-name candidates, skip-and-log-once on an unrecognized shape) so a schema drift is
   self-diagnosing rather than silently mis-parsed.
   BANDTYPE CAVEAT (same smoke test): querying with bandtype=bulk_deals and bandtype=block_deals
   appears to return overlapping/duplicate rows off-market (buy/sell counts came back exactly
   double the EOD archive's, and deal_types showed both "block" and "bulk" for symbols the
   archive confirmed had only bulk deals) — the bandtype param's real filtering semantics aren't
   documented anywhere public. _dedupe_records() collapses exact symbol/side/value duplicates
   defensively; re-verify this during live market hours, since off-market behavior may differ.
2. EOD ARCHIVE — nsearchives.nseindia.com's official consolidated bulk.csv/block.csv (jugaad_data
   already wraps bulk.csv via NSEArchives; block.csv is added the same way here). This is the
   reconciliation ground truth, and the only source ever used for backtesting (walk_forward_
   validator.py) — never the live snapshot, to keep backtest results free of live-parsing noise.
   NOTE: this archive endpoint only ever serves the LATEST published trading day's file — there
   is no historical-date parameter for these two routes.

RECONCILIATION & SHADOW MODE: the live snapshot is provisional/unverified next to the official
EOD file. run_eod_reconciliation() diffs whatever live checkpoint was captured earlier today
against the EOD archive once it publishes, logging discrepancies rather than trusting either
source blindly — see data/institutional_flow_reconciliation.json. Until that reconciliation has
been observed clean for a couple of weeks, INSTITUTIONAL_FLOW_SHADOW_MODE (default: on) keeps
Pillar 6 computed and visible in scan output but excluded from confirmed_pillars_weight / the
live verdict — see scoring_engine.py's institutional_flow_shadow_mode param.

SCHEDULING: maybe_run_institutional_flow_checkpoints() is meant to be called unconditionally on
every scheduler tick (same idiom as news_provider.maybe_refresh_universe_news) — a no-op outside
its own trigger windows, idempotent per day per checkpoint via a disk-backed flag so a process
restart never re-fires a checkpoint that already ran today, and a failed fetch is NOT marked
done so it retries on a later tick that same day instead of silently giving up on it.
"""

import os
import csv
import io
import re
import time
import logging
from datetime import datetime, date, timezone, timedelta
from typing import Dict, Any, List, Optional

from json_utils import atomic_write_json, read_json, json_file_lock
from net_utils import call_with_retry
from env_utils import DATA_DIR

logger = logging.getLogger("BlockDealProvider")

IST = timezone(timedelta(hours=5, minutes=30))


def _ist_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(IST)


# =========================================================================
# CONFIG (env-overridable — see .env.example)
# =========================================================================
def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


MIN_VALUE_CR = _env_float("INSTITUTIONAL_FLOW_MIN_VALUE_CR", 25.0)       # SEBI's current block-deal floor
TIER_MODERATE_CR = _env_float("INSTITUTIONAL_FLOW_MODERATE_CR", 50.0)
TIER_STRONG_CR = _env_float("INSTITUTIONAL_FLOW_STRONG_CR", 150.0)

# 10 min of margin past the confirmed 2:20 PM afternoon block-window close, and a final check
# before the 3:30 PM lock. See run_eod_reconciliation() — if the reconciliation log shows this
# margin is too thin in practice, that's what tells you, not a guess made here.
LIVE_TRIGGER_HOUR = _env_int("INSTITUTIONAL_FLOW_LIVE_TRIGGER_HOUR", 14)
LIVE_TRIGGER_MINUTE = _env_int("INSTITUTIONAL_FLOW_LIVE_TRIGGER_MINUTE", 30)
FINAL_CHECK_HOUR = _env_int("INSTITUTIONAL_FLOW_FINAL_CHECK_HOUR", 15)
FINAL_CHECK_MINUTE = _env_int("INSTITUTIONAL_FLOW_FINAL_CHECK_MINUTE", 15)
# NSE's fully consolidated EOD report is "typically evening, sometimes as late as ~7 PM" —
# 19:30 leaves margin past that before the reconciliation checkpoint gives up for the tick.
RECONCILE_HOUR = _env_int("INSTITUTIONAL_FLOW_RECONCILE_HOUR", 19)
RECONCILE_MINUTE = _env_int("INSTITUTIONAL_FLOW_RECONCILE_MINUTE", 30)

SHADOW_MODE = _env_bool("INSTITUTIONAL_FLOW_SHADOW_MODE", True)

DAILY_FLOW_FILE = os.path.join(DATA_DIR, "institutional_flow_daily.json")
RECONCILIATION_FILE = os.path.join(DATA_DIR, "institutional_flow_reconciliation.json")
CHECKPOINTS_META_FILE = os.path.join(DATA_DIR, "institutional_flow_checkpoints.json")
MAX_RECONCILIATION_HISTORY = 90
DAILY_STORE_RETENTION_DAYS = 5  # same-day signal only — no need to keep a long rolling history


# =========================================================================
# SESSION CLIENTS — reuse jugaad_data's proven Cloudflare-safe session bootstrap, only
# extending its route tables (see module docstring for why these two routes aren't already
# wrapped by jugaad_data itself).
# =========================================================================
_JUGAAD_AVAILABLE = False
try:
    from jugaad_data.nse import NSEArchives, NSELive
    _JUGAAD_AVAILABLE = True
except ImportError:
    logger.warning("jugaad_data not installed. Run: pip install jugaad-data")

# Module-level singletons: cheap to rebuild, and this module is only ever driven from the
# single background scheduler thread on a handful of daily checkpoints (not per HTTP request),
# so the thread-safety caveats of sharing one requests.Session are not a practical concern here.
_archives_client = None
_live_client = None


def _get_archives_client():
    global _archives_client
    if _archives_client is None:
        client = NSEArchives()
        client.timeout = 15  # NSEArchives' own hardcoded 4s default is tight for a cold connection
        client._routes["block_deals"] = "/content/equities/block.csv"  # jugaad_data only wires up bulk.csv
        _archives_client = client
    return _archives_client


def _reset_archives_client():
    global _archives_client
    _archives_client = None


def _get_live_client():
    global _live_client
    if _live_client is None:
        client = NSELive()
        client._routes["large_deals"] = "/snapshot-capital-market-largedeal"
        # jugaad_data's own NSELive already wires this route as "live_index" — reusing that
        # name instead of re-adding it, confirmed live (Aug 2026): returns each constituent's
        # ffmc (free-float market cap), the same basis NSE's own free-float weighting uses, so
        # index weight can be derived directly (see _get_index_constituent_weights()) without a
        # separate weight-table source that would go stale between rebalances.
        _live_client = client
    return _live_client


def _reset_live_client():
    global _live_client
    _live_client = None


# =========================================================================
# RAW FETCH — retried + externally timed-out via net_utils, session dropped on failure so the
# next call re-bootstraps fresh cookies instead of retrying against whatever broke it.
# =========================================================================
def _fetch_live_raw(bandtype: str) -> Optional[Any]:
    def _do():
        client = _get_live_client()
        return client.get("large_deals", {"bandtype": bandtype})

    result = call_with_retry(_do, label=f"NSE live large deals [{bandtype}]")
    if result is None:
        _reset_live_client()
    return result


def _fetch_archive_raw(route: str) -> Optional[str]:
    def _do():
        client = _get_archives_client()
        return client.get(route).text

    result = call_with_retry(_do, label=f"NSE EOD archive [{route}]")
    if result is None:
        _reset_archives_client()
    return result


# =========================================================================
# DEFENSIVE PARSING — see module docstring's FIELD-NAME CAVEAT.
# =========================================================================
def _normalize_key(k: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(k).lower())


def _pick(record: Dict[str, Any], candidates: List[str]) -> Optional[Any]:
    normalized_candidates = [_normalize_key(c) for c in candidates]
    normalized_map = {_normalize_key(k): v for k, v in record.items()}

    for cand in normalized_candidates:
        if cand in normalized_map:
            return normalized_map[cand]

    # Fallback: substring containment. NSE's own header wording has already been observed to
    # drift (e.g. "Trade Price / Wght. Avg. Price" in production vs. the "Wtd." spelling
    # documented elsewhere) — this catches future re-wording without needing another live
    # smoke test to notice it broke.
    for norm_key, v in normalized_map.items():
        for cand in normalized_candidates:
            if cand and (cand in norm_key or norm_key in cand):
                return v
    return None


_SYMBOL_KEYS = ["symbol"]
_SIDE_KEYS = ["buysell", "buysellindicator", "buysellind"]
_DATE_KEYS = ["date"]
_QTY_KEYS = ["quantitytraded", "quantity", "qty", "qtytraded"]
# NSE's actual archive header (confirmed via live fetch, Aug 2026): "Trade Price / Wght. Avg.
# Price" — normalizes to "tradepricewghtavgprice". The live snapshot API instead uses "watp"
# (Weighted Average Trade Price, confirmed via live fetch the same day) — both endpoints'
# real field names are kept alongside generic fallbacks in case of future drift.
_PRICE_KEYS = ["watp", "tradepricewghtavgprice", "tradepricewtdavgprice", "tradeprice", "wghtavgprice", "wtdavgprice", "price", "wavgprice", "avgprice"]
_VALUE_KEYS = ["tradevalue", "value", "wtval", "valueincr", "valuecr"]

_missing_field_warned: set = set()  # warn once per (deal_type, reason), not once per row


def _extract_deal_rows(raw: Any) -> Optional[List[Dict[str, Any]]]:
    """Live snapshot JSON shape is unverified (see module docstring) — try the plausible
    shapes, fall back to 'first list-of-dicts found anywhere in the payload', else give up
    loudly rather than guess wrong silently."""
    if isinstance(raw, list):
        return raw if all(isinstance(r, dict) for r in raw) else None
    if isinstance(raw, dict):
        for key in ("data", "BULK_DEALS_DATA", "BLOCK_DEALS_DATA", "bulk_deals_data", "block_deals_data", "largedeals", "value"):
            val = raw.get(key)
            if isinstance(val, list):
                return val
        for val in raw.values():
            if isinstance(val, list) and val and isinstance(val[0], dict):
                return val
    return None


def _parse_csv_text(text: str) -> List[Dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    return [row for row in reader if row]


def _parse_deal_records(rows: List[Dict[str, Any]], deal_type: str) -> List[Dict[str, Any]]:
    """Normalizes raw archive-CSV or live-JSON rows into {symbol, side, value_cr, deal_type}.
    Rows missing a required field are skipped (not fabricated) and logged once per distinct
    missing-field reason, so a real NSE schema change shows up as one clear warning instead of
    either a crash or silent data loss."""
    out = []
    for row in rows:
        symbol = _pick(row, _SYMBOL_KEYS)
        side_raw = _pick(row, _SIDE_KEYS)

        if not symbol or side_raw is None:
            warn_key = (deal_type, "symbol_or_side")
            if warn_key not in _missing_field_warned:
                _missing_field_warned.add(warn_key)
                logger.warning(f"[InstitutionalFlow] {deal_type}: row missing symbol/side field — actual keys seen: {list(row.keys())}")
            continue

        side_str = str(side_raw).strip().upper()
        if side_str in ("B", "BUY"):
            side = "BUY"
        elif side_str in ("S", "SELL"):
            side = "SELL"
        else:
            continue

        value_raw = _pick(row, _VALUE_KEYS)
        value_cr = None
        if value_raw is not None:
            try:
                value_cr = float(str(value_raw).replace(",", "")) / 1e7
            except (TypeError, ValueError):
                value_cr = None

        if value_cr is None:
            qty_raw = _pick(row, _QTY_KEYS)
            price_raw = _pick(row, _PRICE_KEYS)
            if qty_raw is None or price_raw is None:
                warn_key = (deal_type, "qty_or_price")
                if warn_key not in _missing_field_warned:
                    _missing_field_warned.add(warn_key)
                    logger.warning(f"[InstitutionalFlow] {deal_type}: row missing qty/price/value field — actual keys seen: {list(row.keys())}")
                continue
            try:
                qty = float(str(qty_raw).replace(",", ""))
                price = float(str(price_raw).replace(",", ""))
                value_cr = (qty * price) / 1e7
            except (TypeError, ValueError):
                continue

        date_raw = _pick(row, _DATE_KEYS)

        out.append({
            "symbol": str(symbol).strip().upper().replace(".NS", ""),
            "side": side,
            "value_cr": round(value_cr, 4),
            "deal_type": deal_type,
            # NSE's bulk/block feeds report a trading DAY, not an intraday time, for each deal —
            # this is that day-level field as NSE reports it, kept as-is (not reformatted, so no
            # date-parsing assumption is baked in). Falls back to today when a row omits it.
            "deal_date": str(date_raw).strip() if date_raw else date.today().isoformat(),
        })
    return out


def _dedupe_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapses exact-duplicate rows (same symbol/side/value) seen across a merged multi-
    bandtype fetch. A live smoke test (Aug 2026) showed NSE's live large-deal snapshot
    returning what appears to be the same rows under bandtype=bulk_deals AND
    bandtype=block_deals — buy/sell counts came back exactly double the EOD archive's, and
    deal_types showed both "block" and "bulk" even for symbols the archive confirmed had only
    bulk deals that day. The bandtype param's real filtering semantics aren't documented (see
    module docstring), so this dedupes defensively rather than trusting it partitions cleanly.
    The EOD archive path (separate bulk.csv/block.csv URLs, no observed overlap) is untouched."""
    seen = set()
    deduped = []
    for rec in records:
        key = (rec["symbol"], rec["side"], rec["value_cr"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(rec)
    return deduped


def _classify_tier(value_cr: float) -> str:
    if value_cr >= TIER_STRONG_CR:
        return "STRONG"
    if value_cr >= TIER_MODERATE_CR:
        return "MODERATE"
    if value_cr >= MIN_VALUE_CR:
        return "WEAK"
    return "BELOW_THRESHOLD"


def aggregate_symbol_flows(records: List[Dict[str, Any]], as_of: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Aggregates same-day, same-symbol deals into net buy/sell value + tier. Only symbols with
    at least one qualifying (>= MIN_VALUE_CR) deal are included — a single sub-threshold deal
    from a smaller player shouldn't surface as an institutional-flow entry at all."""
    out: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        if rec["value_cr"] < MIN_VALUE_CR:
            continue
        sym = rec["symbol"]
        bucket = out.setdefault(sym, {
            "symbol": sym, "buy_value_cr": 0.0, "sell_value_cr": 0.0,
            "buy_count": 0, "sell_count": 0, "deal_types": set(),
        })
        if rec["side"] == "BUY":
            bucket["buy_value_cr"] += rec["value_cr"]
            bucket["buy_count"] += 1
        else:
            bucket["sell_value_cr"] += rec["value_cr"]
            bucket["sell_count"] += 1
        bucket["deal_types"].add(rec["deal_type"])

    resolved_as_of = as_of or _ist_now().isoformat()
    for bucket in out.values():
        net = round(bucket["buy_value_cr"] - bucket["sell_value_cr"], 2)
        dominant_side = "BUY" if net > 0 else ("SELL" if net < 0 else "NONE")
        bucket["buy_value_cr"] = round(bucket["buy_value_cr"], 2)
        bucket["sell_value_cr"] = round(bucket["sell_value_cr"], 2)
        bucket["net_value_cr"] = net
        bucket["dominant_side"] = dominant_side
        bucket["tier"] = _classify_tier(abs(net))
        bucket["deal_types"] = sorted(bucket["deal_types"])
        bucket["as_of"] = resolved_as_of
    return out


# =========================================================================
# HIGH-LEVEL FETCHERS
# =========================================================================
def _gather_live_records() -> Optional[List[Dict[str, Any]]]:
    """Deduped, parsed individual deal records (not yet filtered to >= MIN_VALUE_CR, not yet
    aggregated) — shared by fetch_live_large_deals() (aggregate-only, unchanged public
    behavior) and the checkpoint runner, which also needs the raw per-deal rows for the deals
    panel / scanner-row expand breakdown (see get_deals_for_day()). None only if BOTH bandtypes
    failed to fetch."""
    if not _JUGAAD_AVAILABLE:
        logger.warning("jugaad_data not available — cannot fetch institutional flow data.")
        return None

    all_records: List[Dict[str, Any]] = []
    any_success = False
    for bandtype, deal_type in [("bulk_deals", "bulk"), ("block_deals", "block")]:
        raw = _fetch_live_raw(bandtype)
        if raw is None:
            logger.warning(f"[InstitutionalFlow] Live snapshot fetch failed for {bandtype}.")
            continue
        rows = _extract_deal_rows(raw)
        if rows is None:
            shape = list(raw.keys()) if isinstance(raw, dict) else type(raw).__name__
            logger.warning(f"[InstitutionalFlow] Unexpected live snapshot shape for {bandtype}: {shape}")
            continue
        any_success = True
        all_records.extend(_parse_deal_records(rows, deal_type))

    if not any_success:
        return None
    return _dedupe_records(all_records)


def fetch_live_large_deals() -> Optional[Dict[str, Dict[str, Any]]]:
    """Live intraday snapshot (bulk + block combined). Call only after the confirmed 2:20 PM
    afternoon block-deal window closes — see LIVE_TRIGGER_HOUR/MINUTE. Returns None only if
    BOTH bandtypes failed to fetch (never a partial result silently passed off as complete —
    a partial fetch, e.g. bulk succeeded but block failed, still returns what it has, since
    that's real data for the bandtype that worked)."""
    records = _gather_live_records()
    if records is None:
        return None
    return aggregate_symbol_flows(records)


def _gather_archive_records() -> Optional[List[Dict[str, Any]]]:
    """Parsed individual deal records from the official EOD bulk.csv + block.csv — shared by
    fetch_eod_archive_deals() and run_eod_reconciliation() (which also persists the raw rows
    for the deals panel). None only if BOTH files failed to fetch."""
    if not _JUGAAD_AVAILABLE:
        logger.warning("jugaad_data not available — cannot fetch institutional flow archive data.")
        return None

    all_records: List[Dict[str, Any]] = []
    any_success = False
    for route, deal_type in [("bulk_deals", "bulk"), ("block_deals", "block")]:
        raw_text = _fetch_archive_raw(route)
        if raw_text is None:
            logger.warning(f"[InstitutionalFlow] EOD archive fetch failed for {route}.")
            continue
        rows = _parse_csv_text(raw_text)
        any_success = True
        all_records.extend(_parse_deal_records(rows, deal_type))

    if not any_success:
        return None
    return all_records


def fetch_eod_archive_deals() -> Optional[Dict[str, Dict[str, Any]]]:
    """Official end-of-day consolidated bulk.csv + block.csv — the reconciliation ground truth
    and the only source ever used for backtesting. Only reflects the latest published trading
    day (no historical-date parameter on these archive routes)."""
    records = _gather_archive_records()
    if records is None:
        return None
    return aggregate_symbol_flows(records)


def _qualifying_deals(records: List[Dict[str, Any]], as_of: str) -> List[Dict[str, Any]]:
    """Individual deal rows clearing MIN_VALUE_CR (same threshold aggregate_symbol_flows
    applies), sorted by value descending — the per-deal detail an aggregate bucket alone can't
    show. `as_of` is when THIS checkpoint captured the data (data freshness); each deal also
    carries its own NSE-reported `deal_date` from _parse_deal_records (which trading day)."""
    qualifying = [dict(r, as_of=as_of) for r in records if r["value_cr"] >= MIN_VALUE_CR]
    qualifying.sort(key=lambda r: r["value_cr"], reverse=True)
    return qualifying


# =========================================================================
# PERSISTENCE — one entry per day, one sub-entry per checkpoint ("live_trigger",
# "final_check", "eod_archive"), so get_institutional_flow_data() and run_eod_reconciliation()
# can both look back at exactly what was captured and when.
# =========================================================================
def _load_daily_store() -> Dict[str, Any]:
    return read_json(DAILY_FLOW_FILE, default={})


def _save_daily_store(store: Dict[str, Any]):
    atomic_write_json(DAILY_FLOW_FILE, store)


def _persist_snapshot(
    today_str: str,
    checkpoint: str,
    aggregated: Dict[str, Dict[str, Any]],
    deals: Optional[List[Dict[str, Any]]] = None,
):
    with json_file_lock(DAILY_FLOW_FILE):
        store = _load_daily_store()
        day_entry = store.get(today_str, {})
        day_entry[checkpoint] = aggregated
        day_entry["last_checkpoint"] = checkpoint
        day_entry["last_updated"] = _ist_now().isoformat()
        if deals is not None:
            deals_by_checkpoint = day_entry.get("deals_by_checkpoint", {})
            deals_by_checkpoint[checkpoint] = deals
            day_entry["deals_by_checkpoint"] = deals_by_checkpoint
        store[today_str] = day_entry

        for old_date in list(store.keys()):
            if old_date == today_str:
                continue
            try:
                age = (date.today() - date.fromisoformat(old_date)).days
                if age > DAILY_STORE_RETENTION_DAYS:
                    del store[old_date]
            except ValueError:
                del store[old_date]

        _save_daily_store(store)


def get_institutional_flow_data(symbol: str, checkpoint: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fast local lookup for scoring_engine.py — never triggers a live fetch itself; that only
    happens from maybe_run_institutional_flow_checkpoints() on the scheduler thread. Returns
    None if no checkpoint has captured data for this symbol yet today (FAIL LOUD — a prior day's
    flow is never served as if it were today's signal)."""
    clean_sym = symbol.replace(".NS", "").upper()
    today_str = date.today().isoformat()
    store = _load_daily_store()
    day_entry = store.get(today_str)
    if not day_entry:
        return None

    use_checkpoint = checkpoint or day_entry.get("last_checkpoint")
    if not use_checkpoint:
        return None
    snapshot = day_entry.get(use_checkpoint) or {}
    return snapshot.get(clean_sym)


def get_deals_for_day(
    checkpoint: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Individual qualifying deals (>= MIN_VALUE_CR) captured today, sorted by value_cr
    descending — backs the deals panel and the scanner-row expand breakdown. Fast local lookup
    only, same convention as get_institutional_flow_data() (never triggers a live fetch).
    Returns [] when nothing has been captured yet today — an empty list is a normal, valid
    state (no qualifying deals, or not fetched yet) — see get_daily_flow_meta() to tell those
    two cases apart for a freshness indicator."""
    today_str = date.today().isoformat()
    store = _load_daily_store()
    day_entry = store.get(today_str)
    if not day_entry:
        return []

    use_checkpoint = checkpoint or day_entry.get("last_checkpoint")
    if not use_checkpoint:
        return []

    deals = list((day_entry.get("deals_by_checkpoint") or {}).get(use_checkpoint, []))
    if symbol:
        clean_sym = symbol.replace(".NS", "").upper()
        deals = [d for d in deals if d.get("symbol") == clean_sym]

    deals.sort(key=lambda d: d.get("value_cr", 0), reverse=True)
    return deals[:limit] if limit else deals


def get_daily_flow_meta() -> Dict[str, Any]:
    """Freshness metadata for today so far — which checkpoints have actually run, and when.
    Backs the deals-panel freshness indicator ('Live snapshot as of HH:MM — reconciled at... /
    not yet reconciled'), combined with get_reconciliation_history(limit=1) for the
    reconciliation status specifically."""
    today_str = date.today().isoformat()
    store = _load_daily_store()
    day_entry = store.get(today_str, {})
    return {
        "date": today_str,
        "last_checkpoint": day_entry.get("last_checkpoint"),
        "last_updated": day_entry.get("last_updated"),
        "checkpoints_captured": [c for c in ("live_trigger", "final_check", "eod_archive") if c in day_entry],
    }


def get_aggregated_flow_for_today(checkpoint: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Today's per-symbol aggregated flow for one checkpoint (or the most recent one) — the
    same dict get_institutional_flow_data() looks a single symbol up in, exposed here so a
    caller (app.py's scheduler) can scan every symbol at once right after a checkpoint runs,
    to decide what's newly worth a notification (see get_newly_notifiable_flows())."""
    today_str = date.today().isoformat()
    store = _load_daily_store()
    day_entry = store.get(today_str, {})
    use_checkpoint = checkpoint or day_entry.get("last_checkpoint")
    if not use_checkpoint:
        return {}
    return day_entry.get(use_checkpoint) or {}


# =========================================================================
# NOTIFICATIONS — this module stays notification-agnostic (no log_notification/ws_broadcast
# dependency here, matching every other provider) — it only tracks which symbols/indices have
# ALREADY been notified about today, so app.py's scheduler (which owns the other 3 notification
# call sites) can ask "what's newly worth telling the user about" without re-alerting on every
# later checkpoint that still sees the same flow.
# =========================================================================
NOTIFIED_FLOWS_FILE = os.path.join(DATA_DIR, "institutional_flow_notified.json")
# WEAK-tier deals don't notify — "meaningful", not the bare regulatory floor (see module docstring).
NOTIFY_MIN_TIER = "MODERATE"
_TIER_RANK = {"BELOW_THRESHOLD": 0, "WEAK": 1, "MODERATE": 2, "STRONG": 3}


def _load_notified_today() -> set:
    today_str = date.today().isoformat()
    notified = read_json(NOTIFIED_FLOWS_FILE, default={})
    return set(notified.get(today_str, []))


def _mark_notified(keys: List[str]):
    if not keys:
        return
    today_str = date.today().isoformat()
    with json_file_lock(NOTIFIED_FLOWS_FILE):
        notified = read_json(NOTIFIED_FLOWS_FILE, default={})
        already = set(notified.get(today_str, []))
        already.update(keys)
        # Prune older days so this file doesn't grow forever — same-day dedup is all it's for.
        notified = {today_str: sorted(already)}
        atomic_write_json(NOTIFIED_FLOWS_FILE, notified)


def get_newly_notifiable_flows(aggregated: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Symbols in `aggregated` at >= NOTIFY_MIN_TIER that haven't been notified about yet
    today. Marks them notified as a side effect — once returned, a symbol won't be returned
    again today even if a later checkpoint sees it at the same or a higher tier. Call right
    after a checkpoint captures fresh data (see get_aggregated_flow_for_today())."""
    already = _load_notified_today()
    newly = []
    new_keys = []
    for sym, flow in aggregated.items():
        if _TIER_RANK.get(flow.get("tier"), 0) < _TIER_RANK[NOTIFY_MIN_TIER]:
            continue
        key = f"STOCK:{sym}"
        if key in already:
            continue
        newly.append(flow)
        new_keys.append(key)
    _mark_notified(new_keys)
    return newly


def get_newly_notifiable_index_flow(index_flow: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Same idea as get_newly_notifiable_flows() but for one index's aggregate (BULLISH/
    BEARISH only — NEUTRAL never notifies). Called once per index per scoring pass from
    app.py, right after compute_index_institutional_flow()."""
    if not index_flow or index_flow.get("status") != "OK":
        return None
    if index_flow.get("verdict") not in ("BULLISH", "BEARISH"):
        return None
    key = f"INDEX:{index_flow.get('index_name')}"
    if key in _load_notified_today():
        return None
    _mark_notified([key])
    return index_flow


# =========================================================================
# RECONCILIATION — live snapshot vs. official EOD archive, logged (not silently trusted).
# =========================================================================
def _append_reconciliation_record(entry: Dict[str, Any]):
    with json_file_lock(RECONCILIATION_FILE):
        history = read_json(RECONCILIATION_FILE, default=[])
        history.append(entry)
        history = history[-MAX_RECONCILIATION_HISTORY:]
        atomic_write_json(RECONCILIATION_FILE, history)


def get_reconciliation_history(limit: int = 30) -> List[Dict[str, Any]]:
    history = read_json(RECONCILIATION_FILE, default=[])
    return history[-limit:]


def run_eod_reconciliation() -> Dict[str, Any]:
    """Diffs whichever live checkpoint was captured earlier today against the official EOD
    archive. This is the empirical check the live trigger time needs before Pillar 6 comes out
    of shadow mode (see module docstring) — status is always logged, never silently discarded."""
    today_str = date.today().isoformat()
    store = _load_daily_store()
    day_entry = store.get(today_str, {})

    used_checkpoint = "live_trigger" if day_entry.get("live_trigger") else ("final_check" if day_entry.get("final_check") else None)
    live_snapshot = day_entry.get(used_checkpoint, {}) if used_checkpoint else {}

    result: Dict[str, Any] = {
        "date": today_str,
        "run_at": _ist_now().isoformat(),
        "live_snapshot_checkpoint_used": used_checkpoint,
        "live_symbol_count": len(live_snapshot),
        "archive_symbol_count": None,
        "symbols_only_in_live": [],
        "symbols_only_in_archive": [],
        "value_mismatches": [],
        "status": "ARCHIVE_UNAVAILABLE",
    }

    archive_records = _gather_archive_records()
    if archive_records is None:
        logger.warning("[InstitutionalFlow] EOD reconciliation: archive fetch failed — cannot reconcile today.")
        _append_reconciliation_record(result)
        return result
    archive = aggregate_symbol_flows(archive_records)

    result["archive_symbol_count"] = len(archive)
    live_syms = set(live_snapshot.keys())
    archive_syms = set(archive.keys())
    result["symbols_only_in_live"] = sorted(live_syms - archive_syms)
    result["symbols_only_in_archive"] = sorted(archive_syms - live_syms)

    for sym in sorted(live_syms & archive_syms):
        live_net = live_snapshot[sym]["net_value_cr"]
        archive_net = archive[sym]["net_value_cr"]
        if abs(live_net - archive_net) > max(1.0, 0.05 * abs(archive_net)):
            result["value_mismatches"].append({
                "symbol": sym, "live_net_value_cr": live_net, "archive_net_value_cr": archive_net,
            })

    has_discrepancy = bool(result["symbols_only_in_live"] or result["symbols_only_in_archive"] or result["value_mismatches"])
    result["status"] = "DISCREPANCIES_FOUND" if has_discrepancy else "CLEAN"

    if has_discrepancy:
        logger.warning(
            f"[InstitutionalFlow] EOD reconciliation found discrepancies for {today_str}: "
            f"{len(result['symbols_only_in_live'])} live-only, {len(result['symbols_only_in_archive'])} archive-only, "
            f"{len(result['value_mismatches'])} value mismatches."
        )
    else:
        logger.info(f"[InstitutionalFlow] EOD reconciliation clean for {today_str} ({len(archive)} symbols).")

    _persist_snapshot(today_str, "eod_archive", archive, deals=_qualifying_deals(archive_records, _ist_now().isoformat()))
    _append_reconciliation_record(result)
    return result


# =========================================================================
# INDEX-LEVEL AGGREGATION — Nifty 50 / Bank Nifty only. Sensex is a BSE index; nseindia.com has
# no constituent data for it, so it stays honestly UNAVAILABLE here rather than faked — the same
# treatment this codebase already gives Sensex options elsewhere (see index_depth_analysis.py).
# =========================================================================
_NSE_INDEX_QUERY = {
    "NIFTY50": "NIFTY 50",
    "BANKNIFTY": "NIFTY BANK",
}

_INDEX_WEIGHTS_CACHE: Dict[str, Dict[str, Any]] = {}
INDEX_WEIGHTS_CACHE_TTL_SECONDS = 1800  # constituent weights barely move intraday — a 30-min
# cache avoids a live fetch on every /api/indices poll. Rebalances happen at most twice a year,
# never mid-day, so staleness within a trading day is a non-issue.

# |net_value_cr| below this reads as NEUTRAL rather than a directional call on a razor-thin sign.
INDEX_NEUTRAL_BAND_CR = _env_float("INSTITUTIONAL_FLOW_INDEX_NEUTRAL_BAND_CR", 10.0)


def _fetch_index_constituent_weights(nse_index_name: str) -> Optional[Dict[str, float]]:
    """{symbol: weight_pct}, derived from each constituent's live free-float market cap (ffmc)
    — NSE's own free-float weighting methodology, computed directly rather than sourced from a
    separately-maintained (and easily stale) weight table. None only on total fetch failure."""
    cached = _INDEX_WEIGHTS_CACHE.get(nse_index_name)
    if cached and (time.time() - cached["fetched_at"]) < INDEX_WEIGHTS_CACHE_TTL_SECONDS:
        return cached["weights"]

    def _do():
        client = _get_live_client()
        return client.get("live_index", {"index": nse_index_name})

    result = call_with_retry(_do, label=f"NSE index constituents [{nse_index_name}]")
    if result is None:
        _reset_live_client()
        return None

    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, list):
        logger.warning(f"[InstitutionalFlow] Unexpected index-constituent response shape for {nse_index_name}.")
        return None

    ffmc_by_symbol: Dict[str, float] = {}
    for row in data:
        symbol = row.get("symbol")
        ffmc = row.get("ffmc")
        # Skips the index-summary row itself (its "symbol" is the index name and ffmc is null)
        # and any malformed rows, rather than letting either corrupt the weight normalization.
        if not symbol or symbol == nse_index_name or not isinstance(ffmc, (int, float)) or ffmc <= 0:
            continue
        ffmc_by_symbol[symbol] = ffmc

    total_ffmc = sum(ffmc_by_symbol.values())
    if total_ffmc <= 0:
        logger.warning(f"[InstitutionalFlow] No usable constituent ffmc data for {nse_index_name}.")
        return None

    weights = {sym: round(100.0 * ffmc / total_ffmc, 4) for sym, ffmc in ffmc_by_symbol.items()}
    _INDEX_WEIGHTS_CACHE[nse_index_name] = {"weights": weights, "fetched_at": time.time()}
    return weights


def _unavailable_index_flow(index_name: str, status: str, reason: Optional[str] = None) -> Dict[str, Any]:
    return {
        "index_name": index_name, "status": status, "verdict": None, "total_net_value_cr": None,
        "constituents_with_flow": 0, "constituents_total": 0, "top_contributors": [], "as_of": None,
        "reason": reason,
    }


def compute_index_institutional_flow(index_name: str) -> Dict[str, Any]:
    """Constituent-weighted aggregate institutional flow for one index (index_scoring.py's
    short key, e.g. "NIFTY50"/"BANKNIFTY"/"SENSEX"). Combines each constituent's live
    free-float weight with its own already-captured same-day flow — get_institutional_flow_data()
    never triggers a live fetch itself, same convention as the rest of this module.

    status: NOT_FETCHED_YET (today's checkpoints haven't captured anything yet — nothing to
    aggregate, not "no signal"); UNAVAILABLE (no NSE constituent source for this index, or the
    live weight fetch failed); OK (aggregated normally, even if zero constituents had
    qualifying flow today — that's a real NEUTRAL reading, not unavailable).
    """
    daily_meta = get_daily_flow_meta()
    if not daily_meta.get("last_checkpoint"):
        return _unavailable_index_flow(index_name, "NOT_FETCHED_YET")

    nse_query = _NSE_INDEX_QUERY.get(index_name)
    if not nse_query:
        return _unavailable_index_flow(index_name, "UNAVAILABLE", "No NSE constituent-weight source for this index (BSE-listed).")

    weights = _fetch_index_constituent_weights(nse_query)
    if weights is None:
        return _unavailable_index_flow(index_name, "UNAVAILABLE", "Live constituent-weight fetch failed.")

    contributors = []
    total_net_cr = 0.0
    for symbol, weight_pct in weights.items():
        flow = get_institutional_flow_data(symbol)
        if not flow:
            continue
        total_net_cr += flow.get("net_value_cr", 0.0)
        contributors.append({
            "symbol": symbol,
            "weight_pct": weight_pct,
            "net_value_cr": flow.get("net_value_cr", 0.0),
            "dominant_side": flow.get("dominant_side", "NONE"),
            "tier": flow.get("tier", "BELOW_THRESHOLD"),
        })

    total_net_cr = round(total_net_cr, 2)
    if not contributors or abs(total_net_cr) < INDEX_NEUTRAL_BAND_CR:
        verdict = "NEUTRAL"
    else:
        verdict = "BULLISH" if total_net_cr > 0 else "BEARISH"

    contributors.sort(key=lambda c: abs(c["net_value_cr"]), reverse=True)

    return {
        "index_name": index_name,
        "status": "OK",
        "verdict": verdict,
        "total_net_value_cr": total_net_cr,
        "constituents_with_flow": len(contributors),
        "constituents_total": len(weights),
        "top_contributors": contributors[:5],
        "as_of": daily_meta.get("last_updated"),
    }


# =========================================================================
# SCHEDULING — call unconditionally on every scheduler tick.
# =========================================================================
def _load_checkpoint_meta() -> Dict[str, Any]:
    return read_json(CHECKPOINTS_META_FILE, default={})


def _mark_checkpoint_done(checkpoint: str, today_str: str):
    with json_file_lock(CHECKPOINTS_META_FILE):
        meta = _load_checkpoint_meta()
        meta[checkpoint] = today_str
        atomic_write_json(CHECKPOINTS_META_FILE, meta)


def _checkpoint_done_today(checkpoint: str, today_str: str) -> bool:
    return _load_checkpoint_meta().get(checkpoint) == today_str


def maybe_run_institutional_flow_checkpoints() -> Optional[str]:
    """No-op outside its own trigger windows; idempotent per day per checkpoint via a
    disk-backed flag (survives process restarts). A failed fetch is NOT marked done, so it
    retries on a later tick the same day rather than silently giving up for the whole day.
    Returns the checkpoint name that ran this tick, or None."""
    ist_now = _ist_now()
    if ist_now.weekday() >= 5:  # weekend — NSE doesn't publish new deals
        return None
    today_str = ist_now.date().isoformat()
    time_in_mins = ist_now.hour * 60 + ist_now.minute

    checkpoints = [
        ("live_trigger", LIVE_TRIGGER_HOUR * 60 + LIVE_TRIGGER_MINUTE),
        ("final_check", FINAL_CHECK_HOUR * 60 + FINAL_CHECK_MINUTE),
        ("eod_archive", RECONCILE_HOUR * 60 + RECONCILE_MINUTE),
    ]

    for name, trigger_mins in checkpoints:
        if time_in_mins < trigger_mins or _checkpoint_done_today(name, today_str):
            continue

        if name == "eod_archive":
            recon_result = run_eod_reconciliation()
            if recon_result.get("status") == "ARCHIVE_UNAVAILABLE":
                logger.warning("[InstitutionalFlow] EOD reconciliation checkpoint: archive still unavailable — will retry next tick.")
                continue
        else:
            records = _gather_live_records()
            if records is None:
                logger.warning(f"[InstitutionalFlow] Checkpoint '{name}' fetch failed — will retry next tick.")
                continue
            aggregated = aggregate_symbol_flows(records)
            deals = _qualifying_deals(records, _ist_now().isoformat())
            _persist_snapshot(today_str, name, aggregated, deals=deals)
            logger.info(f"[InstitutionalFlow] Checkpoint '{name}' captured {len(aggregated)} symbol(s), {len(deals)} qualifying deal(s) >= {MIN_VALUE_CR}cr.")

        _mark_checkpoint_done(name, today_str)
        return name

    return None
