#!/usr/bin/env python3
"""
setup_queue.py — turn P1-ready watchlist names into ready-to-log prospectus drafts.

Reads the dashboard's cached technicals, finds US watchlist names sitting in the
Phase-1 entry band (trend intact + RSI 35-50), and computes doctrine-sized
levels for each:
  - entry  = current cached price (reference; real trigger is the P1 close-above)
  - stop   = entry − 1.5×ATR(14)   (structure/ATR stop per §5)
  - tp1    = entry + 2×(entry−stop) (2R, clears the 1.5R floor)
  - size   = (account × risk%) ÷ (entry − stop), rounded down to whole shares
The §5 math and a halt-window check come along so the draft is decision-ready.

`candidates()` returns the list (consumed by server.py's Setup Queue panel).
`create(ticker, ...)` shells out to j.py new to write the prospectus.

CLI:
  python3 setup_queue.py list                 # print candidates as JSON
  python3 setup_queue.py create AUPH          # write a prospectus stub
"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILLS_DIR.parent.parent
DASH_CACHE = PROJECT_ROOT / ".claude" / "cache" / "dashboard"
WATCHLIST_MD = PROJECT_ROOT / "watchlist.md"
J_PY = SKILLS_DIR / "journal" / "j.py"
JOURNAL_DIR = PROJECT_ROOT / "journal"

ACCOUNT = 20000.0
RISK_PCT = 0.02
ATR_MULT = 1.5
CONTEXT_TICKERS = {"SPY", "QQQ", "DIA", "IWM"}


def _watchlist_us():
    import re
    if not WATCHLIST_MD.is_file():
        return []
    out, in_us = [], False
    for line in WATCHLIST_MD.read_text().splitlines():
        if line.startswith("## "):
            h = line[3:].lower()
            in_us = ("equities" in h or "etf" in h)
            continue
        if in_us:
            m = re.match(r"\s*-\s*`([^`]+)`", line)
            if m and m.group(1).strip().lower() != "ticker":
                out.append(m.group(1).strip().upper())
    return out


def _cache(ticker):
    p = DASH_CACHE / f"yfin_{ticker.replace('.', '_')}.json"
    if p.is_file():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return None
    return None


def _has_open_prospectus(ticker):
    """Skip names that already have a non-closed journal entry today/recent."""
    import re
    if not JOURNAL_DIR.is_dir():
        return False
    for p in JOURNAL_DIR.glob(f"*_{ticker.replace('.', '_')}.md"):
        txt = p.read_text()
        m = re.search(r"\*\*Status:\*\*\s*([^\n]+)", txt)
        status = (m.group(1) if m else "").upper()
        if "CLOSED" not in status and "DEAD" not in status:
            return True
    return False


def _compute_levels(c):
    price = c.get("price")
    atr = c.get("atr14")
    if not price or not atr:
        return None
    stop = round(price - ATR_MULT * atr, 2)
    risk_per = price - stop
    if risk_per <= 0:
        return None
    tp1 = round(price + 2 * risk_per, 2)
    shares = int((ACCOUNT * RISK_PCT) // risk_per)
    return {
        "entry": round(price, 2),
        "stop": stop,
        "tp1": tp1,
        "risk_per_share": round(risk_per, 2),
        "shares": shares,
        "dollar_risk": round(shares * risk_per, 2),
        "rr1": 2.0,
    }


def candidates():
    out = []
    for t in _watchlist_us():
        if t in CONTEXT_TICKERS:
            continue
        c = _cache(t)
        if not c:
            continue
        rsi, price, s50, s200 = c.get("rsi14"), c.get("price"), c.get("sma50"), c.get("sma200")
        if None in (rsi, price, s50, s200):
            continue
        if not (price > s50 > s200 and 35 <= rsi <= 50):
            continue
        lv = _compute_levels(c)
        if not lv:
            continue
        out.append({
            "ticker": t,
            "name": c.get("name", t),
            "rsi": round(rsi, 1),
            "atr_pct": round(c.get("atr14") / price * 100, 2) if price else None,
            "next_earnings": c.get("next_earnings"),
            "already_drafted": _has_open_prospectus(t),
            **lv,
        })
    return out


def create(ticker, heat_used=0.0, heat_max=1200.0):
    ticker = ticker.upper()
    c = _cache(ticker)
    if not c:
        return 1, f"no cached technicals for {ticker} — refresh the dashboard first"
    lv = _compute_levels(c)
    if not lv:
        return 1, f"cannot compute levels for {ticker} (missing price/ATR)"
    argv = [
        sys.executable, str(J_PY), "new", ticker,
        "--entry", str(lv["entry"]), "--stop", str(lv["stop"]), "--tp1", str(lv["tp1"]),
        "--market", "us", "--account", str(ACCOUNT), "--risk-pct", str(RISK_PCT),
        "--heat-used", str(heat_used), "--heat-max", str(heat_max),
        "--name", c.get("name", ticker),
        "--rsi", f"{c.get('rsi14'):.1f}",
        "--atr-pct", f"{lv['risk_per_share'] / lv['entry'] * 100:.2f}%",
        "--stop-logic", f"{ATR_MULT}× ATR(14) below reference price (structure stop per §5)",
        "--tp1-logic", "2R above entry (clears 1.5R floor)",
        "--entry-logic", f"P1 close-above trigger; reference ${lv['entry']:.2f}",
        "--entry-note", "Setup Queue draft — confirm the daily close-above before entry",
    ]
    proc = subprocess.run(argv, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "create" and len(sys.argv) >= 3:
        rc, out = create(sys.argv[2])
        print(out)
        sys.exit(rc)
    else:
        print(json.dumps(candidates(), indent=2))
