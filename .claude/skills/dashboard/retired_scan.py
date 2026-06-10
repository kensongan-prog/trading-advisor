#!/usr/bin/env python3
"""
retired_scan.py — passive re-entry watch for retired watchlist names.

When a name is moved to "Removed / retired" in watchlist.md, nothing watches it
anymore — even though many are retired *because* they're extended/downtrending,
which is exactly the setup the doctrine's 🧊 BUY (capitulation-buy) rule exists
to catch on the way back. This scans the retired list for a *forming*
constructive re-entry condition and re-surfaces only those, with no row clutter
on the main grid.

Re-surface condition (the technical half of the §4 🧊 BUY-aligned gate):
    RSI(14) in [35, 55]  AND  -5% ≤ price-vs-SMA50 ≤ +10%   (constructive basing)
If a retail-sentiment cache entry shows a bearish extreme (bear ≥ 0.80, conv ≥
0.70) on top of that, it's flagged as a full 🧊 BUY-aligned re-entry — the rest
are "technical basing forming, watch".

Output cached to .claude/cache/dashboard/retired_scan.json; the dashboard reads
it into a small panel. US (+ .KL) names via yfinance batch download.

CLI:
  python3 retired_scan.py refresh
  python3 retired_scan.py show
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILLS_DIR.parent.parent
CACHE = PROJECT_ROOT / ".claude" / "cache" / "dashboard" / "retired_scan.json"
SENTIMENT_DIR = PROJECT_ROOT / ".claude" / "cache" / "sentiment"
WATCHLIST_MD = PROJECT_ROOT / "watchlist.md"


def parse_retired():
    """Return [{ticker, reason}] from the Removed / retired section."""
    if not WATCHLIST_MD.is_file():
        return []
    out, in_sec = [], False
    for line in WATCHLIST_MD.read_text().splitlines():
        if line.startswith("## "):
            in_sec = "removed" in line.lower() or "retired" in line.lower()
            continue
        if in_sec:
            m = re.match(r"\s*-\s*`([^`]+)`\s*[—\-:]?\s*(.*)", line)
            if m:
                out.append({"ticker": m.group(1).strip().upper(),
                            "reason": m.group(2).strip()})
    return out


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100 - 100 / (1 + rs)


def _sma(closes, n):
    return sum(closes[-n:]) / n if len(closes) >= n else None


def _batch_closes(tickers):
    import warnings
    warnings.filterwarnings("ignore")
    import yfinance as yf
    df = yf.download(tickers, period="10mo", interval="1d",
                     auto_adjust=True, progress=False, threads=True)
    out = {}
    close = df["Close"] if "Close" in df.columns.get_level_values(0) else df
    for t in tickers:
        try:
            series = close[t] if hasattr(close, "columns") and t in close.columns else close
            vals = [float(x) for x in series.dropna().tolist()]
            if vals:
                out[t] = vals
        except Exception:
            continue
    return out


def _sentiment_extreme(ticker):
    """True if retail sentiment cache shows a bearish-capitulation extreme."""
    p = SENTIMENT_DIR / f"{ticker.upper()}.json"
    if not p.is_file():
        return None
    try:
        comp = (json.loads(p.read_text()).get("composite") or {})
    except Exception:
        return None
    bear = comp.get("bear_score")
    conv = comp.get("conviction")
    if bear is not None and conv is not None and bear >= 0.80 and conv >= 0.70:
        return {"bear_score": bear, "conviction": conv}
    return None


def refresh():
    retired = parse_retired()
    if not retired:
        data = {"candidates": [], "scanned": 0, "_fetched_at": datetime.now(timezone.utc).isoformat()}
        CACHE.write_text(json.dumps(data, indent=1))
        return data
    yf_syms = [r["ticker"] for r in retired]
    closes_map = _batch_closes(yf_syms)

    candidates = []
    for r in retired:
        t = r["ticker"]
        closes = closes_map.get(t)
        if not closes or len(closes) < 60:
            continue
        price = closes[-1]
        rsi = _rsi(closes)
        s50 = _sma(closes, 50)
        s200 = _sma(closes, 200)
        if rsi is None or s50 is None:
            continue
        vs50 = (price / s50 - 1) * 100
        constructive = (35 <= rsi <= 55) and (-5 <= vs50 <= 10)
        if not constructive:
            continue
        sent = _sentiment_extreme(t)
        candidates.append({
            "ticker": t,
            "reason": r["reason"][:120],
            "price": round(price, 2),
            "rsi": round(rsi, 1),
            "vs_sma50_pct": round(vs50, 1),
            "above_sma200": (s200 is not None and price > s200),
            "sentiment_capitulation": sent,
            "tier": "🧊 BUY-aligned" if sent else "📉 basing forming",
        })

    data = {"candidates": candidates, "scanned": len(retired),
            "_fetched_at": datetime.now(timezone.utc).isoformat()}
    CACHE.write_text(json.dumps(data, indent=1))
    return data


def load_cached():
    if CACHE.is_file():
        try:
            return json.loads(CACHE.read_text())
        except json.JSONDecodeError:
            return None
    return None


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "refresh":
        d = refresh()
        print(f"✓ scanned {d['scanned']} retired name(s) → {len(d['candidates'])} re-surfacing")
        for c in d["candidates"]:
            print(f"  {c['tier']}  {c['ticker']}: ${c['price']} RSI {c['rsi']} "
                  f"vs SMA50 {c['vs_sma50_pct']:+}% — was retired: {c['reason']}")
    else:
        d = load_cached()
        print(json.dumps(d, indent=2) if d else "no cache — run `retired_scan.py refresh`")
