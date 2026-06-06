#!/usr/bin/env python3
"""sector-rotation — relative-strength ranking of the 11 SPDR sector ETFs vs SPY.

Answers: WHERE is money flowing right now? Which sectors are leading the broad
market over the last 1m / 3m / 6m? Outputs a heat-map-style ranking the
dashboard reads on build.

Data source: Twelve Data /time_series (free tier 800 calls/day, 8/min).
Migrated from yfinance+Yahoo to avoid XProtect false-positive blocks and
Yahoo IP bans. ~12 calls per refresh, ~90s wall-clock.

Falls back gracefully to stale cache on Twelve Data outage or budget exhaustion.

Cache: .claude/cache/sector_rotation/data.json  (4h TTL)
"""
from __future__ import annotations
import json, sys, warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]
CACHE = PROJECT_ROOT / ".claude" / "cache" / "sector_rotation" / "data.json"
CACHE.parent.mkdir(parents=True, exist_ok=True)

# Import Twelve Data client (sibling skill)
sys.path.insert(0, str(PROJECT_ROOT / ".claude" / "skills" / "twelve-data"))
import twelve_data_client as td  # noqa: E402

# 11 SPDR sector ETFs + SPY baseline
SECTORS = [
    ("XLK",  "Technology"),
    ("XLF",  "Financials"),
    ("XLV",  "Health Care"),
    ("XLY",  "Consumer Disc."),
    ("XLP",  "Consumer Staples"),
    ("XLE",  "Energy"),
    ("XLI",  "Industrials"),
    ("XLB",  "Materials"),
    ("XLU",  "Utilities"),
    ("XLRE", "Real Estate"),
    ("XLC",  "Comm. Services"),
]
BASELINE = "SPY"
CACHE_TTL_HOURS = 4
COOLDOWN_FILE = CACHE.parent / ".td_cooldown_until"
COOLDOWN_MINUTES_ON_FAIL = 60   # backoff if TD fails / budget exhausted


def cache_age_hours():
    if not CACHE.is_file(): return None
    try:
        ts = json.loads(CACHE.read_text()).get("_fetched_at")
        if not ts: return None
        return (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds() / 3600
    except Exception:
        return None

def is_fresh():
    age = cache_age_hours()
    return age is not None and age < CACHE_TTL_HOURS

def in_cooldown():
    """If Yahoo recently 429'd us, don't even try until the cooldown timestamp passes."""
    if not COOLDOWN_FILE.is_file(): return False
    try:
        until = datetime.fromisoformat(COOLDOWN_FILE.read_text().strip())
        return datetime.now(timezone.utc) < until
    except Exception:
        return False

def set_cooldown(minutes=COOLDOWN_MINUTES_ON_FAIL):
    from datetime import timedelta
    until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    COOLDOWN_FILE.write_text(until.isoformat(timespec="seconds"))
    return until

def stale_cache_with_warning():
    """Return the cached data marked as stale (used when fetch fails but cache exists)."""
    if not CACHE.is_file(): return None
    try:
        data = json.loads(CACHE.read_text())
        data["_stale"] = True
        data["_stale_reason"] = data.get("_stale_reason", "Yahoo fetch failed; using last good cache")
        return data
    except Exception:
        return None


def fetch(force=False):
    if is_fresh() and not force:
        return json.loads(CACHE.read_text())

    # Cooldown check — if Twelve Data recently failed, skip and use stale
    if in_cooldown() and not force:
        age = cache_age_hours()
        try:
            until = datetime.fromisoformat(COOLDOWN_FILE.read_text().strip())
            remaining_min = (until - datetime.now(timezone.utc)).total_seconds() / 60
        except Exception:
            remaining_min = 0
        cached = stale_cache_with_warning()
        if cached:
            print(f"Twelve Data cooldown active ({remaining_min:.0f} min remaining) — using stale cache "
                  f"(age {age:.1f}h). Pass --force to override.", file=sys.stderr)
            cached["_stale_reason"] = f"Twelve Data cooldown; cache is {age:.1f}h old"
            return cached
        return {"error": f"Twelve Data cooldown active, no cache available ({remaining_min:.0f} min remaining)"}

    # Configuration check
    if not td.is_configured():
        cached = stale_cache_with_warning()
        if cached:
            print(f"TWELVE_DATA_API_KEY not set — using stale cache. Drop key into .claude/skills/twelve-data/.env",
                  file=sys.stderr)
            cached["_stale_reason"] = "TD key not configured"
            return cached
        return {"error": "TWELVE_DATA_API_KEY not set (drop into .claude/skills/twelve-data/.env)"}

    # Budget check (informational)
    budget = td.budget_status()
    tickers = [s[0] for s in SECTORS] + [BASELINE]
    est_secs = int(len(tickers) * td.PACE_SECONDS)
    print(f"Fetching sector rotation data ({len(tickers)} ETFs via Twelve Data, ~{est_secs}s)…  "
          f"TD budget: {budget['used']}/{td.DAILY_CAP}", flush=True)

    closes_by_ticker = {}
    errors = {}
    fatal_error = None
    for i, t in enumerate(tickers):
        print(f"  [{i+1}/{len(tickers)}] {t}…", end="", flush=True)
        closes, err = td.candle_closes(t, outputsize=250)
        if err:
            errors[t] = err
            print(f" ✗ {err}", flush=True)
            # If the failure is budget exhaustion or auth, no point continuing the loop
            if "cap hit" in err or "API key" in err or "unauthorized" in err.lower():
                fatal_error = err
                print(f"  → fatal: {err}; stopping fetch loop and entering cooldown.", flush=True)
                break
        else:
            closes_by_ticker[t] = closes
            print(f" ✓ {len(closes)} bars", flush=True)

    if fatal_error:
        until = set_cooldown()
        cached = stale_cache_with_warning()
        if cached:
            print(f"  → cooldown set until {until.strftime('%H:%M UTC')}; falling back to stale cache.", file=sys.stderr)
            cached["_stale_reason"] = f"TD fatal: {fatal_error}; cooldown until {until.strftime('%H:%M UTC')}"
            return cached
        return {"error": f"TD fatal: {fatal_error}; no cache available"}

    if errors:
        print(f"  ⚠ {len(errors)} ticker(s) failed: {errors}", file=sys.stderr)
    if BASELINE not in closes_by_ticker:
        cached = stale_cache_with_warning()
        if cached:
            print(f"  → baseline SPY missing; falling back to stale cache.", file=sys.stderr)
            cached["_stale_reason"] = f"Baseline SPY fetch failed: {errors.get(BASELINE, 'unknown')}"
            return cached
        return {"error": f"baseline {BASELINE} fetch failed: {errors.get(BASELINE, 'unknown')}"}
    # All good — clear any prior cooldown flag
    if COOLDOWN_FILE.is_file():
        try: COOLDOWN_FILE.unlink()
        except Exception: pass

    def perf(closes, days):
        if not closes or len(closes) <= days: return None
        return (closes[-1] / closes[-1 - days] - 1) * 100

    spy_closes = closes_by_ticker[BASELINE]
    spy = {w: perf(spy_closes, d) for w, d in [("1m", 21), ("3m", 63), ("6m", 126)]}

    rows = []
    for sym, name in SECTORS:
        row = {"symbol": sym, "name": name}
        sym_closes = closes_by_ticker.get(sym)
        for w, d in [("1m", 21), ("3m", 63), ("6m", 126)]:
            p = perf(sym_closes, d)
            row[f"perf_{w}"] = p
            row[f"vs_spy_{w}"] = (p - spy[w]) if (p is not None and spy[w] is not None) else None
        rows.append(row)

    # Composite score = weighted avg of vs-SPY across 1m/3m/6m (50/30/20)
    for r in rows:
        weights = [(r.get("vs_spy_1m"), 0.5), (r.get("vs_spy_3m"), 0.3), (r.get("vs_spy_6m"), 0.2)]
        valid = [(v, w) for v, w in weights if v is not None]
        if valid:
            tot_w = sum(w for _, w in valid)
            r["composite"] = sum(v * w for v, w in valid) / tot_w
        else:
            r["composite"] = None

    rows.sort(key=lambda r: (r["composite"] is None, -(r["composite"] or 0)))

    out = {
        "_fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "baseline_spy": spy,
        "rows": rows,
        "_data_source": "twelve_data /time_series",
        "_partial_errors": errors if errors else None,
    }
    CACHE.write_text(json.dumps(out, indent=2))
    return out


def show(out):
    spy = out.get("baseline_spy", {})
    print(f"\n=== US SECTOR ROTATION ===  generated {out.get('_fetched_at')}")
    if spy.get('1m') is not None:
        print(f"Baseline SPY:  1m {spy.get('1m'):+.2f}%  ·  3m {spy.get('3m'):+.2f}%  ·  6m {spy.get('6m'):+.2f}%")
    print()
    print(f"{'RANK':<5} {'SYM':<5} {'SECTOR':<20} {'1m%':>8} {'vs SPY':>10} {'3m%':>8} {'vs SPY':>10} {'6m%':>8} {'vs SPY':>10} {'COMP':>8}")
    print("-" * 110)
    for i, r in enumerate(out["rows"], 1):
        def fmt(v, suffix="%"):
            return f"{v:+.2f}{suffix}" if v is not None else "  —  "
        comp = r.get("composite")
        marker = "🟢" if comp and comp > 2 else "🔴" if comp and comp < -2 else "⚪"
        print(f"{marker} {i:<3} {r['symbol']:<5} {r['name']:<20} {fmt(r.get('perf_1m')):>8} {fmt(r.get('vs_spy_1m')):>10} "
              f"{fmt(r.get('perf_3m')):>8} {fmt(r.get('vs_spy_3m')):>10} {fmt(r.get('perf_6m')):>8} {fmt(r.get('vs_spy_6m')):>10} "
              f"{fmt(comp, ''):>8}")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="Force re-fetch (ignore 1h TTL)")
    args = ap.parse_args()
    out = fetch(force=args.refresh)
    if "error" in out:
        print(f"Error: {out['error']}", file=sys.stderr); return 1
    show(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
