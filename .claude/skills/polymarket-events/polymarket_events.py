#!/usr/bin/env python3
"""
polymarket_events.py — Refresh prediction-market implied probabilities from
Polymarket's Gamma public-search API.

Phase B of the sentiment/confluence build. No auth, no rate limit at retail
research scale. Output is a single events.json the dashboard reads.

Manual (no automation). Output: .claude/cache/polymarket/events.json.

Usage:
    python3 .claude/skills/polymarket-events/polymarket_events.py             # refresh all
    python3 .claude/skills/polymarket-events/polymarket_events.py --show
    python3 .claude/skills/polymarket-events/polymarket_events.py --show macro_rates
    python3 .claude/skills/polymarket-events/polymarket_events.py --probe "fed rate cuts"
    python3 .claude/skills/polymarket-events/polymarket_events.py --clear
"""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
CACHE_DIR = PROJECT_ROOT / ".claude" / "cache" / "polymarket"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE = CACHE_DIR / "events.json"
HISTORY_DIR = CACHE_DIR / "history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

UA = "trading-advisor/0.1 (polymarket-events)"
SEARCH_URL = "https://gamma-api.polymarket.com/public-search"
DEFAULT_DELAY_SEC = 0.5
MAX_EVENTS_PER_QUERY = 3       # keep top-N events per query (by relevance/volume)
MAX_MARKETS_PER_EVENT = 6      # keep top-N markets per event (by liquidity)
HISTORY_KEEP_DAYS = 30         # prune snapshots older than this

# Curated queries. Edit to add/remove categories or queries.
QUERIES = {
    "macro_rates":  ["fed rate cuts", "fed decision", "rate hike"],
    "macro_econ":   ["recession", "inflation", "unemployment"],
    "crypto":       ["bitcoin price", "ethereum price"],
    "geopolitics":  ["china taiwan", "russia ukraine"],
}

# Title-substring blacklist — drops meme/gaming/celebrity markets that occasionally
# match serious queries (e.g. "Russia-Ukraine Ceasefire before GTA VI?" sneaks into
# the "russia ukraine" geopolitics query). Match is case-insensitive substring.
NOISE_BLACKLIST = [
    "gta vi", "gta 6", "gta vii",
    "before grand theft", "before grand theft auto",
    "before half-life", "before kanye",
    "jesus christ return", "jesus returns",
    "elden ring",
    # Add more as we observe pollution
]


def is_noise_title(title):
    t = (title or "").lower()
    return any(b in t for b in NOISE_BLACKLIST)


# ── HTTP ───────────────────────────────────────────────────────────────────
def search(query, limit=5, timeout=20):
    """Hit Polymarket public-search. Returns ({events:[...], ...}, error_or_none)."""
    url = f"{SEARCH_URL}?{urllib.parse.urlencode({'q': query, 'limit': limit})}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ── Event normalization ────────────────────────────────────────────────────
def _safe_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _parse_prices(market):
    """Markets have outcomePrices as either list, JSON string, or split into yesPrice/noPrice.
    Returns (yes_price, no_price) — both floats in [0,1] or (None, None)."""
    op = market.get("outcomePrices")
    if isinstance(op, str):
        try:
            op = json.loads(op)
        except Exception:
            op = None
    if isinstance(op, list) and len(op) >= 2:
        return _safe_float(op[0]), _safe_float(op[1])
    yp = _safe_float(market.get("yesPrice"))
    np = _safe_float(market.get("noPrice"))
    if yp is None and np is not None:
        yp = 1.0 - np
    if np is None and yp is not None:
        np = 1.0 - yp
    return yp, np


def normalize_event(ev):
    """Pluck the fields we care about from a Polymarket event."""
    raw_markets = ev.get("markets") or []
    markets = []
    for m in raw_markets:
        yp, np = _parse_prices(m)
        markets.append({
            "id": m.get("id"),
            "question": m.get("question") or m.get("groupItemTitle") or "—",
            "yes_price": yp,
            "no_price": np,
            "liquidity": _safe_float(m.get("liquidity")),
            "volume_24h": _safe_float(m.get("volume24hr")),
        })
    # Sort by yes_price desc so the most-probable outcomes display first — that's the
    # most informative ordering for the operator. Then truncate to N markets.
    markets.sort(key=lambda x: (x.get("yes_price") if x.get("yes_price") is not None else -1), reverse=True)
    markets = markets[:MAX_MARKETS_PER_EVENT]

    # Headline = the highest-probability market. This answers "what does the market
    # think is most likely?" — far more useful than picking by liquidity which can
    # surface 0%-prob tail-outcomes as the headline.
    headline_q = None
    headline_p = None
    if markets and markets[0].get("yes_price") is not None:
        top = markets[0]
        headline_p = round(top["yes_price"], 4)
        headline_q = top["question"]

    slug = ev.get("slug") or ev.get("ticker") or ""
    return {
        "title": ev.get("title") or ev.get("description") or "—",
        "slug": slug,
        "end_date": ev.get("endDate") or ev.get("end_date"),
        "volume_24h": _safe_float(ev.get("volume24hr")),
        "liquidity": _safe_float(ev.get("liquidity")),
        "url": f"https://polymarket.com/event/{slug}" if slug else None,
        "markets": markets,
        "headline_question": headline_q,
        "headline_prob": headline_p,
    }


# ── Delta calculation ──────────────────────────────────────────────────────
def _load_prior_snapshot(min_age_days=7):
    """Return the most recent snapshot at least min_age_days old, or None."""
    cutoff_ts = time.time() - min_age_days * 86400
    snaps = []
    for p in HISTORY_DIR.glob("snapshot_*.json"):
        try:
            stat = p.stat().st_mtime
            if stat <= cutoff_ts:
                snaps.append((stat, p))
        except Exception:
            continue
    if not snaps:
        return None
    snaps.sort(reverse=True)
    try:
        return json.loads(snaps[0][1].read_text())
    except Exception:
        return None


def _apply_deltas(current, prior_snapshot):
    """Attach delta_7d to each market in current by matching slug+question against prior."""
    if not prior_snapshot:
        return current
    # Build lookup: (event_slug, market_question) → yes_price
    prior_prices = {}
    for cat_data in (prior_snapshot.get("categories") or {}).values():
        for ev in cat_data.get("events", []) or []:
            for m in ev.get("markets", []) or []:
                key = (ev.get("slug"), m.get("question"))
                if m.get("yes_price") is not None:
                    prior_prices[key] = m["yes_price"]

    # Defensive — schema can drift; never crash mid-delta calc when current fetch succeeded
    for cat_data in (current.get("categories") or {}).values():
        for ev in (cat_data.get("events") or []):
            for m in (ev.get("markets") or []):
                key = (ev.get("slug"), m.get("question"))
                prior_yes = prior_prices.get(key)
                if prior_yes is not None and m.get("yes_price") is not None:
                    m["delta_7d"] = round(m["yes_price"] - prior_yes, 4)
                else:
                    m["delta_7d"] = None
    return current


# ── Refresh pipeline ───────────────────────────────────────────────────────
def refresh_all(delay=DEFAULT_DELAY_SEC, verbose=True):
    out = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "categories": {},
    }
    # Carry prior fetched_at into the new file (used for staleness UI)
    if CACHE_FILE.exists():
        try:
            prior = json.loads(CACHE_FILE.read_text())
            out["previous_fetched_at"] = prior.get("fetched_at")
        except Exception:
            pass

    for cat, queries in QUERIES.items():
        if verbose:
            print(f"\n── {cat} ──")
        out["categories"][cat] = {"events": []}
        seen_slugs = set()
        for q in queries:
            if verbose:
                print(f"  q={q!r} ... ", end="", flush=True)
            data, err = search(q, limit=MAX_EVENTS_PER_QUERY)
            if err:
                if verbose:
                    print(f"ERR ({err})")
                continue
            events_raw = (data or {}).get("events") or []
            picked = 0
            for ev in events_raw[:MAX_EVENTS_PER_QUERY]:
                slug = ev.get("slug")
                if slug and slug in seen_slugs:
                    continue
                # Skip closed/inactive
                if ev.get("closed") or not ev.get("active", True):
                    continue
                # Skip meme/gaming/celebrity noise that occasionally matches serious queries
                if is_noise_title(ev.get("title")):
                    continue
                normalized = normalize_event(ev)
                # Skip events with no real market data
                if not normalized["markets"] or normalized["headline_prob"] is None:
                    continue
                out["categories"][cat]["events"].append(normalized)
                if slug:
                    seen_slugs.add(slug)
                picked += 1
            if verbose:
                print(f"{picked} new event(s)")
            time.sleep(delay)

    # Apply 7d deltas from prior snapshot (if any)
    prior_snap = _load_prior_snapshot(min_age_days=7)
    out = _apply_deltas(out, prior_snap)

    # Save current
    CACHE_FILE.write_text(json.dumps(out, indent=2), encoding="utf-8")

    # Save historical snapshot for future delta calcs
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (HISTORY_DIR / f"snapshot_{ts}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    # Prune old snapshots
    cutoff_ts = time.time() - HISTORY_KEEP_DAYS * 86400
    for p in HISTORY_DIR.glob("snapshot_*.json"):
        try:
            if p.stat().st_mtime < cutoff_ts:
                p.unlink()
        except Exception:
            continue

    return out


# ── Show / inspect commands ────────────────────────────────────────────────
def cmd_show(category_filter=None):
    if not CACHE_FILE.exists():
        print("(no cache — run without --show to populate)")
        return 1
    data = json.loads(CACHE_FILE.read_text())
    print(f"fetched_at: {data.get('fetched_at')}")
    if data.get("previous_fetched_at"):
        print(f"previous:   {data['previous_fetched_at']}")
    print()
    for cat, cd in data.get("categories", {}).items():
        if category_filter and cat != category_filter:
            continue
        print(f"── {cat} ──")
        for ev in cd.get("events", []):
            hp = ev.get("headline_prob")
            hp_str = f"{hp*100:.0f}%" if hp is not None else "—"
            print(f"  • [{hp_str}] {ev['title'][:75]}  ({ev.get('headline_question') or '—'})")
            if category_filter:
                for m in ev.get("markets", [])[:4]:
                    yp = m.get("yes_price")
                    yp_str = f"{yp*100:.0f}%" if yp is not None else "—"
                    d = m.get("delta_7d")
                    d_str = f" Δ7d {d*100:+.0f}pp" if d is not None else ""
                    print(f"      {yp_str:>4}  {m['question'][:60]}{d_str}")
        print()
    return 0


def cmd_clear():
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()
        print(f"Cleared {CACHE_FILE}")
    n = 0
    for p in HISTORY_DIR.glob("snapshot_*.json"):
        p.unlink(); n += 1
    print(f"Cleared {n} history snapshots")
    return 0


def cmd_probe(query):
    """Quick probe — show top 3 events matching a query without writing cache."""
    data, err = search(query, limit=5)
    if err:
        print(f"ERR: {err}"); return 1
    events = (data or {}).get("events") or []
    print(f"Top {min(5, len(events))} events for {query!r}:")
    for ev in events[:5]:
        norm = normalize_event(ev)
        hp = norm.get("headline_prob")
        hp_str = f"{hp*100:.0f}%" if hp is not None else "—"
        print(f"  • [{hp_str}] {norm['title'][:75]}")
        for m in norm["markets"][:4]:
            yp = m.get("yes_price")
            yp_str = f"{yp*100:.0f}%" if yp is not None else "—"
            print(f"      {yp_str:>4}  {m['question'][:60]}")
    return 0


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("category_or_q", nargs="?", help="Category for --show, or query for --probe")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--probe", action="store_true", help="Probe a query without caching (debug helper)")
    args = ap.parse_args()

    if args.clear: return cmd_clear()
    if args.show: return cmd_show(args.category_or_q)
    if args.probe:
        if not args.category_or_q:
            print("ERROR: --probe needs a query argument", file=sys.stderr); return 1
        return cmd_probe(args.category_or_q)
    refresh_all()
    print()
    cmd_show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
