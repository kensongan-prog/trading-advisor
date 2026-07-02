#!/usr/bin/env python3
"""
portfolio.py — derive live portfolio state + trade calibration from the journal.

The journal (journal/*.md) is the source of truth. This script reads it and
computes the two things the doctrine needs but that were previously maintained
by hand (and so drifted stale):

  • Open-position HEAT (§5): sum of $-at-risk across LIVE entries, vs the 6%
    ceiling, with a correlation grouping by sector ("3 tech longs = 1 bet").
  • Trade CALIBRATION: closed-trade count, win rate, average R, expectancy,
    and the R-distribution — the evidence the Phase-2 gate needs.

`sync` regenerates portfolio.md so the at-a-glance file is never stale.
`state` prints the computed dict as JSON (consumed by the dashboard build).

CLI:
  python3 portfolio.py state          # JSON: heat + expectancy + positions
  python3 portfolio.py sync           # rewrite portfolio.md from the journal
  python3 portfolio.py show           # human-readable summary
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILLS_DIR.parent.parent
JOURNAL_DIR = PROJECT_ROOT / "journal"
DASH_CACHE = PROJECT_ROOT / ".claude" / "cache" / "dashboard"
PORTFOLIO_MD = PROJECT_ROOT / "portfolio.md"
RISK_PARAMS_JSON = PROJECT_ROOT / "risk_params.json"

ACCOUNT = 20000.0
HEAT_MAX = 1200.0  # 6% of account, per AGENTS.md USER CONFIG
RISK_PCT_PER_TRADE = 0.02  # 2% max risk per trade, per AGENTS.md USER CONFIG
PHASE2_GATE_TARGET = 20    # closed trades needed to exit Phase 1, per AGENTS.md Phased Ramp


def _status(txt):
    m = re.search(r"\*\*Status:\*\*\s*([^\n]+)", txt)
    return (m.group(1).strip() if m else "").rstrip(".")


def _money_after(txt, label):
    m = re.search(re.escape(label) + r"[^\n$]*\$?\s*([0-9][0-9,]*\.?[0-9]*)", txt)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _table_value(txt, label):
    """First $-value in a table row whose first cell starts with `label`."""
    for line in txt.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) >= 3 and cells[1].lower().startswith(label.lower()):
            m = re.search(r"\$?\s*([0-9]+(?:\.[0-9]+)?)", cells[2].replace("**", ""))
            if m:
                return float(m.group(1))
    return None


def _sector(ticker):
    p = DASH_CACHE / f"yfin_{ticker.replace('.', '_')}.json"
    if p.is_file():
        try:
            return json.loads(p.read_text()).get("sector") or "—"
        except json.JSONDecodeError:
            return "—"
    return "—"


def _entries():
    if not JOURNAL_DIR.is_dir():
        return []
    out = []
    for p in sorted(JOURNAL_DIR.glob("*.md"), reverse=True):
        if p.name.startswith("_") or p.name.lower() == "readme.md":
            continue
        txt = p.read_text()
        mt = re.match(r"(\d{4}-\d{2}-\d{2})_(.+)", p.stem)
        out.append({
            "file": p.name,
            "date": mt.group(1) if mt else "",
            "ticker": (mt.group(2) if mt else p.stem).replace("_", "."),
            "status": _status(txt),
            "txt": txt,
        })
    return out


def open_positions():
    out = []
    for e in _entries():
        if not re.match(r"LIVE\b", e["status"], re.I):
            continue
        txt = e["txt"]
        dollar_risk = _money_after(txt, "$ at risk:") or _money_after(txt, "Max loss:")
        out.append({
            "ticker": e["ticker"],
            "date": e["date"],
            "entry": _table_value(txt, "entry") ,
            "stop": _table_value(txt, "stop"),
            "dollar_risk": dollar_risk or 0.0,
            "sector": _sector(e["ticker"]),
            "paper": "paper" in e["status"].lower(),
            "file": e["file"],
        })
    return out


def closed_trades():
    out = []
    for e in _entries():
        if not re.match(r"CLOSED\b", e["status"], re.I):
            continue
        m = re.search(r"\(([+-]?[0-9]+(?:\.[0-9]+)?)R\)", e["status"])
        rm = re.search(r"CLOSED\s*—\s*(\w+)", e["status"], re.I)
        out.append({
            "ticker": e["ticker"],
            "date": e["date"],
            "result": (rm.group(1).lower() if rm else "?"),
            "r": float(m.group(1)) if m else None,
            "file": e["file"],
        })
    return out


def heat():
    pos = open_positions()
    used = sum(p["dollar_risk"] for p in pos)
    by_sector = {}
    for p in pos:
        by_sector.setdefault(p["sector"], []).append(p["ticker"])
    return {
        "used": round(used, 2),
        "max": HEAT_MAX,
        "headroom": round(HEAT_MAX - used, 2),
        "pct_equity": round(used / ACCOUNT * 100, 2),
        "n_positions": len(pos),
        "by_sector": by_sector,
    }


def expectancy():
    closed = [c for c in closed_trades() if c["r"] is not None]
    n = len(closed)
    if n == 0:
        return {"n": 0, "win_rate": None, "avg_r": None, "sum_r": 0.0,
                "wins": 0, "losses": 0, "distribution": []}
    rs = [c["r"] for c in closed]
    wins = sum(1 for r in rs if r > 0)
    losses = sum(1 for r in rs if r <= 0)
    return {
        "n": n,
        "win_rate": round(wins / n * 100, 1),
        "avg_r": round(sum(rs) / n, 3),
        "sum_r": round(sum(rs), 2),
        "wins": wins,
        "losses": losses,
        "distribution": sorted(rs),
    }


def correlation_note(h):
    grouped = [(s, ts) for s, ts in h["by_sector"].items() if len(ts) >= 2]
    if not grouped:
        return ""
    bits = [f"{len(ts)} in {s} ({', '.join(ts)})" for s, ts in grouped]
    return "Correlated exposure: " + "; ".join(bits) + " — treat each cluster as closer to one bet for sizing."


def phase2_gate_passed():
    """The Phase 1 exit / Phase 2 unlock criterion per AGENTS.md's Phased Ramp:
    >=20 closed trades with >=0R cumulative. Named after portfolio.py's own
    pre-existing 'phase2_gate' dict — this is that same gate, just as a bool."""
    exp = expectancy()
    return exp["n"] >= PHASE2_GATE_TARGET and exp["sum_r"] >= 0


def state():
    h = heat()
    return {
        "account": ACCOUNT,
        "heat": h,
        "expectancy": expectancy(),
        "open_positions": open_positions(),
        "correlation_note": correlation_note(h),
        "phase2_gate": {"closed": expectancy()["n"], "target": PHASE2_GATE_TARGET,
                        "cum_r": expectancy()["sum_r"],
                        "passed": phase2_gate_passed()},
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


# ── portfolio.md regeneration ───────────────────────────────────────────────
def write_portfolio_md():
    s = state()
    h = s["heat"]
    pos = s["open_positions"]
    exp = s["expectancy"]
    closed = closed_trades()

    lines = [
        "# Portfolio",
        "",
        "> **Auto-generated** by `portfolio.py sync` from the journal (source of truth). "
        "Do not hand-edit — re-run sync, or it will be overwritten. Heat math derives from "
        "LIVE journal entries; calibration from CLOSED entries.",
        f"> Last synced: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Open positions",
        "",
        "| Opened | Instrument | Entry | Stop | $ at Risk | Sector | Paper? | Journal |",
        "|--------|------------|-------|------|-----------|--------|--------|---------|",
    ]
    if pos:
        for p in pos:
            lines.append(
                f"| {p['date']} | {p['ticker']} | "
                f"{('$%.2f' % p['entry']) if p['entry'] else '—'} | "
                f"{('$%.2f' % p['stop']) if p['stop'] else '—'} | "
                f"${p['dollar_risk']:.2f} | {p['sector']} | "
                f"{'yes' if p['paper'] else 'real'} | {p['file']} |")
    else:
        lines.append("| _none_ | | | | | | | |")

    lines += [
        "",
        "## Portfolio heat",
        "",
        f"- Total $ at risk across open positions: **${h['used']:.2f}**",
        f"- Total % equity at risk: **{h['pct_equity']:.2f}%**",
        f"- Heat ceiling (6% of ${ACCOUNT:,.0f}): **${h['max']:.0f}**",
        f"- Headroom: **${h['headroom']:.2f}**",
        "",
        "## Correlation notes",
        "",
        f"{s['correlation_note'] or '_No correlated clusters among open positions._'}",
        "",
        "## Calibration (closed trades)",
        "",
        f"- Closed trades: **{exp['n']} / 20** toward the Phase-2 gate",
        f"- Win rate: **{exp['win_rate'] if exp['win_rate'] is not None else '—'}%**"
        f"  ({exp['wins']}W / {exp['losses']}L)",
        f"- Average R: **{exp['avg_r'] if exp['avg_r'] is not None else '—'}**",
        f"- Cumulative R: **{exp['sum_r']:+.2f}R**",
        "",
        "## Closed positions (recent)",
        "",
        "| Closed | Instrument | Result | R | Journal |",
        "|--------|------------|--------|---|---------|",
    ]
    if closed:
        for c in closed[:20]:
            rstr = f"{c['r']:+.2f}R" if c["r"] is not None else "—"
            lines.append(f"| {c['date']} | {c['ticker']} | {c['result']} | {rstr} | {c['file']} |")
    else:
        lines.append("| _none_ | | | | |")
    lines.append("")

    PORTFOLIO_MD.write_text("\n".join(lines))
    return PORTFOLIO_MD


# ── risk_params.json export (Bridge Phase 4) ────────────────────────────────
def risk_params():
    """TA's own live risk parameters + calibration-gate state, in the shape
    MooMoo (a separate repo/process) reads read-only via its existing
    TRADING_ADVISOR_ROOT — same bridge pattern as watchlist.md/journal/*.md,
    just machine-readable. Lets MooMoo's staging validate against the
    operator's ACTUAL current account size/caps instead of whatever number
    was baked into a prospectus's prose at draft time, and gives it a single
    boolean to gate MOOMOO_LIVE_TRADING_ENABLED on (doctrine alignment: real-
    money execution unlocks on the SAME 20-trade paper gate that unlocks
    TA's own Phase 2, not a separately-invented criterion).
    """
    exp = expectancy()
    h = heat()
    gate_passed = phase2_gate_passed()
    return {
        "account_equity_usd": ACCOUNT,
        "max_risk_pct_per_trade": RISK_PCT_PER_TRADE,
        "heat_ceiling_pct": HEAT_MAX / ACCOUNT,
        "heat_ceiling_usd": HEAT_MAX,
        "heat_used_usd": h["used"],
        "heat_headroom_usd": h["headroom"],
        "phase2_gate": {
            "closed_trades": exp["n"],
            "target_trades": PHASE2_GATE_TARGET,
            "cum_r": exp["sum_r"],
            "passed": gate_passed,
        },
        # The literal field MooMoo's own live-trading gate should check — named
        # generically (not "phase2_gate_passed") so a reader in a different repo
        # doesn't need to know TA's internal phase-naming to use it correctly.
        "live_trading_unlock_eligible": gate_passed,
        "_generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def write_risk_params():
    payload = risk_params()
    tmp = RISK_PARAMS_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(RISK_PARAMS_JSON)
    return RISK_PARAMS_JSON


def cmd_show():
    s = state()
    h, exp = s["heat"], s["expectancy"]
    print(f"Account: ${ACCOUNT:,.0f}")
    print(f"Heat: ${h['used']:.2f} / ${h['max']:.0f} used ({h['pct_equity']:.2f}% equity), "
          f"headroom ${h['headroom']:.2f}, {h['n_positions']} open position(s)")
    if s["correlation_note"]:
        print(f"  {s['correlation_note']}")
    print(f"Calibration: {exp['n']}/20 closed; "
          f"win {exp['win_rate']}% ; avg {exp['avg_r']}R ; cum {exp['sum_r']:+.2f}R")
    for p in s["open_positions"]:
        print(f"  LIVE {p['ticker']}: entry {p['entry']} stop {p['stop']} risk ${p['dollar_risk']:.2f} [{p['sector']}]")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "state":
        print(json.dumps(state(), indent=2))
    elif cmd == "risk-params":
        print(json.dumps(risk_params(), indent=2))
    elif cmd == "sync":
        p = write_portfolio_md()
        rp = write_risk_params()
        print(f"✓ Synced {p}")
        print(f"✓ Synced {rp}")
        cmd_show()
    else:
        cmd_show()
