#!/usr/bin/env python3
"""Crypto token-unlock cache — Python-callable bridge so the dashboard's
Risk Simulator can run a real §5 48h-halt gate on crypto entries.

The actual unlock data lives on tokenomist.ai, which is a Next.js SPA — direct
urllib scraping doesn't work (no embedded JSON, fetches happen client-side).
This skill is the cache layer: baseline entries for assets with no scheduled
vesting (BTC, ETH, USDC, etc.) ship for free, and per-coin alts (HYPE, ONDO,
…) are populated via the `set` subcommand after running the agent-only
`crypto-unlocks` WebFetch skill.

Source of truth = the JSON files in .claude/cache/crypto_unlocks/{coin}.json
Dashboard sim reads them on build; gate logic is in the sim's JS.

Manual by design — no automation, no cron.
"""

from __future__ import annotations
import argparse, json, sys, re
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = PROJECT_ROOT / ".claude" / "cache" / "crypto_unlocks"
WATCHLIST = PROJECT_ROOT / "watchlist.md"

# Assets with no equity-style vesting — mining emission / native PoS only.
# Treat these as auto-pass on the §5 unlock gate, with a clear "why".
BASELINE_NO_SCHEDULE = {
    "BTC":  "No vesting schedule — mining emission only (~6.25 BTC/block, halving every ~4y).",
    "ETH":  "No vesting schedule — native PoS issuance, no cliff unlocks.",
    "USDC": "Stablecoin — no vesting.",
    "USDT": "Stablecoin — no vesting.",
    "DAI":  "Stablecoin — no vesting.",
}

# Coins with regular linear/scheduled emission that almost never breaches the
# 1%-of-float gate, but still warrant a note. The gate treats these as
# informational warns rather than hard pass — user can override per-trade.
BASELINE_REGULAR_EMISSION = {
    "SOL":  ("Linear monthly inflation (~0.1-0.2%/mo), no large cliffs scheduled. "
             "Verify on tokenomist.ai before sizing >5% account."),
    "BNB":  ("Quarterly burns (deflationary), no team/investor cliffs remaining post-2024."),
    "XRP":  ("Monthly 1B XRP escrow release on the 1st; Ripple re-locks most of it. "
             "Net float change typically <0.5%."),
    "HBAR": ("Monthly treasury unlock; size varies. Verify on tokenomist.ai before entry."),
    "ADA":  ("Treasury emission via Project Catalyst; small, no large cliffs."),
    "DOGE": ("Continuous mining emission (~5B/yr); no vesting."),
}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def coin_path(coin: str) -> Path:
    return CACHE_DIR / f"{coin.upper()}.json"


def write_entry(coin: str, payload: dict) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["coin"] = coin.upper()
    payload.setdefault("_fetched_at", now_utc_iso())
    p = coin_path(coin)
    p.write_text(json.dumps(payload, indent=2))
    return p


def load_entry(coin: str) -> dict | None:
    p = coin_path(coin)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def parse_watchlist_crypto() -> list[str]:
    if not WATCHLIST.exists():
        return []
    out = []
    in_crypto = False
    for line in WATCHLIST.read_text().splitlines():
        s = line.strip()
        if s.startswith("##"):
            in_crypto = "crypto" in s.lower()
            continue
        if in_crypto and s.startswith("- `"):
            m = re.match(r"-\s*`([^`]+)`", s)
            if m:
                out.append(m.group(1).upper())
    return out


def days_until(date_str: str) -> int | None:
    try:
        d = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        return int((d - datetime.now(timezone.utc)).total_seconds() // 86400)
    except Exception:
        return None


def gate_status(entry: dict) -> tuple[str, str]:
    """Return (status, why) where status ∈ {ok, warn, bad}.
    Doctrine §5: new long inside 48h pre-unlock for >1% float = violation.
    """
    if entry is None:
        return ("warn", "no cache entry — run the crypto-unlocks WebFetch skill, then `set` it here")
    if entry.get("_source_type") == "baseline_no_schedule":
        return ("ok", entry.get("notes", "no scheduled unlocks"))
    if entry.get("_source_type") == "baseline_regular":
        return ("warn", entry.get("notes", "regular emission — verify on tokenomist.ai"))
    nu = entry.get("next_unlock")
    if nu is None or not isinstance(nu, dict):
        return ("warn", "no next-unlock data recorded")
    date = nu.get("date")
    pct  = nu.get("pct_of_float")
    typ  = nu.get("type") or "unknown"
    if not date:
        return ("warn", "next-unlock date missing")
    d = days_until(date)
    if d is None:
        return ("warn", f"unparseable date {date!r}")
    if d < 0:
        return ("warn", f"recorded unlock date ({date}) is in the past — refresh entry")
    in_48h = d <= 2
    in_7d  = d <= 7
    pct_str = f"{pct}% float" if pct is not None else "size unknown"
    if in_48h:
        if pct is None:
            return ("bad", f"{typ} unlock in {d}d ({date}); size unknown — treat as inside 48h-halt window per doctrine §5")
        if pct >= 1.0:
            return ("bad", f"{typ} unlock in {d}d ({date}), {pct_str} — inside 48h-halt window (doctrine §5)")
        return ("warn", f"{typ} unlock in {d}d ({date}), {pct_str} — below 1% float, inside 48h window but below halt threshold")
    if in_7d:
        return ("warn", f"{typ} unlock in {d}d ({date}), {pct_str} — outside 48h halt but within trade duration")
    return ("ok", f"next {typ} unlock in {d}d ({date}), {pct_str}")


# ── CLI subcommands ────────────────────────────────────────────────────────

def cmd_baseline(args):
    """Seed the cache with baseline entries for known-schedule coins."""
    n = 0
    for coin, note in BASELINE_NO_SCHEDULE.items():
        write_entry(coin, {
            "_source_type": "baseline_no_schedule",
            "source": "doctrine baseline",
            "notes": note,
            "next_unlock": None,
        })
        n += 1
    for coin, note in BASELINE_REGULAR_EMISSION.items():
        existing = load_entry(coin)
        # Don't overwrite a user-set entry with the baseline note
        if existing and existing.get("_source_type") not in (None, "baseline_regular"):
            continue
        write_entry(coin, {
            "_source_type": "baseline_regular",
            "source": "doctrine baseline",
            "notes": note,
            "next_unlock": None,
        })
        n += 1
    print(f"✓ Seeded {n} baseline entries in {CACHE_DIR}")


def cmd_set(args):
    """Record a per-coin unlock entry (typically after running the WebFetch crypto-unlocks skill)."""
    if not args.date and not args.no_upcoming:
        sys.exit("error: must pass --date YYYY-MM-DD or --no-upcoming")
    if args.no_upcoming:
        payload = {
            "_source_type": "manual",
            "source": args.source or "manual entry",
            "notes": args.notes or "no upcoming cliff unlock per source",
            "next_unlock": None,
        }
    else:
        # Validate date
        try:
            datetime.fromisoformat(args.date)
        except Exception:
            sys.exit(f"error: --date must be ISO YYYY-MM-DD (got {args.date!r})")
        payload = {
            "_source_type": "manual",
            "source": args.source or "manual entry",
            "notes": args.notes or "",
            "next_unlock": {
                "date": args.date,
                "type": args.type or "unknown",
                "pct_of_float": args.pct,
                "tokens": args.tokens,
                "usd_value": args.usd,
                "recipient": args.recipient,
            },
        }
    p = write_entry(args.coin, payload)
    st, why = gate_status(payload)
    icon = {"ok": "✓", "warn": "⚠", "bad": "🛑"}[st]
    print(f"{icon} {args.coin.upper()}  →  {p}")
    print(f"   gate: {st.upper()} — {why}")


def cmd_clear(args):
    if args.all:
        n = 0
        for p in CACHE_DIR.glob("*.json"):
            p.unlink(); n += 1
        print(f"✓ Cleared {n} entries from {CACHE_DIR}")
        return
    if not args.coin:
        sys.exit("error: pass --all or a coin symbol")
    p = coin_path(args.coin)
    if p.exists():
        p.unlink()
        print(f"✓ Removed {p.name}")
    else:
        print(f"(nothing to remove — {p.name} not in cache)")


def cmd_show(args):
    if not CACHE_DIR.exists() or not any(CACHE_DIR.iterdir()):
        print(f"(cache empty — run `baseline` or `set` first; cache dir = {CACHE_DIR})")
        return
    coins = [args.coin.upper()] if args.coin else sorted(p.stem for p in CACHE_DIR.glob("*.json"))
    watchlist = set(parse_watchlist_crypto())
    rows = []
    for c in coins:
        e = load_entry(c)
        if not e: continue
        st, why = gate_status(e)
        in_wl = c in watchlist
        rows.append((c, st, why, e.get("_source_type", "?"), e.get("_fetched_at", ""), in_wl))
    if not rows:
        print("(no entries to show)")
        return
    print(f"{'COIN':<6} {'WL':<3} {'GATE':<5} {'SOURCE':<22} CACHED                   WHY")
    for c, st, why, src, ts, wl in rows:
        icon = {"ok": "✓", "warn": "⚠", "bad": "🛑"}[st]
        wl_mark = "★" if wl else ""
        print(f"{c:<6} {wl_mark:<3} {icon} {st:<3} {src:<22} {ts:<24} {why[:90]}")
    # Missing-from-cache report
    missing = [c for c in sorted(watchlist) if not load_entry(c)]
    if missing:
        print()
        print("Missing from cache (watchlist coins not yet recorded):")
        for c in missing:
            print(f"  - {c}  (run: python3 .claude/skills/crypto-unlocks-cache/crypto_unlocks_cache.py set {c} --date YYYY-MM-DD --pct 1.5 --type cliff)")


def cmd_audit(args):
    """Walk the watchlist and report which coins have/lack an entry."""
    wl = parse_watchlist_crypto()
    if not wl:
        print("(no crypto entries in watchlist.md)")
        return
    print(f"Watchlist crypto coins: {len(wl)}")
    for c in wl:
        e = load_entry(c)
        st, why = gate_status(e)
        icon = {"ok": "✓", "warn": "⚠", "bad": "🛑"}[st]
        src = (e or {}).get("_source_type", "—")
        print(f"  {icon} {c:<6} ({st}, {src})  {why[:80]}")


def main():
    ap = argparse.ArgumentParser(prog="crypto_unlocks_cache.py",
                                 description="Crypto token-unlock cache for the dashboard's Risk Simulator §5 gate.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("baseline", help="Seed cache with baseline entries for BTC/ETH/SOL/BNB/XRP/HBAR/stables").set_defaults(func=cmd_baseline)

    sp = sub.add_parser("set", help="Record an unlock entry for a coin (typically after WebFetch crypto-unlocks)")
    sp.add_argument("coin")
    sp.add_argument("--date", help="ISO YYYY-MM-DD next unlock date")
    sp.add_argument("--no-upcoming", action="store_true", help="Record explicitly that there's no upcoming unlock")
    sp.add_argument("--type", choices=["cliff", "linear", "treasury", "unknown"], help="Unlock type")
    sp.add_argument("--pct", type=float, help="% of circulating supply")
    sp.add_argument("--tokens", type=float, help="Number of tokens unlocking")
    sp.add_argument("--usd", type=float, help="USD value of unlock")
    sp.add_argument("--recipient", help="team / investors / treasury / community")
    sp.add_argument("--source", help="URL the data came from (e.g. tokenomist.ai/hyperliquid)")
    sp.add_argument("--notes", help="Free-text notes")
    sp.set_defaults(func=cmd_set)

    sp = sub.add_parser("clear", help="Remove cache entries")
    sp.add_argument("coin", nargs="?")
    sp.add_argument("--all", action="store_true")
    sp.set_defaults(func=cmd_clear)

    sp = sub.add_parser("show", help="Print current cache state")
    sp.add_argument("coin", nargs="?")
    sp.set_defaults(func=cmd_show)

    sub.add_parser("audit", help="Walk watchlist and report which coins need entries").set_defaults(func=cmd_audit)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
