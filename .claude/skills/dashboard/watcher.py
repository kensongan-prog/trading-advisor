#!/usr/bin/env python3
"""
watcher.py — level/alert watcher. Never trades; it just makes sure you're
present when a level prints.

What it watches (US equities only — Finnhub free tier, 60 calls/min):
  1. PROSPECTUS journal entries → fires when price crosses ABOVE the entry
     trigger zone (the breakout that's been sitting unwatched).
  2. LIVE journal entries → fires on STOP hit (price ≤ stop) and TP touch
     (price ≥ TP1 / TP2).
  3. Watchlist names → fires when a name enters the Phase-1 entry band
     (RSI 35-50 AND price > SMA50 > SMA200), read from the dashboard cache.

Each distinct alert fires once per day (deduped in a state file), so a 60s
loop doesn't spam you. macOS notification via osascript; also printed.

Doctrine-clean: read-only, no orders, no journal writes. It points you at the
tape; you decide.

Usage:
  python3 watcher.py --once                 # single scan, notify + print
  python3 watcher.py --once --no-notify      # single scan, print only (testing)
  python3 watcher.py                         # loop every 60s during US market hours
  python3 watcher.py --interval 120 --ignore-hours
"""

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILLS_DIR.parent.parent
JOURNAL_DIR = PROJECT_ROOT / "journal"
WATCHLIST_MD = PROJECT_ROOT / "watchlist.md"
DASH_CACHE = PROJECT_ROOT / ".claude" / "cache" / "dashboard"
STATE_DIR = PROJECT_ROOT / ".claude" / "cache" / "watcher"
STATE_FILE = STATE_DIR / "fired.json"

sys.path.insert(0, str(SKILLS_DIR / "finnhub"))
import finnhub_client as fc  # noqa: E402


# ── US market-hours gate (ET, ignoring half-day holidays — close enough) ────
def us_market_open(now_utc=None):
    now = now_utc or datetime.now(timezone.utc)
    et = now.astimezone(timezone(timedelta(hours=-4)))  # EDT; project runs Jun (DST)
    if et.weekday() >= 5:
        return False
    open_t = et.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = et.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_t <= et <= close_t


# ── Journal level extraction ────────────────────────────────────────────────
# Only currency-marked numbers are real levels — avoids "20-EMA", "1.5× ATR",
# "Jun 17", "2R" etc. being read as prices.
MONEY_RE = re.compile(r"(?:\$|MYR\s*)\s*([0-9]+(?:\.[0-9]+)?)")


def _floats(s):
    return [float(x) for x in MONEY_RE.findall(s)]


def parse_levels(text):
    """Pull entry-zone-high, stop, tp1, tp2 out of a prospectus markdown table.

    Keys on the standard Entry/Stop/TP1/TP2 table rows. Returns a dict with
    whatever it found (missing keys absent). Bold **$X** values preferred.
    """
    out = {}
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        # A well-formed row splits to ['', label, value, logic, ''] → ≥4 cells
        if len(cells) < 4:
            continue
        label = cells[1].lower()
        value = cells[2]
        nums = _floats(value)
        if not nums:
            continue  # e.g. TP2 "trail behind 20-EMA" — no number to watch
        if label.startswith("entry trigger") and "entry" not in out:
            out["entry"] = max(nums)  # zone high = breakout level
        elif label.startswith("stop") and "stop" not in out:
            out["stop"] = nums[0]
        elif label.startswith("tp1") and "tp1" not in out:
            out["tp1"] = nums[0]
        elif label.startswith("tp2") and "tp2" not in out:
            out["tp2"] = nums[0]
    return out


def load_journal_targets():
    """Return list of {ticker, kind: prospectus|live, levels:{...}}."""
    targets = []
    if not JOURNAL_DIR.is_dir():
        return targets
    for p in sorted(JOURNAL_DIR.glob("*.md")):
        if p.name.startswith("_") or p.name.lower() == "readme.md":
            continue
        txt = p.read_text()
        m = re.search(r"\*\*Status:\*\*\s*([^\n]+)", txt)
        status = (m.group(1) if m else "").upper()
        mt = re.match(r"\d{4}-\d{2}-\d{2}_(.+)", p.stem)
        ticker = (mt.group(1) if mt else p.stem).replace("_", ".")
        # Only US equities (skip .KL and crypto-looking entries — watcher is US-only)
        if ticker.endswith(".KL"):
            continue
        if "CLOSED" in status or "DEAD" in status:
            continue
        # LIVE only when it's the leading status token, not prose like
        # "convert to live entry when trigger fires".
        kind = "live" if re.match(r"\s*LIVE\b", status) else "prospectus"
        levels = parse_levels(txt)
        if levels:
            targets.append({"ticker": ticker.upper(), "kind": kind,
                            "levels": levels, "file": p.name})
    return targets


def load_watchlist_us():
    if not WATCHLIST_MD.is_file():
        return []
    text = WATCHLIST_MD.read_text()
    out, in_us = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            h = line[3:].lower()
            in_us = ("equities" in h or "etf" in h)
            continue
        if in_us:
            m = re.match(r"\s*-\s*`([^`]+)`", line)
            if m:
                t = m.group(1).strip().upper()
                if t.lower() != "ticker":
                    out.append(t)
    return out


def load_ticker_cache(ticker):
    key = ticker.replace(".", "_")
    p = DASH_CACHE / f"yfin_{key}.json"
    if p.is_file():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return None
    return None


# ── Dedupe state ────────────────────────────────────────────────────────────
def load_state():
    if STATE_FILE.is_file():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1))


def already_fired(state, key):
    """Fired today already?"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return state.get(key) == today


def mark_fired(state, key):
    state[key] = datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── Notification ────────────────────────────────────────────────────────────
def notify(title, message, do_notify=True):
    line = f"🔔 {title} — {message}"
    print(line, flush=True)
    if do_notify and sys.platform == "darwin":
        safe_t = title.replace('"', "'")
        safe_m = message.replace('"', "'")
        try:
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{safe_m}" with title "{safe_t}" sound name "Glass"'],
                check=False, capture_output=True, timeout=5)
        except Exception:
            pass


# ── One scan ────────────────────────────────────────────────────────────────
def scan(state, do_notify=True):
    """Run one pass over journal targets + watchlist. Returns list of fired alerts."""
    fired = []
    journal = load_journal_targets()
    watchlist = load_watchlist_us()

    # Unique tickers needing a live quote (journal targets only — watchlist P1
    # band uses cached RSI, no quote needed).
    quote_cache = {}

    def get_quote(t):
        if t not in quote_cache:
            q, err = fc.quote(t)
            quote_cache[t] = (q if (q and not err) else None)
        return quote_cache[t]

    # 1 + 2: journal targets
    for tg in journal:
        t = tg["ticker"]
        lv = tg["levels"]
        q = get_quote(t)
        if not q:
            continue
        price = q.get("c")
        high = q.get("h", price)
        low = q.get("l", price)
        if not price:
            continue

        if tg["kind"] == "prospectus" and "entry" in lv:
            # Breakout: intraday high tagged or crossed the entry trigger level
            if high >= lv["entry"]:
                key = f"{t}:entry:{lv['entry']}"
                if not already_fired(state, key):
                    notify(f"{t} ENTRY TRIGGER",
                           f"tagged ${lv['entry']:.2f} (now ${price:.2f}). Prospectus {tg['file']} — check for the close confirmation.",
                           do_notify)
                    mark_fired(state, key); fired.append(key)

        if tg["kind"] == "live":
            if "stop" in lv and low <= lv["stop"]:
                key = f"{t}:stop:{lv['stop']}"
                if not already_fired(state, key):
                    notify(f"{t} ⚠ STOP HIT",
                           f"traded ${low:.2f} ≤ stop ${lv['stop']:.2f} (now ${price:.2f}). Doctrine: exit, no 'give it another day'.",
                           do_notify)
                    mark_fired(state, key); fired.append(key)
            for tp in ("tp1", "tp2"):
                if tp in lv and high >= lv[tp]:
                    key = f"{t}:{tp}:{lv[tp]}"
                    if not already_fired(state, key):
                        notify(f"{t} 🎯 {tp.upper()} TOUCH",
                               f"tagged ${lv[tp]:.2f} (now ${price:.2f}). Scale / trail per plan.",
                               do_notify)
                        mark_fired(state, key); fired.append(key)

    # 3: watchlist P1 entry band (from dashboard cache — no quote burn)
    CONTEXT_TICKERS = {"SPY", "QQQ", "DIA", "IWM"}  # reference, not entry candidates
    for t in watchlist:
        if t in CONTEXT_TICKERS:
            continue
        c = load_ticker_cache(t)
        if not c:
            continue
        rsi = c.get("rsi14")
        price = c.get("price")
        s50 = c.get("sma50")
        s200 = c.get("sma200")
        if None in (rsi, price, s50, s200):
            continue
        trend_ok = price > s50 > s200
        in_band = 35 <= rsi <= 50
        if trend_ok and in_band:
            key = f"{t}:p1band"
            if not already_fired(state, key):
                notify(f"{t} 📐 P1 ENTRY BAND",
                       f"RSI {rsi:.1f} (35-50) with trend intact (px>{s50:.2f}>{s200:.2f}). Candidate for the Setup Queue — verify on the dashboard.",
                       do_notify)
                mark_fired(state, key); fired.append(key)

    return fired


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="Single scan then exit")
    ap.add_argument("--interval", type=int, default=60, help="Loop interval seconds (default 60)")
    ap.add_argument("--no-notify", action="store_true", help="Print only, no macOS notification")
    ap.add_argument("--ignore-hours", action="store_true", help="Scan even when US market closed")
    args = ap.parse_args()

    if not fc.is_configured():
        sys.exit("ERROR: FINNHUB_API_KEY not set (drop it into .claude/skills/finnhub/.env)")

    do_notify = not args.no_notify

    def one():
        if not args.ignore_hours and not us_market_open():
            print(f"[{datetime.now().strftime('%H:%M:%S')}] US market closed — skipping (use --ignore-hours to override)", flush=True)
            return
        state = load_state()
        fired = scan(state, do_notify)
        save_state(state)
        if not fired:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] scan clean — no new levels", flush=True)

    if args.once:
        one()
        return
    print(f"watcher running — interval {args.interval}s, US market hours{' (bypassed)' if args.ignore_hours else ''}. Ctrl-C to stop.", flush=True)
    try:
        while True:
            one()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nwatcher stopped.")


if __name__ == "__main__":
    main()
