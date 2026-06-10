#!/usr/bin/env python3
"""
mae_mfe.py — daily MAE/MFE excursion snapshot for open positions.

For each LIVE journal position, records how far price has run against the entry
(MAE = max adverse excursion) and in favour (MFE = max favourable excursion),
expressed in R (multiples of the entry-to-stop risk). After 15-20 closes this
is what tells you whether stops are too tight (winners show big MAE) or targets
too small (MFE >> realized R).

Run once a day (e.g. after the close) — it reads the intraday high/low from
Finnhub and ratchets the stored extremes. State is cumulative in
.claude/cache/dashboard/mae_mfe.json; the dashboard's Portfolio panel reads it.

US equities only (Finnhub). Entries are pruned automatically when a position
leaves LIVE status.

CLI:
  python3 mae_mfe.py snapshot     # update extremes from today's range
  python3 mae_mfe.py show         # print current excursions
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILLS_DIR.parent.parent
CACHE = PROJECT_ROOT / ".claude" / "cache" / "dashboard" / "mae_mfe.json"

sys.path.insert(0, str(SKILLS_DIR / "finnhub"))
import finnhub_client as fc  # noqa: E402
import portfolio  # same dir  # noqa: E402


def _load():
    if CACHE.is_file():
        try:
            return json.loads(CACHE.read_text())
        except json.JSONDecodeError:
            pass
    return {"positions": {}, "updated_at": None}


def _save(data):
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    CACHE.write_text(json.dumps(data, indent=1))


def snapshot():
    data = _load()
    positions = portfolio.open_positions()
    live_tickers = {p["ticker"] for p in positions}

    # Prune positions that are no longer LIVE
    for t in list(data["positions"].keys()):
        if t not in live_tickers:
            del data["positions"][t]

    updated = []
    for p in positions:
        t = p["ticker"]
        entry, stop = p.get("entry"), p.get("stop")
        if t.endswith(".KL") or not entry or not stop or entry <= stop:
            continue  # US-only; need a valid entry/stop to express R
        risk = entry - stop
        q, err = fc.quote(t)
        if err or not q:
            continue
        hi = q.get("h") or q.get("c")
        lo = q.get("l") or q.get("c")
        if hi is None or lo is None:
            continue
        rec = data["positions"].get(t, {"entry": entry, "stop": stop,
                                         "low": lo, "high": hi})
        rec["low"] = min(rec.get("low", lo), lo)
        rec["high"] = max(rec.get("high", hi), hi)
        rec["entry"] = entry
        rec["stop"] = stop
        # MAE = worst drawdown from entry (negative R); MFE = best run-up (positive R)
        rec["mae_r"] = round((rec["low"] - entry) / risk, 3)
        rec["mfe_r"] = round((rec["high"] - entry) / risk, 3)
        rec["last_snapshot"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        data["positions"][t] = rec
        updated.append((t, rec["mae_r"], rec["mfe_r"]))

    _save(data)
    return updated


def show():
    data = _load()
    if not data["positions"]:
        print("No open-position excursions recorded yet.")
        return
    print(f"Updated: {data.get('updated_at')}")
    for t, rec in data["positions"].items():
        print(f"  {t}: MAE {rec.get('mae_r'):+.2f}R · MFE {rec.get('mfe_r'):+.2f}R "
              f"(entry {rec['entry']}, stop {rec['stop']}, range {rec['low']}-{rec['high']})")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "snapshot":
        upd = snapshot()
        if upd:
            for t, mae, mfe in upd:
                print(f"  {t}: MAE {mae:+.2f}R · MFE {mfe:+.2f}R")
        else:
            print("No LIVE US positions to snapshot.")
    else:
        show()
