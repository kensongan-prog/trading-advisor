#!/usr/bin/env python3
"""
hn_sentiment.py — Manually refresh Hacker News sentiment for watchlist tickers.

Raw-fetch leg of the three-source retail sentiment composite. HN tends to
carry more substantive technical opinion than Reddit / StockTwits, especially
on tech-stack names (RDDT, MRVL, RKLB, NVDA-class) and crypto majors.

This is the FETCHER ONLY — sentiment scoring happens in `sentiment-cache`
(LLM-scored alongside Reddit + StockTwits, with engagement weighting).

Source: Algolia HN search API (free, no auth, no rate limit at retail scale).

Usage:
    python3 .claude/skills/hn-sentiment/hn_sentiment.py             # all watchlist
    python3 .claude/skills/hn-sentiment/hn_sentiment.py NVDA RDDT   # specific tickers
    python3 .claude/skills/hn-sentiment/hn_sentiment.py --show      # all cached
    python3 .claude/skills/hn-sentiment/hn_sentiment.py --show RDDT # one ticker detail
    python3 .claude/skills/hn-sentiment/hn_sentiment.py --clear     # wipe cache
    python3 .claude/skills/hn-sentiment/hn_sentiment.py --force NVDA  # bypass cache age
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
WATCHLIST_PATH = PROJECT_ROOT / "watchlist.md"
CACHE_DIR = PROJECT_ROOT / ".claude" / "cache" / "hn_sentiment"

ALGOLIA_SEARCH = "https://hn.algolia.com/api/v1/search_by_date"
ALGOLIA_ITEM   = "https://hn.algolia.com/api/v1/items"

LOOKBACK_DAYS = 30
TOP_STORIES = 5            # fetch comment trees for top N stories
TOP_COMMENTS_PER_STORY = 5  # keep top N top-level comments per story (by points)
MIN_COMMENTS_FILTER = 3     # stories with fewer comments aren't worth the round-trip
MAX_STORIES_FETCH = 15      # cap stories pulled from search before ranking
PACE_SECONDS = 0.4          # be polite to Algolia (no rate limit but courteous)
CACHE_TTL_HOURS = 24        # treat cache as fresh for 24h


# Ticker → search query map. HN talks about companies by name, not by ticker.
# Curated for watchlist coverage — extend as needed. Missing entries fall
# back to the ticker symbol (works for some, e.g. "Bitcoin" via BTC).
TICKER_NAMES = {
    # US equities
    "SPY":  None,           # too broad — skip
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "GOOGL": "Google",
    "GOOG": "Google",
    "META": "Meta",
    "AMZN": "Amazon",
    "NVDA": "Nvidia",
    "TSLA": "Tesla",
    "RDDT": "Reddit",
    "MRVL": "Marvell",
    "RKLB": "Rocket Lab",
    "CLOV": "Clover Health",
    "CLSK": "CleanSpark",
    "CIFR": "Cipher Mining",
    "AUPH": "Aurinia",
    "RGLD": "Royal Gold",
    "RYDE": "Ryde",
    "KTOS": "Kratos Defense",
    "KO":   "Coca-Cola",
    "PURR": "Hyperliquid",    # PURR is the equity-treasury proxy, HN talks about HL
    "EONR":  None,           # unclear company; skip until verified
    # Crypto (CoinGecko ids/symbols)
    "BTC":  "Bitcoin",
    "ETH":  "Ethereum",
    "SOL":  "Solana",
    "BNB":  "Binance",
    "XRP":  "Ripple",
    "HBAR": "Hedera",
    "HYPE": "Hyperliquid",
    "ENA":  "Ethena",
    "ONDO": "Ondo Finance",
}


def _now():
    return datetime.now(timezone.utc)


def watchlist_tickers():
    """Read watchlist.md, return list of uppercase tickers. Strips .KL suffix
    (KLSE never has HN coverage so we skip those automatically)."""
    if not WATCHLIST_PATH.exists():
        return []
    text = WATCHLIST_PATH.read_text(encoding="utf-8")
    tickers, seen = [], set()
    for m in re.finditer(r"^\s*-\s*`([^`]+)`", text, re.MULTILINE):
        sym = m.group(1).strip().upper()
        if not sym or sym.startswith("_") or sym == "TICKER":
            continue
        # Skip KLSE codes (4 digits or *.KL) — no HN coverage
        if sym.endswith(".KL") or re.fullmatch(r"\d{4}", sym):
            continue
        if sym not in seen:
            seen.add(sym); tickers.append(sym)
    return tickers


def ticker_query(ticker):
    """Return the search query string for a ticker, or None if mapped-to-skip."""
    t = ticker.upper()
    if t in TICKER_NAMES:
        return TICKER_NAMES[t]  # may be None to signal skip
    # Unknown — fall back to the ticker itself. Works for some names but
    # often returns noise; the LLM scorer's relevance filter cleans up.
    return t


# ── HTTP helpers ─────────────────────────────────────────────────────────
def _http_get_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "trading-advisor/0.1 (hn-sentiment)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _strip_html(s):
    if not s:
        return ""
    # HN comments come HTML-formatted. Crude strip — drop tags, decode &lt; etc.
    s = re.sub(r"<[^>]+>", " ", s)
    s = (s.replace("&#x27;", "'").replace("&quot;", '"')
           .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
           .replace("&#x2F;", "/").replace("&nbsp;", " "))
    return re.sub(r"\s+", " ", s).strip()


# ── Algolia calls ────────────────────────────────────────────────────────
def search_stories(query, lookback_days=LOOKBACK_DAYS, hits=MAX_STORIES_FETCH):
    """Search HN stories matching `query` from the last N days."""
    cutoff = int((_now() - timedelta(days=lookback_days)).timestamp())
    params = {
        "query": query,
        "tags": "story",
        "numericFilters": f"created_at_i>{cutoff},num_comments>={MIN_COMMENTS_FILTER}",
        "hitsPerPage": hits,
        "restrictSearchableAttributes": "title,story_text",
    }
    url = f"{ALGOLIA_SEARCH}?{urllib.parse.urlencode(params)}"
    data, err = _http_get_json(url)
    if err:
        return [], err
    return data.get("hits") or [], None


def fetch_story_comments(story_id, top_n=TOP_COMMENTS_PER_STORY):
    """Pull the comment tree for a story; return top-level comments ranked
    by `points`, limited to top_n. Falls back to creation-recency on stories
    where every comment has points=null (Algolia sometimes omits it)."""
    url = f"{ALGOLIA_ITEM}/{story_id}"
    data, err = _http_get_json(url)
    if err:
        return [], err
    children = data.get("children") or []
    items = []
    for c in children:
        if c.get("type") != "comment":
            continue
        body = _strip_html(c.get("text", ""))
        if not body or len(body) < 40:  # drop very short noise
            continue
        items.append({
            "body": body[:600],  # cap each comment to keep LLM-token budget in check
            "points": c.get("points"),
            "author": c.get("author"),
            "created_at": c.get("created_at"),
        })
    items.sort(key=lambda x: (x.get("points") or 0, x.get("created_at") or ""), reverse=True)
    return items[:top_n], None


# ── Cache I/O ────────────────────────────────────────────────────────────
def cache_path(ticker):
    safe = ticker.upper().replace("/", "_").replace("\\", "_")
    return CACHE_DIR / f"{safe}.json"


def save_cache(ticker, payload):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path(ticker).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_cache(ticker):
    p = cache_path(ticker)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def is_fresh(ticker, ttl_hours=CACHE_TTL_HOURS):
    d = load_cache(ticker)
    if not d:
        return False
    ts = d.get("fetched_at")
    if not ts:
        return False
    try:
        age = (_now() - datetime.fromisoformat(ts)).total_seconds() / 3600.0
        return age < ttl_hours
    except Exception:
        return False


# ── Main per-ticker workflow ────────────────────────────────────────────
def refresh_ticker(ticker, force=False):
    """Fetch HN stories + top comments for one ticker. Persist to cache."""
    ticker = ticker.upper()
    query = ticker_query(ticker)
    if query is None:
        # Explicitly mapped to skip (SPY, EONR, etc.)
        payload = {
            "ticker": ticker, "company_query": None, "no_coverage": True,
            "reason": "ticker is mapped-to-skip (too broad or unverified)",
            "fetched_at": _now().isoformat(timespec="seconds"),
            "story_count": 0, "stories": [],
        }
        save_cache(ticker, payload)
        return payload

    if not force and is_fresh(ticker):
        return load_cache(ticker)

    print(f"[hn] {ticker} (query='{query}')", end=" ", flush=True)
    hits, err = search_stories(query)
    if err:
        payload = {
            "ticker": ticker, "company_query": query, "error": err,
            "fetched_at": _now().isoformat(timespec="seconds"),
            "story_count": 0, "stories": [],
        }
        save_cache(ticker, payload)
        print(f"search-err={err}")
        return payload

    # Rank stories by engagement = points + num_comments*2
    for h in hits:
        h["_engagement"] = (h.get("points") or 0) + 2 * (h.get("num_comments") or 0)
    hits.sort(key=lambda h: h["_engagement"], reverse=True)
    top = hits[:TOP_STORIES]

    stories = []
    for h in top:
        sid = str(h.get("objectID", ""))
        comments, c_err = fetch_story_comments(sid)
        time.sleep(PACE_SECONDS)
        story_text_excerpt = _strip_html(h.get("story_text") or "")[:400] or None
        stories.append({
            "id": sid,
            "title": h.get("title") or "",
            "url": h.get("url") or h.get("story_url") or f"https://news.ycombinator.com/item?id={sid}",
            "points": h.get("points"),
            "num_comments": h.get("num_comments"),
            "engagement": h["_engagement"],
            "author": h.get("author"),
            "created_at": h.get("created_at"),
            "story_text_excerpt": story_text_excerpt,
            "top_comments": comments,
            "comments_error": c_err,
        })

    payload = {
        "ticker": ticker,
        "company_query": query,
        "fetched_at": _now().isoformat(timespec="seconds"),
        "lookback_days": LOOKBACK_DAYS,
        "story_count": len(stories),
        "hits_searched": len(hits),
        "stories": stories,
    }
    save_cache(ticker, payload)
    total_comments = sum(len(s["top_comments"]) for s in stories)
    print(f"stories={len(stories)} comments={total_comments} (from {len(hits)} hits)")
    return payload


# ── CLI ─────────────────────────────────────────────────────────────────
def cmd_show(targets):
    cached = sorted(p.stem for p in CACHE_DIR.glob("*.json")) if CACHE_DIR.is_dir() else []
    if targets:
        targets = [t.upper() for t in targets]
        cached = [t for t in cached if t in targets]
    if not cached:
        print("(no cached entries)")
        return
    for t in cached:
        d = load_cache(t)
        if not d:
            print(f"{t:8s}  (corrupt)")
            continue
        if d.get("no_coverage"):
            print(f"{t:8s}  skip ({d.get('reason','no coverage')})")
            continue
        if d.get("error"):
            print(f"{t:8s}  err: {d['error']}  fetched {d.get('fetched_at','?')}")
            continue
        sc = d.get("story_count", 0)
        cc = sum(len(s.get("top_comments", [])) for s in d.get("stories", []))
        ts = d.get("fetched_at", "?")
        q  = d.get("company_query", "?")
        print(f"{t:8s}  query='{q}' stories={sc} comments={cc}  fetched {ts}")
        if len(targets or []) == 1:
            for s in d.get("stories", []):
                print(f"  [{s.get('engagement','?')}p+c]  {s.get('title','')[:80]}")
                for c in s.get("top_comments", []):
                    body = (c.get("body") or "")[:90].replace("\n", " ")
                    print(f"      ({c.get('points','?')}p) {body}")


def cmd_clear():
    if not CACHE_DIR.is_dir():
        print("(no cache dir)")
        return
    n = 0
    for p in CACHE_DIR.glob("*.json"):
        p.unlink(); n += 1
    print(f"removed {n} entries")


def main():
    ap = argparse.ArgumentParser(description="HN sentiment raw-fetch (free Algolia API)")
    ap.add_argument("tickers", nargs="*", help="Specific tickers; empty = all watchlist")
    ap.add_argument("--show", action="store_true", help="Print cached state instead of fetching")
    ap.add_argument("--clear", action="store_true", help="Wipe the cache dir")
    ap.add_argument("--force", action="store_true", help="Bypass freshness check; refetch even if cache <24h old")
    args = ap.parse_args()

    if args.clear:
        cmd_clear(); return 0
    if args.show:
        cmd_show(args.tickers); return 0

    tickers = args.tickers if args.tickers else watchlist_tickers()
    if not tickers:
        print("No tickers (empty watchlist?)"); return 1

    print(f"Refreshing HN sentiment for {len(tickers)} ticker(s)" +
          (" [forced]" if args.force else f" [cache TTL {CACHE_TTL_HOURS}h]"))
    for t in tickers:
        try:
            refresh_ticker(t, force=args.force)
        except Exception as e:
            print(f"[hn] {t} CRASHED: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
