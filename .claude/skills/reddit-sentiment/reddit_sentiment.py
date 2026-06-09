#!/usr/bin/env python3
"""
reddit_sentiment.py — Manually refresh retail-sentiment raw data from Reddit.

Step 1 of Phase A retail-sentiment build. This is the FETCHER ONLY — it pulls
posts from relevant subreddits and dumps them to JSON. Sentiment scoring is
a separate layer (built next) that consumes this cache.

Why split fetch and score: we can re-score without re-fetching (cheaper iteration
on the scoring prompt), and a broken scorer can't corrupt raw data.

Manual (no automation): you run this when you want fresh retail-sentiment data.
Output: .claude/cache/reddit_sentiment/{ticker}.json per ticker.

Usage:
    python3 .claude/skills/reddit-sentiment/reddit_sentiment.py             # all watchlist
    python3 .claude/skills/reddit-sentiment/reddit_sentiment.py AUPH BTC    # specific
    python3 .claude/skills/reddit-sentiment/reddit_sentiment.py --show      # cached values
    python3 .claude/skills/reddit-sentiment/reddit_sentiment.py --show AUPH # one ticker detail
    python3 .claude/skills/reddit-sentiment/reddit_sentiment.py --clear     # wipe cache
"""

import argparse
import base64
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
WATCHLIST_PATH = PROJECT_ROOT / "watchlist.md"
CACHE_DIR = PROJECT_ROOT / ".claude" / "cache" / "reddit_sentiment"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
ENV_FILE = SCRIPT_DIR / ".env"
TOKEN_CACHE = CACHE_DIR / ".oauth_token.json"

# Reddit requires this exact UA format: <platform>:<app-id>:<version> (by /u/<user>)
# Username defaults to "anonymous" if REDDIT_USERNAME not set — Reddit accepts it for
# client_credentials (application-only) grants. Real account name preferred when available.
UA_TEMPLATE = "trading-advisor:reddit-sentiment:0.1.0 (by /u/{user})"

DEFAULT_DELAY_SEC = 1.0
DEFAULT_LOOKBACK_DAYS = 7
TOP_N_POSTS = 10  # keep this many posts per ticker (deduped, ranked by score)


# ── .env loader (dependency-free) ──────────────────────────────────────────
def load_env_file(path=ENV_FILE):
    """Load KEY=VAL pairs from .env into os.environ. env wins over .env (conventional)."""
    if not path.exists():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception as e:
        print(f"WARN: .env parse failed: {e}", file=sys.stderr)


def get_ua():
    user = os.environ.get("REDDIT_USERNAME", "anonymous").strip().lstrip("/u/").lstrip("u/")
    return UA_TEMPLATE.format(user=user or "anonymous")


# ── OAuth (client_credentials grant) ───────────────────────────────────────
def get_oauth_token(force_refresh=False):
    """Fetch an application-only OAuth token from Reddit. Cached on disk until expiry."""
    if not force_refresh and TOKEN_CACHE.exists():
        try:
            cached = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
            if cached.get("expires_at", 0) > time.time() + 60:
                return cached["access_token"], None
        except Exception:
            pass

    client_id = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None, (
            "Missing REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET. "
            f"Set them in {ENV_FILE} (see SKILL.md for the 5-step app-registration walkthrough)."
        )

    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token",
        data=body,
        headers={
            "Authorization": f"Basic {auth}",
            "User-Agent": get_ua(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        return None, f"OAuth HTTP {e.code}: {e.reason} — {body}"
    except Exception as e:
        return None, f"OAuth {type(e).__name__}: {e}"

    token = data.get("access_token")
    if not token:
        return None, f"OAuth response missing access_token: {data}"

    expires_in = int(data.get("expires_in") or 3600)
    TOKEN_CACHE.write_text(json.dumps({
        "access_token": token,
        "token_type": data.get("token_type", "bearer"),
        "expires_at": time.time() + expires_in - 60,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }, indent=2), encoding="utf-8")
    return token, None

# ── Subreddit routing ──────────────────────────────────────────────────────
SUBS_US_EQUITY = ["wallstreetbets", "stocks", "investing", "StockMarket"]
SUBS_KLSE = ["Bursa_Malaysia", "MalaysianPF", "malaysia"]
SUBS_CRYPTO_GENERAL = ["CryptoCurrency", "CryptoMarkets"]

# Crypto ticker → (full name for query, per-coin sub if exists)
CRYPTO_META = {
    "BTC": ("Bitcoin", "Bitcoin"),
    "ETH": ("Ethereum", "ethereum"),
    "SOL": ("Solana", "solana"),
    "BNB": ("Binance Coin", "binance"),
    "XRP": ("Ripple", "Ripple"),
    "HBAR": ("Hedera", "Hedera"),
    "HYPE": ("Hyperliquid", "HyperliquidX"),
    "ENA": ("Ethena", "ethena_labs"),
}


# ── Classification ─────────────────────────────────────────────────────────
def classify_ticker(ticker):
    t = ticker.upper().strip()
    if t.endswith(".KL") or (t.replace(".KL", "").isdigit() and len(t.replace(".KL", "")) == 4):
        return "klse"
    if t in CRYPTO_META:
        return "crypto"
    return "us_equity"


def query_terms(ticker):
    """Return list of query strings to search Reddit with."""
    t = ticker.upper().strip()
    cls = classify_ticker(t)
    if cls == "crypto":
        name, _ = CRYPTO_META[t]
        # Search ticker OR full name — most posts use one or the other
        return [t, name]
    if cls == "klse":
        # Strip .KL — Reddit posts about Bursa names usually use bare code or company name
        return [t.replace(".KL", "")]
    return [t]


def subs_for(ticker):
    cls = classify_ticker(ticker)
    if cls == "crypto":
        per_coin = CRYPTO_META[ticker.upper()][1]
        return SUBS_CRYPTO_GENERAL + [per_coin]
    if cls == "klse":
        return SUBS_KLSE
    return SUBS_US_EQUITY


# ── HTTP ──────────────────────────────────────────────────────────────────
def reddit_search_oauth(sub, query, token, lookback_days=DEFAULT_LOOKBACK_DAYS, timeout=20):
    """OAuth-authenticated search via oauth.reddit.com. Returns (posts_list, error_or_none).
    Used when REDDIT_CLIENT_ID/SECRET are present (preferred — richer data including scores).

    v1.9.2 fix: the original function was a stub left over from the v1.5.0 OAuth refactor
    — it fetched the JSON and returned None implicitly. Reddit fetches silently fell
    through to the RSS path (no score / num_comments) even when credentials were set.
    Engagement-weighting was effectively a no-op on Reddit data because of this.
    """
    t_window = "week" if lookback_days <= 7 else "month"
    params = {
        "q": query,
        "restrict_sr": "1",
        "t": t_window,
        "sort": "new",
        "limit": "25",
    }
    url = f"https://oauth.reddit.com/r/{sub}/search?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": get_ua(),
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return [], f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"

    children = (data.get("data") or {}).get("children") or []
    cutoff_ts = time.time() - (lookback_days * 86400)
    posts = []
    for ch in children:
        if ch.get("kind") != "t3":
            continue
        pd = ch.get("data") or {}
        created = pd.get("created_utc")
        if created and created < cutoff_ts:
            continue
        selftext = (pd.get("selftext") or "")[:500]
        posts.append({
            "id": pd.get("id") or "",
            "subreddit": sub,
            "title": pd.get("title") or "",
            "score": pd.get("score"),                # real upvote count
            "num_comments": pd.get("num_comments"),  # real comment count
            "created_utc": int(created) if created else None,
            "url": pd.get("url") or f"https://www.reddit.com{pd.get('permalink','')}",
            "selftext_excerpt": selftext,
            "source": "oauth",
        })
    return posts, None


def reddit_search_rss(sub, query, lookback_days=DEFAULT_LOOKBACK_DAYS, timeout=20):
    """Unauthenticated search via Reddit's Atom/RSS feed. Returns (posts_list, error_or_none).
    Used when no OAuth credentials — Reddit's RSS path is not blocked the way JSON is.
    Trade-off: no score/num_comments (RSS doesn't include them); title + summary + author + URL only."""
    t_window = "week" if lookback_days <= 7 else "month"
    params = {
        "q": query,
        "restrict_sr": "1",
        "t": t_window,
        "sort": "new",
    }
    url = f"https://www.reddit.com/r/{sub}/search.rss?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": get_ua(),
            "Accept": "application/atom+xml, application/xml",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return [], f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"

    # Parse Atom feed
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        return [], f"RSS parse failed: {e}"

    ns = {"a": "http://www.w3.org/2005/Atom"}
    cutoff_ts = time.time() - (lookback_days * 86400)
    posts = []
    for entry in root.findall("a:entry", ns):
        title_el = entry.find("a:title", ns)
        title = (title_el.text or "").strip() if title_el is not None else ""

        content_el = entry.find("a:content", ns)
        content_html = content_el.text or "" if content_el is not None else ""
        # Atom content is HTML-escaped; strip tags and unescape entities for the body excerpt
        content_text = re.sub(r"<[^>]+>", " ", html.unescape(content_html))
        content_text = re.sub(r"\s+", " ", content_text).strip()

        link_el = entry.find("a:link", ns)
        url_attr = link_el.get("href") if link_el is not None else ""

        # Author can be a <name> inside <author>
        author = ""
        author_el = entry.find("a:author/a:name", ns)
        if author_el is not None and author_el.text:
            author = author_el.text.strip()

        # Updated timestamp (ISO 8601)
        updated_el = entry.find("a:updated", ns)
        updated_iso = (updated_el.text or "").strip() if updated_el is not None else ""
        created_utc = 0
        if updated_iso:
            try:
                # Python 3.7+ fromisoformat doesn't handle 'Z' suffix until 3.11; normalize
                iso = updated_iso.replace("Z", "+00:00")
                dt = datetime.fromisoformat(iso)
                created_utc = int(dt.timestamp())
            except Exception:
                pass

        if created_utc and created_utc < cutoff_ts:
            continue

        # Entry id format: today it's "t3_POSTID" (Reddit fullname). Older format
        # was the tag URI "tag:reddit.com,2008:/r/sub/comments/POSTID/slug" —
        # both regexes tried in order so we work across format changes.
        id_el = entry.find("a:id", ns)
        id_text = (id_el.text or "").strip() if id_el is not None else ""
        m = re.search(r"comments/([a-z0-9]+)/", id_text) or re.match(r"t3_([a-z0-9]+)", id_text)
        post_id = m.group(1) if m else id_text[-10:]

        posts.append({
            "id": post_id,
            "subreddit": sub,
            "title": title,
            "score": None,            # not in RSS
            "num_comments": None,     # not in RSS
            "created_utc": created_utc or None,
            "url": url_attr,
            "selftext_excerpt": content_text[:500],
            "source": "rss",
        })
    return posts, None


def reddit_search(sub, query, token, lookback_days=DEFAULT_LOOKBACK_DAYS, timeout=20):
    """Dispatch to OAuth path if token present, else RSS workaround."""
    if token:
        posts, err = reddit_search_oauth(sub, query, token, lookback_days=lookback_days, timeout=timeout)
        if not err:
            for p in posts:
                p["source"] = "oauth"
        return posts, err
    return reddit_search_rss(sub, query, lookback_days=lookback_days, timeout=timeout)


# ── Comment-tree fetching (v1.9.2+) ──────────────────────────────────────
# Top comments often carry the meatier sentiment than the OP. Fetched per post
# after the top-N ranking. OAuth path gives per-comment scores; RSS path gives
# bodies only (no scores) — the engagement-weighting in sentiment-cache falls
# back to uniform weighting on RSS-sourced comments.
COMMENTS_PER_POST = 5
MIN_COMMENT_LEN = 40  # drop very-short noise ("this", "lol", etc.)


def fetch_comments_oauth(sub, post_id, token, top_n=COMMENTS_PER_POST, timeout=15):
    """OAuth path: full comment tree with scores. Returns list of comment dicts."""
    url = f"https://oauth.reddit.com/r/{sub}/comments/{post_id}?limit=25&sort=top&depth=1"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": get_ua(),
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return [], f"HTTP {e.code}"
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"
    # Response is [post_listing, comments_listing]; comments at children[].data.body
    if not isinstance(data, list) or len(data) < 2:
        return [], "unexpected response shape"
    children = (data[1].get("data") or {}).get("children") or []
    out = []
    for c in children:
        if c.get("kind") != "t1":
            continue
        cd = c.get("data") or {}
        body = (cd.get("body") or "").strip()
        if not body or len(body) < MIN_COMMENT_LEN:
            continue
        out.append({
            "body": body[:600],   # cap to keep LLM-token budget reasonable
            "score": cd.get("score"),
            "author": cd.get("author"),
            "created_utc": cd.get("created_utc"),
            "source": "oauth",
        })
    out.sort(key=lambda x: x.get("score") or 0, reverse=True)
    return out[:top_n], None


def fetch_comments_rss(sub, post_id, top_n=COMMENTS_PER_POST, timeout=15):
    """RSS path: comment bodies via the Atom feed. No per-comment score available.
    First entry in the feed is the post itself — we skip it and treat the rest as comments.
    """
    url = f"https://www.reddit.com/r/{sub}/comments/{post_id}.rss?limit=25&sort=top"
    req = urllib.request.Request(url, headers={
        "User-Agent": get_ua(),
        "Accept": "application/atom+xml, application/xml",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return [], f"HTTP {e.code}"
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        return [], f"parse: {e}"
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entries = root.findall("a:entry", ns)
    if not entries:
        return [], None
    out = []
    # Skip the first entry (the post body); remaining entries are comments.
    for e in entries[1:]:
        content_el = e.find("a:content", ns)
        if content_el is None or not content_el.text:
            continue
        text = re.sub(r"<[^>]+>", " ", html.unescape(content_el.text))
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < MIN_COMMENT_LEN:
            continue
        author_el = e.find("a:author/a:name", ns)
        author = author_el.text.strip() if author_el is not None and author_el.text else None
        updated_el = e.find("a:updated", ns)
        created_utc = None
        if updated_el is not None and updated_el.text:
            try:
                iso = updated_el.text.strip().replace("Z", "+00:00")
                created_utc = int(datetime.fromisoformat(iso).timestamp())
            except Exception:
                pass
        out.append({
            "body": text[:600],
            "score": None,        # RSS doesn't expose
            "author": author,
            "created_utc": created_utc,
            "source": "rss",
        })
    # RSS order is reverse-chrono. No score to rank by; keep first top_n as proxy.
    return out[:top_n], None


def fetch_comments(sub, post_id, token, top_n=COMMENTS_PER_POST):
    """Dispatch to OAuth (with scores) if token, else RSS (bodies only)."""
    if token:
        return fetch_comments_oauth(sub, post_id, token, top_n=top_n)
    return fetch_comments_rss(sub, post_id, top_n=top_n)


# ── Aggregate per ticker ───────────────────────────────────────────────────
def fetch_ticker(ticker, token, lookback_days=DEFAULT_LOOKBACK_DAYS, delay=DEFAULT_DELAY_SEC, verbose=True):
    cls = classify_ticker(ticker)
    subs = subs_for(ticker)
    queries = query_terms(ticker)

    all_posts = {}  # id → post (dedup)
    errors = []
    n_calls = 0

    for sub in subs:
        for q in queries:
            if verbose:
                print(f"  [reddit] r/{sub} q={q!r} ... ", end="", flush=True)
            posts, err = reddit_search(sub, q, token, lookback_days=lookback_days)
            n_calls += 1
            if err:
                errors.append(f"r/{sub} q={q!r}: {err}")
                if verbose:
                    print(f"ERR ({err})")
            else:
                # Dedup by post id; for crypto where we search both ticker and name,
                # this avoids double-counting the same post matched by both queries.
                for p in posts:
                    if p["id"] not in all_posts:
                        all_posts[p["id"]] = p
                if verbose:
                    print(f"{len(posts)} posts")
            time.sleep(delay)

    # Rank by score (when OAuth provides it) or recency (RSS mode), keep top N for downstream scoring
    ranked = sorted(
        all_posts.values(),
        key=lambda p: (p.get("score") if p.get("score") is not None else 0, p.get("created_utc") or 0),
        reverse=True,
    )[:TOP_N_POSTS]

    # v1.9.2: fetch top comments for each ranked post. OAuth gives per-comment
    # scores (engagement-weightable); RSS gives bodies only (uniform weighting).
    comment_calls = 0
    comment_errors = []
    for p in ranked:
        post_id = p.get("id")
        sub = p.get("subreddit")
        if not post_id or not sub:
            p["top_comments"] = []
            continue
        if verbose:
            print(f"  [reddit] r/{sub} comments/{post_id} ... ", end="", flush=True)
        comments, c_err = fetch_comments(sub, post_id, token)
        comment_calls += 1
        if c_err:
            comment_errors.append(f"r/{sub}/{post_id}: {c_err}")
            if verbose:
                print(f"ERR ({c_err})")
            p["top_comments"] = []
        else:
            p["top_comments"] = comments
            if verbose:
                print(f"{len(comments)} comments")
        time.sleep(delay)

    return {
        "ticker": ticker.upper(),
        "asset_class": cls,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "lookback_days": lookback_days,
        "subs_searched": subs,
        "queries_used": queries,
        "api_calls": n_calls + comment_calls,
        "search_calls": n_calls,
        "comment_calls": comment_calls,
        "mention_count": len(all_posts),
        "posts": ranked,
        "errors": (errors + comment_errors) or None,
    }


# ── Watchlist parsing ──────────────────────────────────────────────────────
def parse_watchlist():
    """Extract tickers from watchlist.md. Returns list of uppercase ticker strings."""
    if not WATCHLIST_PATH.exists():
        return []
    text = WATCHLIST_PATH.read_text(encoding="utf-8")
    # Match `TICKER` at start of a list item — backtick-wrapped
    tickers = []
    for m in re.finditer(r"^\s*-\s*`([^`]+)`", text, re.MULTILINE):
        sym = m.group(1).strip().upper()
        # Skip section placeholders / italicized notes / the literal `TICKER` format example
        if sym and not sym.startswith("_") and sym != "TICKER":
            tickers.append(sym)
    # Dedup preserving order
    seen = set()
    out = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ── Cache I/O ──────────────────────────────────────────────────────────────
def cache_path(ticker):
    safe = ticker.upper().replace("/", "_").replace("\\", "_")
    return CACHE_DIR / f"{safe}.json"


def save_cache(ticker, data):
    p = cache_path(ticker)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def load_cache(ticker):
    p = cache_path(ticker)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── Commands ──────────────────────────────────────────────────────────────
def cmd_refresh(tickers, lookback_days=DEFAULT_LOOKBACK_DAYS, delay=DEFAULT_DELAY_SEC):
    if not tickers:
        tickers = parse_watchlist()
        if not tickers:
            print("ERROR: no tickers passed and watchlist.md is empty/missing", file=sys.stderr)
            return 1
        print(f"Refreshing {len(tickers)} tickers from watchlist.md")
    else:
        print(f"Refreshing {len(tickers)} tickers: {' '.join(tickers)}")

    # OAuth is optional — if credentials present, use it (richer data including scores);
    # otherwise fall back to Reddit's RSS feeds (titles + bodies, no scores).
    has_creds = os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET")
    if has_creds:
        token, err = get_oauth_token()
        if err:
            print(f"WARN: OAuth failed, falling back to RSS: {err}", file=sys.stderr)
            token = None
        else:
            print(f"OAuth token acquired (UA: {get_ua()})")
    else:
        token = None
        print(f"No OAuth credentials — using RSS workaround (UA: {get_ua()})")
        print("(Add REDDIT_CLIENT_ID/SECRET to .env once your app is approved for richer data.)")

    summary = []
    for i, t in enumerate(tickers, 1):
        print(f"\n[{i}/{len(tickers)}] {t}")
        result = fetch_ticker(t, token, lookback_days=lookback_days, delay=delay, verbose=True)
        save_cache(t, result)
        summary.append((t, result["mention_count"], len(result.get("errors") or [])))

    print("\n── Summary " + "─" * 50)
    print(f"{'TICKER':<10}{'MENTIONS':>10}{'ERRORS':>10}")
    for t, n, e in summary:
        print(f"{t:<10}{n:>10}{e:>10}")
    print()
    return 0


def cmd_show(tickers):
    if tickers:
        # Detail view for a specific ticker
        for t in tickers:
            data = load_cache(t)
            if not data:
                print(f"{t}: no cache entry")
                continue
            print(f"\n── {t} ({data['asset_class']}) — fetched {data['fetched_at']} ──")
            print(f"  subs: {', '.join(data['subs_searched'])}")
            print(f"  queries: {data['queries_used']}")
            print(f"  mention_count: {data['mention_count']}")
            if data.get("errors"):
                print(f"  errors: {data['errors']}")
            for p in data["posts"][:5]:
                print(f"  • [r/{p['subreddit']}] {p['title'][:80]}  (score={p['score']}, comments={p['num_comments']})")
        return 0

    # Index view: all cached tickers
    print(f"{'TICKER':<10}{'CLASS':<12}{'MENTIONS':>10}  FETCHED")
    files = sorted(CACHE_DIR.glob("*.json"))
    if not files:
        print("(cache empty)")
        return 0
    for p in files:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            print(f"{d['ticker']:<10}{d['asset_class']:<12}{d['mention_count']:>10}  {d['fetched_at']}")
        except Exception as e:
            print(f"{p.stem:<10}(unreadable: {e})")
    return 0


def cmd_clear():
    files = list(CACHE_DIR.glob("*.json"))
    for p in files:
        p.unlink()
    print(f"Cleared {len(files)} cache files from {CACHE_DIR}")
    return 0


# ── Main ──────────────────────────────────────────────────────────────────
def cmd_check_auth():
    """Verify which Reddit access mode is active (OAuth or RSS fallback)."""
    print(f"ENV file: {ENV_FILE}  (exists: {ENV_FILE.exists()})")
    print(f"REDDIT_CLIENT_ID: {'set' if os.environ.get('REDDIT_CLIENT_ID') else 'not set'}")
    print(f"REDDIT_CLIENT_SECRET: {'set' if os.environ.get('REDDIT_CLIENT_SECRET') else 'not set'}")
    print(f"REDDIT_USERNAME: {os.environ.get('REDDIT_USERNAME', '(not set, will use anonymous)')}")
    print(f"UA: {get_ua()}")
    has_creds = os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET")
    if has_creds:
        token, err = get_oauth_token(force_refresh=True)
        if err:
            print(f"\nMODE: RSS fallback (OAuth credentials present but token fetch failed: {err})")
            return 1
        print(f"\nMODE: OAuth (richer data including scores). Token cached at {TOKEN_CACHE}")
        return 0

    # RSS probe
    posts, err = reddit_search_rss("wallstreetbets", "test")
    if err:
        print(f"\nMODE: RSS fallback — but probe failed: {err}")
        return 1
    print(f"\nMODE: RSS fallback (no OAuth credentials). Probe returned {len(posts)} posts.")
    print("Add REDDIT_CLIENT_ID/SECRET to .env once your Reddit app is approved for richer data.")
    return 0


def main():
    load_env_file()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1] if __doc__ else None)
    ap.add_argument("tickers", nargs="*", help="Specific tickers to refresh (default: watchlist)")
    ap.add_argument("--show", action="store_true", help="Show cached values, no fetch")
    ap.add_argument("--clear", action="store_true", help="Wipe the cache")
    ap.add_argument("--check-auth", action="store_true", help="Verify OAuth credentials work")
    ap.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK_DAYS, help="Lookback days (default 7)")
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY_SEC, help="Politeness delay between requests (default 1.0s)")
    args = ap.parse_args()

    if args.clear:
        return cmd_clear()
    if args.check_auth:
        return cmd_check_auth()
    if args.show:
        return cmd_show([t.upper() for t in args.tickers])
    return cmd_refresh([t.upper() for t in args.tickers], lookback_days=args.lookback, delay=args.delay)


if __name__ == "__main__":
    sys.exit(main())
