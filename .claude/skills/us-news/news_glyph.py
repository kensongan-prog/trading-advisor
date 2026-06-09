"""
news_glyph.py — Per-ticker 72h news-direction glyph (🟢 / 🔴 / ⚪ + ❗ analyst modifier).

The dashboard reads this to surface a news-direction indicator inside each
watchlist row's existing Retail/News column, with the headline list rendered
in the row's expandable dropdown.

Sources by asset class:
  US      AV cache (.claude/cache/us_news/{TICKER}.json, sentiment pre-scored)
          + Finnhub upgrade_downgrade (.claude/cache/finnhub_news/{TICKER}.json)
          + Finnhub company_news (coverage gap-filler)
  KLSE    .claude/cache/klse_news/{CODE}.json (scraped from klsescreener.com)
  Crypto  .claude/cache/crypto_news/{COIN}.json (CoinGecko status_updates + headlines)

Doctrine:
  - 72h window drives the glyph color. Older items still render in the dropdown
    as context but do NOT change the glyph.
  - Analyst rating action in 72h → ❗ modifier appended (e.g. 🟢❗ or 🔴❗).
  - Analyst-action items carry a hard-coded caveat string in the dropdown:
    analyst calls are salient but ~50% accurate at 12mo horizon — confluence
    still required (AGENTS.md §4).

CLI:
  python3 news_glyph.py refresh-us --tickers AAPL,MSFT,CLSK [--force]
  python3 news_glyph.py refresh-klse --codes 1155,5285 [--force]
  python3 news_glyph.py refresh-crypto --coins bitcoin,ethereum [--force]
  python3 news_glyph.py show --ticker CLSK --asset-class us
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

_THIS = Path(__file__).resolve()
PROJECT_ROOT = _THIS.parent.parent.parent.parent
CACHE_ROOT = PROJECT_ROOT / ".claude" / "cache"
FINNHUB_CACHE = CACHE_ROOT / "finnhub_news"
KLSE_NEWS_CACHE = CACHE_ROOT / "klse_news"
CRYPTO_NEWS_CACHE = CACHE_ROOT / "crypto_news"
US_NEWS_CACHE = CACHE_ROOT / "us_news"  # AV cache (existing)
LLM_SCORE_CACHE = CACHE_ROOT / "news_llm_scores"  # per-ticker, item-immutable

# OpenRouter free-tier scoring (shares the key with sentiment-cache).
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
LLM_DEFAULT_MODEL = "google/gemma-4-31b-it:free"
LLM_FALLBACK_MODEL = "openai/gpt-oss-120b:free"
LLM_BATCH_SIZE = 10  # headlines per call; keeps latency + token budget tight

# Allow importing finnhub_client and us-news/news_cache helpers.
sys.path.insert(0, str(_THIS.parent.parent / "finnhub"))
sys.path.insert(0, str(_THIS.parent))

# Sentiment-direction caveat applied wherever an analyst action drives the glyph.
ANALYST_CAVEAT = (
    "Analyst calls ~50% accurate at 12mo horizon — treat as a salient data "
    "point, not a thesis. Confluence still required (AGENTS.md §4)."
)

# Sentiment thresholds — mirror Alpha Vantage's label boundaries.
SENT_BULL_THR = 0.15
SENT_BEAR_THR = -0.15

# Keyword heuristic for non-AV sources (Finnhub headlines, KLSE, crypto).
# Pre-scored AV items take priority; this is fallback when no score is available.
BULL_KW = re.compile(
    r"\b(upgrade[ds]?|raises?\s+(rating|target|guidance|estimate)|beat[s]?(\s+expectations)?|"
    r"surge[ds]?|soars?|rally|rallies|jumps?|gains?|rises?|tops?\s+estimate|record\s+high|"
    r"outperform|exceeds?|breakthrough|partnership|approval[s]?|wins?\s+contract|"
    r"buyback|dividend\s+(hike|increase|raise))\b",
    re.IGNORECASE,
)
BEAR_KW = re.compile(
    r"\b(downgrade[ds]?|cut[s]?\s+(rating|target|guidance|estimate)|miss(es)?(\s+expectations)?|"
    r"plunge[ds]?|slump[s]?|tumble[ds]?|plummet[s]?|slide[s]?|drops?\s+\d|falls?\s+\d|"
    r"trade[sd]?\s+down|trading\s+down|sell[- ]off|sell\s+rating|"
    r"decline[ds]?|weak|loss(es)?|lawsuit|investigation|probe|recall|fraud|bankruptcy|"
    r"going\s+concern|delisting|warning|guidance\s+cut|dividend\s+(cut|suspend))\b",
    re.IGNORECASE,
)
# Analyst-action detection from a headline (used for KLSE + crypto + AV items
# where Finnhub's structured upgrade-downgrade feed doesn't apply).
ANALYST_KW = re.compile(
    r"\b(upgrade[ds]?|downgrade[ds]?|raises?\s+(target|rating)|cuts?\s+(target|rating)|"
    r"initiate[ds]?\s+coverage|reiterate[ds]?|overweight|underweight|outperform|underperform|"
    r"buy\s+rating|sell\s+rating|hold\s+rating|price\s+target)\b",
    re.IGNORECASE,
)


# ── Generic helpers ─────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc)


def _parse_dt(value):
    """Best-effort parse of a datetime in any of the source-specific shapes."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except Exception:
            return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    # AV format: 20260609T142200
    if re.fullmatch(r"\d{8}T\d{6}", s):
        try:
            return datetime.strptime(s, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        except Exception:
            pass
    # ISO-ish
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        pass
    return None


def _keyword_score(headline):
    """Crude ±0.25 score from headline keywords. 0 if both/neither matched."""
    h = headline or ""
    bull = bool(BULL_KW.search(h))
    bear = bool(BEAR_KW.search(h))
    if bull and not bear:
        return 0.25
    if bear and not bull:
        return -0.25
    return 0.0


# ── LLM scoring (OpenRouter, item-immutable cache) ──────────────────────
# Per-item cache keyed by hash(headline) — once a (ticker, headline) is scored
# the result is banked forever; the headline never changes. The hourly TTL
# lives in the *fetch* step (refresh_us/refresh_klse/refresh_crypto), not here.

def _load_llm_env():
    """Load OPENROUTER_API_KEY from sentiment-cache's .env if not in environ.
    Single source of truth — operator manages one OpenRouter key for the project."""
    if os.environ.get("OPENROUTER_API_KEY"):
        return True
    env_path = PROJECT_ROOT / ".claude" / "skills" / "sentiment-cache" / ".env"
    if not env_path.is_file():
        return False
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip(); v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def _item_hash(headline):
    """Stable cache key for an item. Headline-only; the same article reaching
    multiple tickers gets independently scored (cache keyed by ticker file)."""
    h = (headline or "").strip().lower()
    return hashlib.sha256(h.encode("utf-8")).hexdigest()[:16]


def _llm_cache_path(ticker):
    return LLM_SCORE_CACHE / f"{ticker.upper()}.json"


def _llm_cache_load(ticker):
    return _read_json(_llm_cache_path(ticker)) or {}


def _llm_cache_save(ticker, cache):
    p = _llm_cache_path(ticker)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, indent=2, default=str))


LLM_SYSTEM = (
    "You are a financial sentiment classifier for news headlines. "
    "You receive a TICKER and a numbered list of headlines. For each headline, "
    "return ONE JSON object: "
    '{"relevance": "primary"|"mention"|"none", "score": -1.0..1.0}. '
    "relevance='primary' only when the TICKER (or its commonly-known company name) "
    "is the main subject of the headline. relevance='mention' when the TICKER "
    "appears but isn't the focus (e.g. sector comparison, peer mention). "
    "relevance='none' when the TICKER doesn't appear at all. "
    "score range: -1=strongly bearish, -0.3=somewhat bearish, 0=neutral, "
    "+0.3=somewhat bullish, +1=strongly bullish. "
    "When relevance is 'mention' or 'none', set score=0.0. "
    "Return ONLY a JSON array of objects, one per headline, same order. No prose, no markdown."
)


def _llm_score_batch(ticker, headlines, model=None, timeout=60):
    """POST a batch of headlines to OpenRouter. Returns (list_of_dicts, error)."""
    if not headlines:
        return [], None
    if not _load_llm_env():
        return None, "OPENROUTER_API_KEY missing (set in .claude/skills/sentiment-cache/.env)"
    model = model or LLM_DEFAULT_MODEL
    api_key = os.environ["OPENROUTER_API_KEY"]
    numbered = "\n".join(f"{i+1}. {h[:300]}" for i, h in enumerate(headlines))
    user = f"TICKER: {ticker}\nHeadlines (n={len(headlines)}):\n{numbered}\n\nReturn JSON array only."
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": LLM_SYSTEM},
            {"role": "user", "content": user},
        ],
        "temperature": 0.0,
        "max_tokens": 800,
    }).encode()
    req = urllib.request.Request(
        OPENROUTER_URL, data=body, method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/local/trading-advisor",
            "X-Title": "trading-advisor news-glyph scorer",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    content = (d.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
    # Strip markdown fence if present
    if content.startswith("```"):
        parts = content.split("```", 2)
        content = parts[1].lstrip()
        if content.startswith("json"):
            content = content[4:].lstrip()
        content = content.rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(content)
    except Exception as e:
        return None, f"JSON parse failed: {e} (content: {content[:120]})"
    if not isinstance(parsed, list) or len(parsed) != len(headlines):
        return None, f"Expected list of {len(headlines)}, got {type(parsed).__name__} len={len(parsed) if isinstance(parsed,list) else '?'}"
    out = []
    for item in parsed:
        if not isinstance(item, dict):
            out.append({"relevance": "none", "score": 0.0})
            continue
        rel = str(item.get("relevance", "none")).lower().strip()
        if rel not in ("primary", "mention", "none"):
            rel = "none"
        try:
            score = float(item.get("score", 0.0))
            score = max(-1.0, min(1.0, score))
        except Exception:
            score = 0.0
        # Enforce: only 'primary' relevance carries nonzero score
        if rel != "primary":
            score = 0.0
        out.append({"relevance": rel, "score": score})
    return out, None


def llm_score_items_for_ticker(ticker, items, force=False, verbose=False):
    """Enrich items with LLM scores. Caches by hash(headline) — only LLM-calls
    items that aren't already cached. Returns (n_cached, n_fetched, error_or_none)."""
    if not items:
        return 0, 0, None
    cache = _llm_cache_load(ticker)
    # Identify items needing LLM call
    needed = []  # (idx_in_items, headline_hash, headline)
    for idx, it in enumerate(items):
        headline = (it.get("headline") or "").strip()
        if not headline:
            continue
        h = _item_hash(headline)
        if not force and h in cache:
            continue
        needed.append((idx, h, headline))
    n_cached = len(items) - len(needed)
    if not needed:
        return n_cached, 0, None
    # Batch the LLM calls
    n_fetched = 0
    last_err = None
    for start in range(0, len(needed), LLM_BATCH_SIZE):
        chunk = needed[start:start + LLM_BATCH_SIZE]
        headlines = [c[2] for c in chunk]
        # Try primary model, fall back to secondary on hard failure
        for model in (LLM_DEFAULT_MODEL, LLM_FALLBACK_MODEL):
            out, err = _llm_score_batch(ticker, headlines, model=model)
            if not err:
                break
            if verbose:
                print(f"    [llm] {model} failed: {err[:80]}; trying fallback")
        if err:
            last_err = err
            if verbose:
                print(f"    [llm] batch failed both models: {err[:120]}")
            continue
        for (idx, h, _hl), result in zip(chunk, out):
            cache[h] = {
                "relevance": result["relevance"],
                "score": result["score"],
                "scored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "model": model,
            }
            n_fetched += 1
        # Small pace between batches — OpenRouter free is ~20 req/min depending on model
        time.sleep(1.0)
    _llm_cache_save(ticker, cache)
    return n_cached, n_fetched, last_err


def _apply_llm_scores(ticker, items):
    """Replace each item's sentiment_score with the cached LLM score where available.
    Adds 'score_source' field: 'llm' | 'keyword' | 'av' (for AV-pre-scored items)."""
    cache = _llm_cache_load(ticker)
    if not cache:
        # Annotate existing items with their pre-LLM source
        for it in items:
            if it.get("origin", "").startswith("av") and "score_source" not in it:
                it["score_source"] = "av"
            elif "score_source" not in it:
                it["score_source"] = "keyword"
        return items
    for it in items:
        # AV items keep their AV-attributed score (per-ticker, already correct)
        if it.get("origin", "").startswith("av"):
            it["score_source"] = "av"
            continue
        headline = it.get("headline") or ""
        entry = cache.get(_item_hash(headline))
        if entry:
            it["sentiment_score"] = entry["score"]
            it["score_source"] = "llm"
            it["llm_relevance"] = entry["relevance"]
            # If LLM judged this 'mention' or 'none', also flip the origin tag for UI clarity
            if entry["relevance"] != "primary" and it.get("origin", "").startswith("finnhub"):
                it["origin"] = f"finnhub-news ({entry['relevance']})"
        else:
            it["score_source"] = "keyword"
    return items


def _read_json(path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))


# ── Item normalization ──────────────────────────────────────────────────
# Every news item, regardless of source, gets normalized to:
#   {
#     "dt":              ISO timestamp UTC,
#     "headline":        str,
#     "source":          str,
#     "sentiment_score": float in [-1, 1] or None,
#     "is_analyst_action": bool,
#     "analyst_detail":  str (e.g. "Cantor Fitzgerald: Neutral → Overweight, PT $14") or None,
#     "url":             str or None,
#     "origin":          "av" | "finnhub-news" | "finnhub-rating" | "klse" | "crypto",
#   }


def _normalize_av_item(ticker, item):
    dt = _parse_dt(item.get("time_published"))
    # AV ships per-ticker sentiment in `ticker_sentiment` array.
    ts = None
    for x in (item.get("ticker_sentiment") or []):
        if (x.get("ticker") or "").upper() == ticker.upper():
            ts = x
            break
    try:
        score = float((ts or {}).get("ticker_sentiment_score")) if ts else None
    except (TypeError, ValueError):
        score = None
    headline = (item.get("title") or "").strip()
    return {
        "dt": dt.isoformat() if dt else None,
        "headline": headline,
        "source": item.get("source") or "?",
        "sentiment_score": score,
        "is_analyst_action": bool(ANALYST_KW.search(headline)),
        "analyst_detail": None,
        "url": item.get("url"),
        "origin": "av",
    }


def _normalize_finnhub_news_item(item, ticker=None):
    """Normalize a Finnhub /company-news entry.

    Attribution guard: Finnhub returns articles that *mention* the queried
    ticker but may be primarily about a different company (e.g. an Axon-focused
    headline that lists KTOS in the body). Headlines without the ticker get
    their keyword sentiment muted to 0 to prevent unrelated bullishness/
    bearishness from polluting the per-ticker aggregate. Mark the origin so
    the UI can flag these as 'mention only'.
    """
    dt = _parse_dt(item.get("datetime"))
    headline = (item.get("headline") or "").strip()
    score = _keyword_score(headline)
    origin = "finnhub-news"
    if ticker and score != 0 and ticker.upper() not in headline.upper():
        # Ticker symbol not in headline → either a name-only mention (company
        # name like "Kratos" instead of "KTOS") or a sector article that
        # mentions the ticker in the body. Halve the score to discount spillover
        # without nuking legitimate sector reads.
        score = round(score * 0.5, 2)
        origin = "finnhub-news (no-ticker)"
    return {
        "dt": dt.isoformat() if dt else None,
        "headline": headline,
        "source": item.get("source") or "Finnhub",
        "sentiment_score": score,
        "is_analyst_action": bool(ANALYST_KW.search(headline)),
        "analyst_detail": None,
        "url": item.get("url"),
        "origin": origin,
    }


def _normalize_finnhub_rating(item):
    """Convert a Finnhub upgrade/downgrade entry into a synthesized news item."""
    dt = _parse_dt(item.get("gradeTime"))
    action = (item.get("action") or "").lower()  # up/down/init/main/reit
    company = item.get("company") or "Analyst"
    from_g = item.get("fromGrade") or ""
    to_g = item.get("toGrade") or ""
    if action == "up":
        headline = f"{company} upgrades to {to_g}" + (f" (from {from_g})" if from_g else "")
        score = 0.40
    elif action == "down":
        headline = f"{company} downgrades to {to_g}" + (f" (from {from_g})" if from_g else "")
        score = -0.40
    elif action == "init":
        headline = f"{company} initiates coverage: {to_g}"
        # Coverage initiation is mildly positive only if the rating is itself bullish.
        score = 0.20 if re.search(r"buy|outperform|overweight", to_g, re.I) else (
                -0.20 if re.search(r"sell|underperform|underweight", to_g, re.I) else 0.0)
    else:  # main / reit / unknown
        headline = f"{company} reiterates {to_g}" if to_g else f"{company}: action={action}"
        score = 0.0
    detail = f"{company}: {from_g or '—'} → {to_g or '—'} (action={action})"
    return {
        "dt": dt.isoformat() if dt else None,
        "headline": headline,
        "source": company,
        "sentiment_score": score,
        "is_analyst_action": True,
        "analyst_detail": detail,
        "url": None,
        "origin": "finnhub-rating",
    }


def _normalize_klse_item(item):
    dt = _parse_dt(item.get("date") or item.get("dt"))
    headline = (item.get("headline") or item.get("title") or "").strip()
    return {
        "dt": dt.isoformat() if dt else None,
        "headline": headline,
        "source": item.get("source") or "klsescreener",
        "sentiment_score": _keyword_score(headline),
        "is_analyst_action": bool(ANALYST_KW.search(headline)),
        "analyst_detail": None,
        "url": item.get("url"),
        "origin": "klse",
    }


def _normalize_crypto_item(item):
    dt = _parse_dt(item.get("created_at") or item.get("dt") or item.get("date"))
    headline = (item.get("description") or item.get("headline") or item.get("title") or "").strip()
    # CoinGecko status updates can be long-form; truncate for display sanity.
    if len(headline) > 200:
        headline = headline[:197] + "…"
    return {
        "dt": dt.isoformat() if dt else None,
        "headline": headline,
        "source": item.get("source") or "CoinGecko",
        "sentiment_score": _keyword_score(headline),
        "is_analyst_action": False,  # crypto has no equity-style analyst actions
        "analyst_detail": None,
        "url": item.get("url"),
        "origin": "crypto",
    }


# ── Per-asset-class loaders ─────────────────────────────────────────────

def _load_us_items(ticker):
    items = []
    # AV cache (pre-scored sentiment)
    av = _read_json(US_NEWS_CACHE / f"{ticker.upper()}.json")
    if av and isinstance(av.get("feed"), list):
        for it in av["feed"]:
            items.append(_normalize_av_item(ticker, it))
    # Finnhub cache (analyst ratings + headlines)
    fh = _read_json(FINNHUB_CACHE / f"{ticker.upper()}.json")
    if fh:
        for it in (fh.get("ratings") or []):
            items.append(_normalize_finnhub_rating(it))
        for it in (fh.get("news") or []):
            items.append(_normalize_finnhub_news_item(it, ticker=ticker))
    return _apply_llm_scores(ticker, items)


def _load_klse_items(code):
    code = str(code).replace(".KL", "").strip()
    d = _read_json(KLSE_NEWS_CACHE / f"{code}.json")
    if not d:
        return []
    items = [_normalize_klse_item(it) for it in (d.get("items") or [])]
    return _apply_llm_scores(code, items)


def _load_crypto_items(coin):
    coin = coin.lower().strip()
    d = _read_json(CRYPTO_NEWS_CACHE / f"{coin}.json")
    if not d:
        return []
    items = [_normalize_crypto_item(it) for it in (d.get("items") or [])]
    return _apply_llm_scores(coin, items)


# ── Glyph computation ───────────────────────────────────────────────────

def compute_glyph(items):
    """Turn a normalized item list into the dashboard payload.

    Returns:
        {
          "glyph": "🟢"|"🔴"|"⚪",
          "analyst_72h": bool,
          "modifier": ""|"❗",
          "items_72h": [...],          # for dropdown — items in last 72h
          "older_context": [...],      # for dropdown — items 72h-7d
          "caveat": ANALYST_CAVEAT or None,
          "summary": short str e.g. "2 bullish in 72h",
        }
    """
    now = _now()
    items_72h, older = [], []
    for it in items:
        dt = _parse_dt(it.get("dt"))
        if not dt:
            continue
        age_h = (now - dt).total_seconds() / 3600.0
        if age_h < 0:  # future-dated; ignore
            continue
        if age_h <= 72:
            items_72h.append(it)
        elif age_h <= 14 * 24:
            older.append(it)
    # Sort newest first
    items_72h.sort(key=lambda x: x.get("dt") or "", reverse=True)
    older.sort(key=lambda x: x.get("dt") or "", reverse=True)

    analyst_72h = any(it.get("is_analyst_action") for it in items_72h)
    modifier = "❗" if analyst_72h else ""

    # Aggregate sentiment over 72h items that have a score
    scored = [it["sentiment_score"] for it in items_72h
              if isinstance(it.get("sentiment_score"), (int, float))]
    if not items_72h:
        glyph = "⚪"
        summary = "no news in 72h"
    elif scored:
        avg = sum(scored) / len(scored)
        if avg >= SENT_BULL_THR:
            glyph = "🟢"
            summary = f"{len(items_72h)} item(s) in 72h, net bullish ({avg:+.2f})"
        elif avg <= SENT_BEAR_THR:
            glyph = "🔴"
            summary = f"{len(items_72h)} item(s) in 72h, net bearish ({avg:+.2f})"
        else:
            glyph = "⚪"
            summary = f"{len(items_72h)} item(s) in 72h, mixed ({avg:+.2f})"
    else:
        glyph = "⚪"
        summary = f"{len(items_72h)} item(s) in 72h, unscored"

    return {
        "glyph": glyph,
        "analyst_72h": analyst_72h,
        "modifier": modifier,
        "items_72h": items_72h,
        "older_context": older,
        "caveat": ANALYST_CAVEAT if analyst_72h else None,
        "summary": summary,
    }


def glyph_for(ticker, asset_class):
    """Public API used by dashboard.py. asset_class ∈ {'us', 'klse', 'crypto'}."""
    ac = (asset_class or "").lower()
    if ac == "us":
        items = _load_us_items(ticker)
    elif ac == "klse":
        items = _load_klse_items(ticker)
    elif ac == "crypto":
        items = _load_crypto_items(ticker)
    else:
        return None
    return compute_glyph(items)


# ── Refreshers ──────────────────────────────────────────────────────────

def _yf_upgrades_downgrades(ticker):
    """Fetch analyst rating actions via yfinance. Free, no key.
    Returns list[{gradeTime (unix), fromGrade, toGrade, company, action}] —
    same shape as Finnhub's upgrade_downgrade so the rest of the pipeline
    is source-agnostic. Finnhub's structured endpoint is paywalled on the
    free tier (HTTP 403), so yfinance is the actual data source today.
    """
    try:
        import yfinance as yf  # type: ignore
    except ImportError:
        return [], "yfinance not installed"
    try:
        df = yf.Ticker(ticker).upgrades_downgrades
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"
    if df is None or len(df) == 0:
        return [], None
    rows = []
    for idx, r in df.iterrows():
        try:
            ts = int(idx.timestamp())
        except Exception:
            continue
        rows.append({
            "gradeTime": ts,
            "fromGrade": r.get("FromGrade") or "",
            "toGrade":   r.get("ToGrade") or "",
            "company":   r.get("Firm") or "",
            "action":   (r.get("Action") or "").lower(),  # up/down/init/main/reit
        })
    return rows, None


def refresh_us(tickers, force=False, max_age_h=1.0, skip_llm=False):
    """For each ticker, fetch analyst actions (yfinance) + headlines (Finnhub).
    Persists to .claude/cache/finnhub_news/{TICKER}.json.
    """
    try:
        import finnhub_client as fh
    except ImportError as e:
        print(f"[ERR] cannot import finnhub_client: {e}")
        return
    finnhub_ok = fh.is_configured()
    if not finnhub_ok:
        print("[warn] FINNHUB_API_KEY not set — proceeding with yfinance only")
    FINNHUB_CACHE.mkdir(parents=True, exist_ok=True)
    for tk in tickers:
        tk_u = tk.upper().strip()
        path = FINNHUB_CACHE / f"{tk_u}.json"
        if not force and path.is_file():
            try:
                age = (datetime.now(timezone.utc) -
                       datetime.fromisoformat(json.loads(path.read_text())["fetched_at"])).total_seconds() / 3600
                if age < max_age_h:
                    print(f"  [skip] {tk_u} cache {age:.1f}h old (<{max_age_h}h)")
                    continue
            except Exception:
                pass
        print(f"  [fetch] {tk_u}", end=" ", flush=True)
        ratings, err_r = _yf_upgrades_downgrades(tk_u)
        if finnhub_ok:
            news, err_n = fh.company_news(tk_u, days=7)
            time.sleep(fh.PACE_SECONDS)
        else:
            news, err_n = [], "FINNHUB_API_KEY not set"
        payload = {
            "ticker": tk_u,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ratings": ratings,
            "ratings_source": "yfinance",
            "ratings_error": err_r,
            "news": news if not err_n else [],
            "news_source": "finnhub" if finnhub_ok and not err_n else None,
            "news_error": err_n,
        }
        _write_json(path, payload)
        print(f"ratings={len(payload['ratings'])} news={len(payload['news'])}"
              + (f" rating_err={err_r}" if err_r else "")
              + (f" news_err={err_n}" if err_n else ""))
        if not skip_llm:
            _autoscore_after_refresh("us", tk_u)


def refresh_klse(codes, force=False, max_age_h=1.0, skip_llm=False):
    """Scrape klsescreener.com/v2/news/stock/{CODE} for each code.
    Stored as items[] of {date, source, headline, url}.
    """
    KLSE_NEWS_CACHE.mkdir(parents=True, exist_ok=True)
    for code in codes:
        code = str(code).replace(".KL", "").strip()
        path = KLSE_NEWS_CACHE / f"{code}.json"
        if not force and path.is_file():
            try:
                age = (datetime.now(timezone.utc) -
                       datetime.fromisoformat(json.loads(path.read_text())["fetched_at"])).total_seconds() / 3600
                if age < max_age_h:
                    print(f"  [skip] {code} cache {age:.1f}h old")
                    continue
            except Exception:
                pass
        url = f"https://www.klsescreener.com/v2/news/stock/{code}"
        print(f"  [fetch] {code}", end=" ", flush=True)
        items = _scrape_klse_news(url)
        payload = {
            "code": code,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "items": items,
        }
        _write_json(path, payload)
        print(f"items={len(items)}")
        if not skip_llm:
            _autoscore_after_refresh("klse", code)
        time.sleep(1.0)


def _scrape_klse_news(url):
    """urllib + regex scrape of klsescreener's per-stock news page.

    Page structure (verified 2026-06-09):
      <div class="article flex-1">
        <div class="item-title"><h2><a href="/v2/news/view/...">HEADLINE</a></h2></div>
        <div>SUMMARY</div>
        <div class="item-title-secondary subtitle">
          <span>SOURCE</span>
          <span data-date="YYYY-MM-DD HH:MM:SS">...</span>
        </div>
      </div>
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            html_text = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return [{"_error": f"{type(e).__name__}: {e}"}]

    tag_strip = re.compile(r'<[^>]+>')
    def _clean(s):
        return tag_strip.sub("", s or "").replace("&nbsp;", " ").strip()

    # Each article is a <div class="article ..."> block. Capture each block's
    # span via a permissive non-greedy match; closing div is implicit (we slice
    # forward up to the next article-start or 4kB, whichever is smaller).
    items = []
    starts = [m.start() for m in re.finditer(r'<div\s+class="article\b', html_text)]
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else min(s + 4000, len(html_text))
        block = html_text[s:e]
        # Headline + link
        title_m = re.search(
            r'<div[^>]*class="item-title"[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            block, re.DOTALL | re.IGNORECASE,
        )
        if not title_m:
            continue
        href = title_m.group(1)
        title = _clean(title_m.group(2))
        if not title:
            continue
        # Source + date — pulled independently from the article block.
        src = "klsescreener"
        dt = None
        date_m = re.search(r'data-date="([^"]+)"', block)
        if date_m:
            raw = date_m.group(1).strip()
            # KL local time → tag as +08:00 so downstream UTC math is correct.
            if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", raw):
                dt = raw.replace(" ", "T") + "+08:00"
            else:
                dt = raw
        sub_m = re.search(r'class="item-title-secondary[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL | re.IGNORECASE)
        if sub_m:
            first_span = re.search(r'<span[^>]*>(.*?)</span>', sub_m.group(1), re.DOTALL)
            if first_span:
                cleaned = _clean(first_span.group(1))
                if cleaned and not re.search(r'\d{4}-\d{2}-\d{2}', cleaned):
                    src = cleaned
        items.append({
            "headline": title,
            "source": src,
            "date": dt,
            "url": href if href.startswith("http") else f"https://www.klsescreener.com{href}",
        })
        if len(items) >= 20:
            break
    return items


_RSS_FEEDS = [
    ("CoinDesk",      "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt",       "https://decrypt.co/feed"),
]

# Coin → match keywords. For the major coins we filter the aggregate RSS by
# name + symbol. Long-tail alts won't get RSS coverage → glyph shows ⚪ (correct
# degraded behavior, per design).
_COIN_KEYWORDS = {
    "bitcoin":      [r"\bbitcoin\b", r"\bBTC\b"],
    "ethereum":     [r"\bethereum\b", r"\bETH\b", r"\bether\b"],
    "solana":       [r"\bsolana\b", r"\bSOL\b"],
    "binancecoin":  [r"\bbinance\s*coin\b", r"\bBNB\b"],
    "ripple":       [r"\bripple\b", r"\bXRP\b"],
    "cardano":      [r"\bcardano\b", r"\bADA\b"],
    "dogecoin":     [r"\bdogecoin\b", r"\bDOGE\b"],
    "hyperliquid":  [r"\bhyperliquid\b", r"\bHYPE\b"],
    "ondo-finance": [r"\bondo\b"],
    "chainlink":    [r"\bchainlink\b", r"\bLINK\b"],
    "avalanche-2":  [r"\bavalanche\b", r"\bAVAX\b"],
    "polkadot":     [r"\bpolkadot\b", r"\bDOT\b"],
    "arbitrum":     [r"\barbitrum\b", r"\bARB\b"],
    "optimism":     [r"\boptimism\b", r"\bOP\b"],
    "aptos":        [r"\baptos\b", r"\bAPT\b"],
    "sui":          [r"\bsui\b"],
    "litecoin":     [r"\blitecoin\b", r"\bLTC\b"],
}


class _Redirect308(urllib.request.HTTPRedirectHandler):
    """urllib doesn't follow 308 by default (older stdlib). Handle it."""
    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_301(req, fp, 301, msg, headers)


def _fetch_rss_items(url, timeout=15):
    """Return list of dicts {title, link, pubDate, description}."""
    import xml.etree.ElementTree as ET
    opener = urllib.request.build_opener(_Redirect308())
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh) trading-advisor/1.8",
        "Accept": "application/rss+xml, application/xml, text/xml",
    })
    try:
        with opener.open(req, timeout=timeout) as r:
            body = r.read()
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        return [], f"ParseError: {e}"
    items = []
    for it in root.iter("item"):
        def t(tag):
            el = it.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""
        items.append({
            "title":       t("title"),
            "link":        t("link"),
            "pubDate":     t("pubDate"),
            "description": t("description"),
        })
    return items, None


def _parse_rfc822(s):
    if not s:
        return None
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def refresh_crypto(coins, force=False, max_age_h=1.0, skip_llm=False):
    """Refresh per-coin news by filtering aggregate crypto-news RSS feeds.

    Free + no key. Covers majors well (BTC, ETH, SOL, ...); long-tail alts may
    show ⚪ no-news-in-72h — that's accurate, not a bug.
    """
    CRYPTO_NEWS_CACHE.mkdir(parents=True, exist_ok=True)

    # Fetch each RSS feed ONCE and cache in memory, then filter per coin.
    feed_cache = []
    for feed_name, url in _RSS_FEEDS:
        items, err = _fetch_rss_items(url)
        if err:
            print(f"  [feed-err] {feed_name}: {err}")
            continue
        feed_cache.append((feed_name, items))
        time.sleep(0.5)

    for coin in coins:
        coin = coin.lower().strip()
        path = CRYPTO_NEWS_CACHE / f"{coin}.json"
        if not force and path.is_file():
            try:
                age = (datetime.now(timezone.utc) -
                       datetime.fromisoformat(json.loads(path.read_text())["fetched_at"])).total_seconds() / 3600
                if age < max_age_h:
                    print(f"  [skip] {coin} cache {age:.1f}h old")
                    continue
            except Exception:
                pass
        kws = _COIN_KEYWORDS.get(coin)
        if not kws:
            # Best-effort: split slug on '-' and match each token.
            kws = [rf"\b{re.escape(tok)}\b" for tok in coin.split("-") if len(tok) >= 3]
        pat = re.compile("|".join(kws), re.IGNORECASE) if kws else None
        items_out = []
        if pat:
            for feed_name, items in feed_cache:
                for it in items:
                    title = it.get("title") or ""
                    desc = it.get("description") or ""
                    if pat.search(title) or pat.search(desc):
                        dt = _parse_rfc822(it.get("pubDate"))
                        items_out.append({
                            "headline": title,
                            "source": feed_name,
                            "created_at": dt.isoformat() if dt else None,
                            "url": it.get("link"),
                        })
        # Sort newest first, cap at 30
        items_out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        items_out = items_out[:30]
        payload = {
            "coin": coin,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "items": items_out,
            "feeds_polled": [f for f, _ in feed_cache],
        }
        _write_json(path, payload)
        print(f"  [{coin}] items={len(items_out)} (matched {len(kws)} keywords across {len(feed_cache)} feeds)")
        if not skip_llm:
            _autoscore_after_refresh("crypto", coin)


def _autoscore_after_refresh(asset_class, key, verbose=True):
    """Run LLM scoring on the items now in cache for this key. Items pre-scored
    by AV (origin starts with 'av') are skipped. Idempotent — already-scored
    items are noops via the per-item cache."""
    if asset_class == "us":
        raw = _load_us_items(key)
    elif asset_class == "klse":
        raw = _load_klse_items(key)
    elif asset_class == "crypto":
        raw = _load_crypto_items(key)
    else:
        return
    needs_llm = [it for it in raw if not (it.get("origin") or "").startswith("av")]
    if not needs_llm:
        return
    n_cached, n_fetched, err = llm_score_items_for_ticker(key.upper(), needs_llm, verbose=verbose)
    if verbose:
        if err and n_fetched == 0:
            print(f"    [llm] {key}: ERR {err[:100]}")
        else:
            print(f"    [llm] {key}: scored={n_fetched} cached_skipped={n_cached}" +
                  (f" partial_err={err[:60]}" if err else ""))


# ── CLI ─────────────────────────────────────────────────────────────────

def _cli():
    ap = argparse.ArgumentParser(description="News-glyph cache builder + reader")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_us = sub.add_parser("refresh-us", help="Fetch Finnhub analyst actions + news for US tickers")
    p_us.add_argument("--tickers", required=True, help="Comma-separated symbols")
    p_us.add_argument("--force", action="store_true")
    p_us.add_argument("--max-age-h", type=float, default=1.0)
    p_us.add_argument("--no-llm", action="store_true", help="Skip auto-LLM-scoring after fetch.")

    p_kl = sub.add_parser("refresh-klse", help="Scrape klsescreener news pages")
    p_kl.add_argument("--codes", required=True, help="Comma-separated 4-digit Bursa codes")
    p_kl.add_argument("--force", action="store_true")
    p_kl.add_argument("--max-age-h", type=float, default=1.0)
    p_kl.add_argument("--no-llm", action="store_true", help="Skip auto-LLM-scoring after fetch.")

    p_cr = sub.add_parser("refresh-crypto", help="Fetch CoinGecko status_updates per coin")
    p_cr.add_argument("--coins", required=True, help="Comma-separated CoinGecko IDs")
    p_cr.add_argument("--force", action="store_true")
    p_cr.add_argument("--max-age-h", type=float, default=1.0)
    p_cr.add_argument("--no-llm", action="store_true", help="Skip auto-LLM-scoring after fetch.")

    p_sc = sub.add_parser("score", help="LLM-score items currently in the news cache for one or more tickers (no fetch)")
    p_sc.add_argument("--tickers", required=True, help="Comma-separated keys (US: symbol; KLSE: 4-digit code; crypto: CoinGecko slug)")
    p_sc.add_argument("--asset-class", required=True, choices=["us", "klse", "crypto"])
    p_sc.add_argument("--force", action="store_true", help="Re-score even items already in the LLM cache.")

    p_show = sub.add_parser("show", help="Print the computed glyph + items for one ticker")
    p_show.add_argument("--ticker", required=True)
    p_show.add_argument("--asset-class", required=True, choices=["us", "klse", "crypto"])

    args = ap.parse_args()
    if args.cmd == "refresh-us":
        refresh_us([t.strip() for t in args.tickers.split(",") if t.strip()],
                   force=args.force, max_age_h=args.max_age_h, skip_llm=args.no_llm)
    elif args.cmd == "refresh-klse":
        refresh_klse([c.strip() for c in args.codes.split(",") if c.strip()],
                     force=args.force, max_age_h=args.max_age_h, skip_llm=args.no_llm)
    elif args.cmd == "refresh-crypto":
        refresh_crypto([c.strip() for c in args.coins.split(",") if c.strip()],
                       force=args.force, max_age_h=args.max_age_h, skip_llm=args.no_llm)
    elif args.cmd == "score":
        keys = [t.strip() for t in args.tickers.split(",") if t.strip()]
        for k in keys:
            print(f"[score] {args.asset_class}: {k}")
            _autoscore_after_refresh(args.asset_class, k)
            # If --force, also bust the per-item cache for these items first
            if args.force:
                # Reload items, then call llm_score with force=True
                if args.asset_class == "us":      items = _load_us_items(k)
                elif args.asset_class == "klse":  items = _load_klse_items(k)
                else:                              items = _load_crypto_items(k)
                needs_llm = [it for it in items if not (it.get("origin") or "").startswith("av")]
                llm_score_items_for_ticker(k.upper(), needs_llm, force=True, verbose=True)
    elif args.cmd == "show":
        result = glyph_for(args.ticker, args.asset_class)
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    _cli()
