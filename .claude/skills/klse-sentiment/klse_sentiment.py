#!/usr/bin/env python3
"""klse_sentiment.py — KLSE community-comment fetcher (klsescreener).

Raw-fetch leg for KLSE retail sentiment — the Bursa-native equivalent of
stocktwits-sentiment / reddit-sentiment, filling the gap those leave (StockTwits
404s on Bursa codes; Reddit r/Bursa_Malaysia is thin). klsescreener hosts a
per-stock community comment thread with real, multilingual (English/Chinese/Malay)
retail chatter and no login wall.

Full thread endpoint (discovered 2026-07-01; the AJAX pager was deprecated — see
notes/learned.md): /v2/comments/all/stock/{code}. Server-rendered HTML, urllib +
regex. We parse (body, date), keep only comments inside a recent window (default
180 days), and write a raw cache in the shape the sentiment-cache LLM scorer
consumes (messages[].body + asset_class + no_coverage), so `process_klse` in
sentiment_cache can score it into the §4 composite. Manual by design — no cron.

Usage:
  python3 klse_sentiment.py               # all KLSE codes in watchlist, 180d
  python3 klse_sentiment.py 9431 5099     # specific Bursa codes
  python3 klse_sentiment.py --days 90     # tighter window
  python3 klse_sentiment.py --show        # print cached values, no fetch
  python3 klse_sentiment.py --clear       # wipe cache
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
WATCHLIST_PATH = PROJECT_ROOT / "watchlist.md"
CACHE_DIR = PROJECT_ROOT / ".claude" / "cache" / "klse_sentiment"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36"
DEFAULT_DELAY_SEC = 1.2
DEFAULT_WINDOW_DAYS = 180
MAX_MESSAGES = 60  # matches sentiment_cache MAX_MESSAGES_PER_TICKER


# ── HTTP ──────────────────────────────────────────────────────────────────
def fetch_page(code, timeout=20):
    url = f"https://www.klsescreener.com/v2/comments/all/stock/{code}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ── Parsing ───────────────────────────────────────────────────────────────
# Each comment/reply carries etime="YYYY-MM-DD HH:MM:SS +0800" then a
# <div class="comment-message ...">TEXT</div>. Pair each etime with its NEXT
# comment-message, never crossing another etime (the (?:(?!etime=).)*? guard).
COMMENT_RE = re.compile(
    r'etime="(\d{4}-\d{2}-\d{2})[^"]*"'
    r'(?:(?!etime=).)*?'
    r'class="comment-message[^"]*"[^>]*>(.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)


def _clean(text):
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)          # strip tags (links, emoji imgs)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_comments(page):
    """Return list of {date, body}, in document order (newest-first as rendered)."""
    out = []
    for date, raw in COMMENT_RE.findall(page):
        body = _clean(raw)
        if body:
            out.append({"date": date, "body": body})
    return out


def _within_window(date_str, cutoff):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date() >= cutoff
    except Exception:
        return False


# ── Watchlist ───────────────────────────────────────────────────────────────
def klse_codes_from_watchlist():
    codes = []
    if not WATCHLIST_PATH.exists():
        return codes
    in_klse = False
    for line in WATCHLIST_PATH.read_text().splitlines():
        if line.startswith("## "):
            h = re.sub(r"^#+\s*", "", line).strip().lower()
            in_klse = h.startswith("klse") or h.startswith("bursa") or h.startswith("malaysia")
            continue
        if not in_klse or not line.strip():
            continue
        m = re.match(r"\s*-\s*`([^`]+)`", line)
        if m:
            tk = m.group(1).strip().upper()
            if tk.endswith(".KL"):
                tk = tk[:-3]
            if tk.isdigit():
                codes.append(tk.zfill(4))
    return codes


# ── Cache ─────────────────────────────────────────────────────────────────
def cache_path(code):
    return CACHE_DIR / f"{code}.json"


def write_cache(code, payload):
    payload = dict(payload)
    payload["_fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cache_path(code).write_text(json.dumps(payload, indent=2, default=str, ensure_ascii=False))


def read_cache(code):
    p = cache_path(code)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


# ── Commands ──────────────────────────────────────────────────────────────
def refresh_one(code, window_days):
    from datetime import date, timedelta
    cutoff = date.today() - timedelta(days=window_days)
    page, err = fetch_page(code)
    if err:
        # 404 = no comment thread for this code → treat as no_coverage, not error noise
        no_cov = err.startswith("HTTP 404")
        payload = {"ticker": code, "asset_class": "klse", "window_days": window_days,
                   "messages": [], "message_count": 0,
                   "no_coverage": no_cov, "error": None if no_cov else err}
        write_cache(code, payload)
        return payload
    all_msgs = parse_comments(page)
    msgs = [m for m in all_msgs if _within_window(m["date"], cutoff)][:MAX_MESSAGES]
    payload = {
        "ticker": code,
        "asset_class": "klse",
        "window_days": window_days,
        "messages": msgs,
        "message_count": len(msgs),
        "total_on_page": len(all_msgs),
        "no_coverage": len(msgs) == 0,
        "error": None,
    }
    write_cache(code, payload)
    return payload


def cmd_refresh(codes, window_days, delay):
    if not codes:
        print("No KLSE codes provided and none found in watchlist.md.")
        return 1
    print(f"Fetching KLSE comments for {len(codes)} ticker(s), window {window_days}d: {', '.join(codes)}")
    n_ok = n_fail = 0
    for i, code in enumerate(codes):
        p = refresh_one(code, window_days)
        if p.get("error"):
            n_fail += 1
            print(f"  {code}: ERROR {p['error']}")
        else:
            n_ok += 1
            tag = "no coverage" if p["no_coverage"] else f"{p['message_count']} msg(s) in {window_days}d (of {p['total_on_page']} on page)"
            print(f"  {code}: {tag}")
        if i < len(codes) - 1:
            time.sleep(delay)
    print(f"\n✓ Done. {n_ok} ok, {n_fail} failed. Cache: {CACHE_DIR.relative_to(PROJECT_ROOT)}")
    return 0


def cmd_show(codes):
    if not codes:
        codes = [p.stem for p in sorted(CACHE_DIR.glob("*.json"))]
    if not codes:
        print("No cached KLSE comments.")
        return 0
    for code in codes:
        c = read_cache(code)
        if not c:
            print(f"{code}: (no cache)")
            continue
        tag = "no coverage" if c.get("no_coverage") else f"{c.get('message_count', 0)} msgs ({c.get('window_days')}d)"
        print(f"\n{code} — {tag} · fetched {c.get('_fetched_at', '?')}")
        for m in (c.get("messages") or [])[:6]:
            print(f"   {m['date']}  {m['body'][:80]}")
    return 0


def cmd_clear():
    n = 0
    for p in CACHE_DIR.glob("*.json"):
        p.unlink()
        n += 1
    print(f"Cleared {n} cache file(s).")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Fetch KLSE community comments from klsescreener into a local cache.")
    ap.add_argument("codes", nargs="*", help="Bursa codes (default: all KLSE in watchlist)")
    ap.add_argument("--days", type=int, default=DEFAULT_WINDOW_DAYS, help="Recency window in days (default 180)")
    ap.add_argument("--show", action="store_true", help="Display cached values, no fetch")
    ap.add_argument("--clear", action="store_true", help="Wipe cache and exit")
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY_SEC)
    args = ap.parse_args()

    codes = [c[:-3] if c.upper().endswith(".KL") else c for c in args.codes]
    codes = [c.zfill(4) for c in codes if c.isdigit()] or klse_codes_from_watchlist()

    if args.clear:
        return cmd_clear()
    if args.show:
        return cmd_show(codes)
    return cmd_refresh(codes, args.days, args.delay)


if __name__ == "__main__":
    sys.exit(main())
