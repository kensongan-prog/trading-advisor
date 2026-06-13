#!/usr/bin/env python3
"""
rel_strength.py — per-ticker relative strength vs SPY (and its sector ETF).

Buying P1 pullbacks in names that are *leading* the market is one of the few
robust retail edges. This computes, for each US watchlist name, its 1-month and
3-month price return and the spread vs SPY over the same window. Positive spread
= outperforming the index = leadership.

Sector-relative strength reuses the sector-rotation cache (the per-sector ETF's
vs-SPY number) so we can also say "leading its sector" vs "just riding a hot
sector".

Output cached to .claude/cache/dashboard/rel_strength.json (4h TTL); the
dashboard's US grid reads it into an RS column.

CLI:
  python3 rel_strength.py refresh     # fetch + recompute
  python3 rel_strength.py show        # print cached
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILLS_DIR.parent.parent

sys.path.insert(0, str(SCRIPT_DIR))
import _cli_lib  # noqa: E402  (shared operator-CLI helpers, same dir)
CACHE = PROJECT_ROOT / ".claude" / "cache" / "dashboard" / "rel_strength.json"
SECTOR_CACHE = PROJECT_ROOT / ".claude" / "cache" / "sector_rotation" / "data.json"
DASH_CACHE = PROJECT_ROOT / ".claude" / "cache" / "dashboard"
WATCHLIST_MD = PROJECT_ROOT / "watchlist.md"
TTL_HOURS = 4

# yfinance sector name → SPDR sector ETF symbol (matches sector-rotation universe)
SECTOR_ETF = {
    "Technology": "XLK", "Financial Services": "XLF", "Healthcare": "XLV",
    "Consumer Cyclical": "XLY", "Consumer Defensive": "XLP", "Energy": "XLE",
    "Industrials": "XLI", "Basic Materials": "XLB", "Utilities": "XLU",
    "Real Estate": "XLRE", "Communication Services": "XLC",
}
CONTEXT_TICKERS = {"SPY", "QQQ", "DIA", "IWM"}


def _watchlist_us():
    return _cli_lib.watchlist_us(WATCHLIST_MD)


def _sector_of(ticker):
    p = DASH_CACHE / f"yfin_{ticker.replace('.', '_')}.json"
    if p.is_file():
        try:
            return json.loads(p.read_text()).get("sector")
        except json.JSONDecodeError:
            return None
    return None


def _return_pct(closes, lookback):
    """% return over the last `lookback` bars (closes oldest→newest)."""
    if not closes or len(closes) <= lookback:
        return None
    old = closes[-1 - lookback]
    new = closes[-1]
    if not old:
        return None
    return (new / old - 1) * 100


def _sector_vs_spy():
    """{ETF: {'1m':x,'3m':y}} from sector-rotation cache."""
    if not SECTOR_CACHE.is_file():
        return {}
    try:
        rows = json.loads(SECTOR_CACHE.read_text()).get("rows", [])
    except json.JSONDecodeError:
        return {}
    return {r["symbol"]: {"1m": r.get("vs_spy_1m"), "3m": r.get("vs_spy_3m")} for r in rows}


def _batch_closes(tickers):
    return _cli_lib.batch_closes(tickers, period="4mo")


def refresh():
    tickers = [t for t in _watchlist_us() if t not in CONTEXT_TICKERS]
    closes_map = _batch_closes(["SPY"] + tickers)
    spy_closes = closes_map.get("SPY")
    if not spy_closes:
        return None, "SPY history unavailable from yfinance"
    spy_1m = _return_pct(spy_closes, 21)
    spy_3m = _return_pct(spy_closes, 63)
    sector_rs = _sector_vs_spy()

    out = {}
    for t in tickers:
        closes = closes_map.get(t)
        if not closes:
            continue
        r1 = _return_pct(closes, 21)
        r3 = _return_pct(closes, 63)
        rec = {
            "ret_1m": round(r1, 2) if r1 is not None else None,
            "ret_3m": round(r3, 2) if r3 is not None else None,
            "vs_spy_1m": round(r1 - spy_1m, 2) if (r1 is not None and spy_1m is not None) else None,
            "vs_spy_3m": round(r3 - spy_3m, 2) if (r3 is not None and spy_3m is not None) else None,
        }
        sec = _sector_of(t)
        etf = SECTOR_ETF.get(sec)
        if etf and etf in sector_rs and rec["vs_spy_1m"] is not None:
            sec_vs = sector_rs[etf].get("1m")
            if sec_vs is not None:
                # leading its sector if the name's vs-SPY exceeds the sector's vs-SPY
                rec["vs_sector_1m"] = round(rec["vs_spy_1m"] - sec_vs, 2)
                rec["sector_etf"] = etf
        out[t] = rec

    data = {"spy_ret_1m": round(spy_1m, 2) if spy_1m else None,
            "spy_ret_3m": round(spy_3m, 2) if spy_3m else None,
            "tickers": out,
            "_fetched_at": datetime.now(timezone.utc).isoformat()}
    CACHE.write_text(json.dumps(data, indent=1))
    return data, None


def load_cached():
    return _cli_lib.load_json_cache(CACHE)


def cache_age_hours():
    d = load_cached()
    if not d or not d.get("_fetched_at"):
        return None
    try:
        ts = datetime.fromisoformat(d["_fetched_at"])
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    except ValueError:
        return None


def is_fresh():
    a = cache_age_hours()
    return a is not None and a < TTL_HOURS


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "refresh":
        d, err = refresh()
        if err:
            sys.exit(f"ERROR: {err}")
        print(f"✓ refreshed {len(d['tickers'])} tickers (SPY 1m {d['spy_ret_1m']}%, 3m {d['spy_ret_3m']}%)")
        for t, r in d["tickers"].items():
            print(f"  {t}: vs-SPY 1m {r['vs_spy_1m']:+}%  3m {r['vs_spy_3m']:+}%"
                  + (f"  vs-sector {r['vs_sector_1m']:+}%" if r.get("vs_sector_1m") is not None else ""))
    else:
        d = load_cached()
        print(json.dumps(d, indent=2) if d else "no cache — run `rel_strength.py refresh`")
