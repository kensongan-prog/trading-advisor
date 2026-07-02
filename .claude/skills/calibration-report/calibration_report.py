#!/usr/bin/env python3
"""
calibration_report.py — Analysis C1: the outcome engine.

Buckets CLOSED journal entries' realized R by the gate state captured at
entry (RSI band, sentiment flag, RS-vs-SPY leader/laggard, sector,
structural-quality flags) so the operator can see which entry conditions
actually produce edge, not just an aggregate win-rate/expectancy number.

Reuses portfolio.closed_trades() for the closed-trade list (ticker/date/
result/R), then re-reads each journal file's Data snapshot table for the
entry-time context fields (added 2026-07-02 — closed trades from before
that date will show "unknown" for sector/sentiment/RS).

CLI:
  python3 calibration_report.py report          # human-readable report
  python3 calibration_report.py report --json    # machine-readable
"""
import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SKILLS_DIR / "dashboard"))
import portfolio  # noqa: E402

MIN_N = 3  # below this, a bucket's stats are shown but flagged low-confidence


def _table_field(txt, label):
    """Value cell of a '| Label | Value | ... |' row in the Data snapshot table."""
    for line in txt.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) >= 3 and cells[1].lower() == label.lower():
            return cells[2] or None
    return None


def _rsi_band(rsi_str):
    if not rsi_str or rsi_str == "—":
        return "unknown"
    m = re.search(r"[0-9]+(?:\.[0-9]+)?", rsi_str)
    if not m:
        return "unknown"
    v = float(m.group(0))
    if v < 30:
        return "<30 (oversold)"
    if v < 50:
        return "30-50"
    if v < 70:
        return "50-70"
    return ">=70 (overbought)"


def _rs_bucket(rs_str):
    if not rs_str or rs_str == "—":
        return "unknown"
    m = re.search(r"[+-]?[0-9]+(?:\.[0-9]+)?", rs_str)
    if not m:
        return "unknown"
    v = float(m.group(0))
    if v > 0:
        return "leader (RS>0)"
    if v < 0:
        return "laggard (RS<0)"
    return "flat (RS=0)"


def closed_entries_with_context():
    """Every CLOSED-with-a-realized-R journal entry, with entry-time gate state."""
    out = []
    for c in portfolio.closed_trades():
        if c["r"] is None:
            continue
        txt = (portfolio.JOURNAL_DIR / c["file"]).read_text()
        out.append({
            "ticker": c["ticker"],
            "date": c["date"],
            "r": c["r"],
            "rsi_band": _rsi_band(_table_field(txt, "RSI(14) daily")),
            "sentiment_flag": _table_field(txt, "Sentiment flag") or "unknown",
            "rs_bucket": _rs_bucket(_table_field(txt, "RS vs SPY (1m)")),
            "sector": _table_field(txt, "Sector") or "unknown",
            "has_quality_flags": "### Structural risk flags" in txt,
        })
    return out


def _bucket_stats(entries, key_fn):
    buckets = {}
    for e in entries:
        buckets.setdefault(key_fn(e), []).append(e["r"])
    out = {}
    for k, rs in buckets.items():
        n = len(rs)
        wins = sum(1 for r in rs if r > 0)
        out[k] = {
            "n": n,
            "win_rate": round(wins / n * 100, 1),
            "avg_r": round(sum(rs) / n, 3),
            "sum_r": round(sum(rs), 2),
            "low_confidence": n < MIN_N,
        }
    return out


def build_report():
    entries = closed_entries_with_context()
    return {
        "n_closed": len(entries),
        "min_n_for_confidence": MIN_N,
        "overall": _bucket_stats(entries, lambda e: "all") if entries else {},
        "by_rsi_band": _bucket_stats(entries, lambda e: e["rsi_band"]),
        "by_sentiment_flag": _bucket_stats(entries, lambda e: e["sentiment_flag"]),
        "by_rs_bucket": _bucket_stats(entries, lambda e: e["rs_bucket"]),
        "by_sector": _bucket_stats(entries, lambda e: e["sector"]),
        "by_structural_quality": _bucket_stats(
            entries, lambda e: "has flags" if e["has_quality_flags"] else "clean"
        ),
    }


def _fmt_bucket_table(title, buckets):
    lines = [f"\n{title}"]
    if not buckets:
        lines.append("  (no closed trades yet)")
        return "\n".join(lines)
    for k, s in sorted(buckets.items(), key=lambda kv: -kv[1]["n"]):
        flag = f"  ⚠ low-confidence (n<{MIN_N})" if s["low_confidence"] else ""
        lines.append(
            f"  {k:<24} n={s['n']:<3} win={s['win_rate']:>5}%  "
            f"avg={s['avg_r']:+.2f}R  sum={s['sum_r']:+.2f}R{flag}"
        )
    return "\n".join(lines)


def print_report(rep):
    print(f"Calibration report — {rep['n_closed']} closed trade(s) toward the 20-trade Phase-2 gate.")
    if rep["n_closed"] == 0:
        print("No closed trades yet — nothing to bucket.")
        return
    o = rep["overall"]["all"]
    print(f"\nOverall: n={o['n']}  win_rate={o['win_rate']}%  avg_r={o['avg_r']:+.2f}R  sum_r={o['sum_r']:+.2f}R")
    print(_fmt_bucket_table("By RSI band at entry:", rep["by_rsi_band"]))
    print(_fmt_bucket_table("By sentiment flag at entry:", rep["by_sentiment_flag"]))
    print(_fmt_bucket_table("By RS vs SPY (1m) at entry:", rep["by_rs_bucket"]))
    print(_fmt_bucket_table("By sector:", rep["by_sector"]))
    print(_fmt_bucket_table("By structural-quality flags at entry:", rep["by_structural_quality"]))
    print(f"\nNote: buckets with n<{MIN_N} are directional only, not yet statistically meaningful.")
    print("Sector/sentiment/RS-vs-SPY are only captured for prospectuses created after 2026-07-02 "
          "— older closed trades show 'unknown' for those dimensions.")


def cmd_report(args):
    rep = build_report()
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print_report(rep)
    return 0


def main():
    ap = argparse.ArgumentParser(description="Bucket closed-trade outcomes by entry-time gate state.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("report", help="Print the calibration report")
    rp.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    rp.set_defaults(func=cmd_report)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
