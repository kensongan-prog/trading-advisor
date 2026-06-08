#!/usr/bin/env python3
"""
stocktwits_sentiment.py — Manually refresh retail sentiment from StockTwits.

Free public API (no auth). Sibling of reddit_sentiment.py in Phase A. Captures
user-tagged Bull/Bear labels + raw message bodies for downstream LLM scoring.

Manual (no automation). Output: .claude/cache/stocktwits_sentiment/{ticker}.json.

Usage:
    python3 .claude/skills/stocktwits-sentiment/stocktwits_sentiment.py             # all watchlist
    python3 .claude/skills/stocktwits-sentiment/stocktwits_sentiment.py NVDA BTC    # specific
    python3 .claude/skills/stocktwits-sentiment/stocktwits_sentiment.py --show
    python3 .claude/skills/stocktwits-sentiment/stocktwits_sentiment.py --show NVDA
    python3 .claude/skills/stocktwits-sentiment/stocktwits_sentiment.py --clear
"""

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
WATCHLIST_PATH = PROJECT_ROOT / "watchlist.md"
CACHE_DIR = PROJECT_ROOT / ".claude" / "cache" / "stocktwits_sentiment"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

UA = "trading-advisor/0.1 (stocktwits-sentiment)"
DEFAULT_DELAY_SEC = 0.5  # StockTwits is more permissive than Reddit
BASE = "https://api.stocktwits.com/api/2/streams/symbol"

# Crypto tickers from our watchlist that need the .X suffix on StockTwits.
# (Aligned with reddit-sentiment CRYPTO_META keys.)
CRYPTO_TICKERS = {"BTC", "ETH", "SOL", "BNB", "XRP", "HBAR", "HYPE", "ENA"}


# ── Classification ─────────────────────────────────────────────────────────
def classify_ticker(ticker):
    t = ticker.upper().strip()
    if t.endswith(".KL") or (t.replace(".KL", "").isdigit() and len(t.replace(".KL", "")) == 4):
        return "klse"
    if t in CRYPTO_TICKERS:
        return "crypto"
    return "us_equity"


def stocktwits_symbol(ticker):
    """Map our internal ticker to the StockTwits symbol form."""
    t = ticker.upper().strip()
    cls = classify_ticker(t)
    if cls == "crypto":
        return f"{t}.X"
    if cls == "klse":
        return None  # no coverage on StockTwits
    return t  # US equity


# ── HTTP ──────────────────────────────────────────────────────────────────
def fetch_stream(st_symbol, timeout=15):
    url = f"{BASE}/{st_symbol}.json"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace")), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ── Per-ticker fetch ───────────────────────────────────────────────────────
def fetch_ticker(ticker, verbose=True):
    cls = classify_ticker(ticker)
    st_sym = stocktwits_symbol(ticker)
    base = {
        "ticker": ticker.upper(),
        "asset_class": cls,
        "stocktwits_symbol": st_sym,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }

    if st_sym is None:
        if verbose:
            print(f"  [st] {ticker}: no coverage (KLSE)")
        return {**base, "no_coverage": True, "message_count": 0, "watchers": None,
                "tagged_counts": {"Bullish": 0, "Bearish": 0, "untagged": 0},
                "tagged_bull_pct": None, "messages": [], "error": None}

    if verbose:
        print(f"  [st] {ticker} ({st_sym}) ... ", end="", flush=True)

    data, err = fetch_stream(st_sym)
    if err:
        if verbose:
            print(f"ERR ({err})")
        # 404 = no symbol — treat as no_coverage rather than error noise
        no_cov = err.startswith("HTTP 404")
        return {**base, "no_coverage": no_cov, "message_count": 0, "watchers": None,
                "tagged_counts": {"Bullish": 0, "Bearish": 0, "untagged": 0},
                "tagged_bull_pct": None, "messages": [], "error": None if no_cov else err}

    raw_msgs = data.get("messages") or []
    sym_meta = data.get("symbol") or {}
    watchers = sym_meta.get("watchlist_count")

    msgs = []
    bull = bear = untagged = 0
    for m in raw_msgs:
        entities = m.get("entities") or {}
        sentiment_obj = entities.get("sentiment") or {}
        tagged = sentiment_obj.get("basic")  # "Bullish" | "Bearish" | None
        if tagged == "Bullish":
            bull += 1
        elif tagged == "Bearish":
            bear += 1
        else:
            untagged += 1
        user_obj = m.get("user") or {}
        msgs.append({
            "id": m.get("id"),
            "body": (m.get("body") or "").strip(),
            "created_at": m.get("created_at"),
            "user": user_obj.get("username"),
            "tagged_sentiment": tagged,
            "likes": (m.get("likes") or {}).get("total", 0) if isinstance(m.get("likes"), dict) else 0,
            "reshares": (m.get("reshares") or {}).get("reshared_count", 0) if isinstance(m.get("reshares"), dict) else 0,
        })

    total_tagged = bull + bear
    bull_pct = round(bull / total_tagged, 3) if total_tagged > 0 else None

    if verbose:
        if total_tagged:
            print(f"{len(msgs)} msgs, {bull}B/{bear}b ({bull_pct:.0%} bull), watchers={watchers}")
        else:
            print(f"{len(msgs)} msgs (none tagged), watchers={watchers}")

    return {
        **base,
        "no_coverage": False,
        "message_count": len(msgs),
        "watchers": watchers,
        "tagged_counts": {"Bullish": bull, "Bearish": bear, "untagged": untagged},
        "tagged_bull_pct": bull_pct,
        "messages": msgs,
        "error": None,
    }


# ── Watchlist parsing ──────────────────────────────────────────────────────
def parse_watchlist():
    if not WATCHLIST_PATH.exists():
        return []
    text = WATCHLIST_PATH.read_text(encoding="utf-8")
    tickers = []
    for m in re.finditer(r"^\s*-\s*`([^`]+)`", text, re.MULTILINE):
        sym = m.group(1).strip().upper()
        # Skip the literal `TICKER` placeholder from the watchlist's Format: example line
        if sym and not sym.startswith("_") and sym != "TICKER":
            tickers.append(sym)
    seen, out = set(), []
    for t in tickers:
        if t not in seen:
            seen.add(t); out.append(t)
    return out


# ── Cache I/O ──────────────────────────────────────────────────────────────
def cache_path(ticker):
    safe = ticker.upper().replace("/", "_").replace("\\", "_")
    return CACHE_DIR / f"{safe}.json"


def save_cache(ticker, data):
    cache_path(ticker).write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_cache(ticker):
    p = cache_path(ticker)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── Commands ──────────────────────────────────────────────────────────────
def cmd_refresh(tickers, delay=DEFAULT_DELAY_SEC):
    if not tickers:
        tickers = parse_watchlist()
        if not tickers:
            print("ERROR: no tickers passed and watchlist.md empty/missing", file=sys.stderr)
            return 1
        print(f"Refreshing {len(tickers)} tickers from watchlist.md")
    else:
        print(f"Refreshing {len(tickers)} tickers: {' '.join(tickers)}")

    summary = []
    for i, t in enumerate(tickers, 1):
        print(f"\n[{i}/{len(tickers)}] {t}")
        result = fetch_ticker(t, verbose=True)
        save_cache(t, result)
        summary.append(result)
        time.sleep(delay)

    print("\n── Summary " + "─" * 60)
    print(f"{'TICKER':<10}{'CLASS':<10}{'MSGS':>6}{'BULL%':>8}{'WATCHERS':>12}  STATUS")
    for r in summary:
        bp = f"{r['tagged_bull_pct']:.0%}" if r['tagged_bull_pct'] is not None else "—"
        w = r['watchers'] if r['watchers'] is not None else "—"
        status = "no_coverage" if r.get("no_coverage") else ("error" if r.get("error") else "ok")
        print(f"{r['ticker']:<10}{r['asset_class']:<10}{r['message_count']:>6}{bp:>8}{str(w):>12}  {status}")
    print()
    return 0


def cmd_show(tickers):
    if tickers:
        for t in tickers:
            d = load_cache(t)
            if not d:
                print(f"{t}: no cache entry")
                continue
            print(f"\n── {t} ({d['asset_class']}, ST sym: {d['stocktwits_symbol']}) — fetched {d['fetched_at']} ──")
            if d.get("no_coverage"):
                print("  no coverage on StockTwits")
                continue
            print(f"  watchers: {d['watchers']}  |  messages: {d['message_count']}  |  tagged: {d['tagged_counts']}")
            bp = d['tagged_bull_pct']
            print(f"  bull% (of tagged): {bp:.1%}" if bp is not None else "  bull%: — (no tagged messages)")
            print("  recent messages:")
            for m in d['messages'][:5]:
                tag = f"[{m['tagged_sentiment']}]" if m['tagged_sentiment'] else "[-]"
                print(f"    {tag} @{m['user']}: {m['body'][:100]}")
        return 0

    print(f"{'TICKER':<10}{'CLASS':<10}{'MSGS':>6}{'BULL%':>8}{'WATCHERS':>12}  FETCHED")
    files = sorted(CACHE_DIR.glob("*.json"))
    if not files:
        print("(cache empty)")
        return 0
    for p in files:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            bp = f"{d['tagged_bull_pct']:.0%}" if d.get('tagged_bull_pct') is not None else "—"
            w = d.get('watchers') if d.get('watchers') is not None else "—"
            print(f"{d['ticker']:<10}{d['asset_class']:<10}{d['message_count']:>6}{bp:>8}{str(w):>12}  {d['fetched_at']}")
        except Exception as e:
            print(f"{p.stem}: (unreadable: {e})")
    return 0


def cmd_clear():
    files = list(CACHE_DIR.glob("*.json"))
    for p in files:
        p.unlink()
    print(f"Cleared {len(files)} cache files from {CACHE_DIR}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="*")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY_SEC)
    args = ap.parse_args()
    if args.clear:
        return cmd_clear()
    if args.show:
        return cmd_show([t.upper() for t in args.tickers])
    return cmd_refresh([t.upper() for t in args.tickers], delay=args.delay)


if __name__ == "__main__":
    sys.exit(main())
