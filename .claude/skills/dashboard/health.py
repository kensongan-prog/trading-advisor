#!/usr/bin/env python3
"""
health.py — data-health surface for the dashboard.

Why this exists: the v2.0.x patch series found four bugs where degraded data
looked identical to good data:
  - crypto-zip pairing wrong rows (twice — grid + BTFD)
  - KLSE Chinese headlines silently scoring to relevance=none
  - HN `num_comments>=3` filter silently dropping coverage
  - sentiment classifier 429s hiding StockTwits behind `present:false`

Each one rendered cleanly on the dashboard. The numbers were just quietly
wrong. This module surfaces per-source health so silent degradation becomes
operator-visible.

State taxonomy:
  fresh             — has data, within TTL
  stale             — has data, beyond TTL (the data is old but real)
  error_transient   — explicit transient failure (429, 5xx) — refresh fixes it
  error_permanent   — explicit permanent failure (auth, parse) — code/config fix
  no_coverage       — fetched cleanly, no data exists (small-cap with no news)
  missing           — no cache file at all

Pure-logic functions take inputs explicitly; side-effect functions (cache
walking) sit at the bottom and call into the pure ones. Tests target the
pure side.
"""
from datetime import datetime, timezone
from pathlib import Path
import json
import re

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
CACHE_ROOT = PROJECT_ROOT / ".claude" / "cache"


# ── State taxonomy ────────────────────────────────────────────────────────
STATE_FRESH           = "fresh"
STATE_STALE           = "stale"
STATE_ERR_TRANSIENT   = "error_transient"
STATE_ERR_PERMANENT   = "error_permanent"
STATE_NO_COVERAGE     = "no_coverage"
STATE_MISSING         = "missing"

# Priority order for surfacing (high = act on first).
_STATE_PRIORITY = {
    STATE_ERR_TRANSIENT: 4,    # refresh fixes; highest action priority
    STATE_ERR_PERMANENT: 3,    # code/config issue
    STATE_STALE:          2,
    STATE_MISSING:        1,
    STATE_NO_COVERAGE:    0,   # informational only
    STATE_FRESH:         -1,
}


def state_priority(s):
    return _STATE_PRIORITY.get(s, 0)


# ── TTLs per source (hours) ───────────────────────────────────────────────
# Past TTL = "stale" but data still real. Tightened conservatively — the goal
# is to alert the operator when the data is old enough that decisions made
# from it are likely wrong, not to demand constant refreshing.
TTL_HOURS = {
    "us_news":         48,
    "finnhub_news":    24,
    "klse_news":       24,
    "crypto_news":     24,
    "reddit_sentiment": 24,
    "stocktwits_sentiment": 12,   # ST updates intraday
    "hn_sentiment":    24,
    "sentiment":       24,       # LLM composite re-score
    "polymarket":      12,
    "sector_rotation":  6,
    "screener":        12,
    "klse_announcements": 48,
    "klse_fundamentals":  72,
    "crypto_unlocks":  168,      # weekly check is fine
}


# ── Refresh routing per source ────────────────────────────────────────────
# Maps every TTL_HOURS key to its refresh method:
#   ("flag", "--flag")       — pass this flag to dashboard.py (server can run it)
#   ("cli",  "relative/path") — run this standalone Python CLI, then rebuild
#   ("agent",)               — agent/WebFetch skill; a server process cannot do it
#
# Note on klse-refresh / klse-announcements: their SKILL.md says "manual by
# design." A human clicking a refresh button IS manual initiation — one-click
# does not violate that doctrine; it just saves the operator needing the CLI path.
REFRESH_VIA = {
    "us_news":              ("flag", "--refresh-news"),
    "finnhub_news":         ("flag", "--refresh-news-glyph"),
    "klse_news":            ("flag", "--refresh-news-glyph"),
    "crypto_news":          ("flag", "--refresh-news-glyph"),
    "reddit_sentiment":     ("flag", "--refresh-sentiment"),
    "stocktwits_sentiment": ("flag", "--refresh-sentiment"),
    "hn_sentiment":         ("flag", "--refresh-sentiment"),
    "sentiment":            ("flag", "--refresh-sentiment"),
    "polymarket":           ("flag", "--refresh-polymarket"),
    "sector_rotation":      ("flag", "--with-discovery"),
    "screener":             ("flag", "--with-discovery"),
    "klse_announcements":   ("cli",  ".claude/skills/klse-announcements/klse_announcements.py"),
    "klse_fundamentals":    ("cli",  ".claude/skills/klse-refresh/klse_refresh.py"),
    "crypto_unlocks":       ("agent",),
}


def source_refresh_via(source_name):
    """Return the REFRESH_VIA entry for source_name, or None if unknown.
    Handles sentiment.* composite sub-sources (e.g. 'sentiment.stocktwits')."""
    if source_name in REFRESH_VIA:
        return REFRESH_VIA[source_name]
    if source_name and source_name.startswith("sentiment."):
        return REFRESH_VIA.get("sentiment")
    return None


def validate_refresh_source(source_name):
    """Validate a source name for the /api/refresh-source endpoint.
    Returns (True, via_tuple) on success, (False, error_string) on failure."""
    via = source_refresh_via(source_name)
    if via is None:
        return False, f"unknown source {source_name!r} — valid: {sorted(TTL_HOURS)}"
    if via[0] == "agent":
        return False, f"{source_name} is agent-refresh only — run a session to refresh it"
    return True, via


# ── Error classification ──────────────────────────────────────────────────
# Mirror the sentiment_cache._is_transient_error logic so health and the
# scorer stay in sync on what "transient" means. Tests pin this.
_TRANSIENT_MARKERS = ("HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504",
                      "URLError", "timeout", "Timeout", "TimeoutError",
                      "rate limit", "rate-limit", "temporarily")


def is_transient_error(err_msg):
    """True if the error string looks like a retry-might-fix-it failure."""
    if not err_msg or not isinstance(err_msg, str):
        return False
    low = err_msg.lower()
    for m in _TRANSIENT_MARKERS:
        if m.lower() in low:
            return True
    return False


# ── Pure: classify a single cache file's state ────────────────────────────
def classify_file_state(payload, ttl_hours, data_field=None, now=None):
    """Given a parsed JSON payload and a TTL, return (state, age_hours, detail).

    Inputs:
      payload    : dict or None (None means "file missing")
      ttl_hours  : numeric — beyond this age, state goes "stale"
      data_field : key whose presence/length indicates real data. If list-like,
                   non-empty list means coverage; if dict, non-empty dict.
                   If None, just checks `no_coverage` and `error` markers.
      now        : datetime for testability; defaults to now-UTC.

    Returns: (state, age_hours_or_None, detail_string)
    """
    if payload is None:
        return STATE_MISSING, None, "no cache file"

    # Explicit error field check first — overrides everything
    err = payload.get("error") or payload.get("_error")
    if err:
        if is_transient_error(str(err)):
            return STATE_ERR_TRANSIENT, _payload_age_h(payload, now), str(err)[:120]
        return STATE_ERR_PERMANENT, _payload_age_h(payload, now), str(err)[:120]

    # no_coverage marker — fetcher said "fetched OK, nothing exists"
    if payload.get("no_coverage"):
        return STATE_NO_COVERAGE, _payload_age_h(payload, now), str(payload.get("reason", ""))[:120]

    # Data presence check — falls through to "no_coverage" if nothing useful
    if data_field is not None:
        d = payload.get(data_field)
        empty = (
            d is None
            or (isinstance(d, (list, dict, str)) and len(d) == 0)
        )
        if empty:
            return STATE_NO_COVERAGE, _payload_age_h(payload, now), f"empty {data_field}"

    # Staleness — only matters if we got past the above
    age_h = _payload_age_h(payload, now)
    if age_h is None:
        # No timestamp at all; treat as fresh-with-caveat rather than stale
        return STATE_FRESH, None, "no fetched_at field"
    if age_h > ttl_hours:
        return STATE_STALE, age_h, f"{age_h:.0f}h old (TTL {ttl_hours}h)"
    return STATE_FRESH, age_h, f"{age_h:.0f}h old"


def _payload_age_h(payload, now=None):
    """Read whichever timestamp the payload carries (handles fetched_at /
    _fetched_at / scored_at / _generated_at across the different caches)."""
    now = now or datetime.now(timezone.utc)
    for key in ("fetched_at", "_fetched_at", "scored_at", "_generated_at", "_last_full_pass_at"):
        ts = payload.get(key)
        if ts:
            try:
                # tolerate trailing Z / +00:00 / no tz
                ts = ts.rstrip("Z")
                dt = datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return (now - dt).total_seconds() / 3600
            except Exception:
                continue
    return None


# ── Pure: classify the LLM-composite sentiment cache per source ────────────
def classify_sentiment_sources(sentiment_payload, now=None):
    """Sentiment composite stores per-source presence + error fields. Returns
    a dict {source_name: (state, detail)} for each of stocktwits/reddit/hackernews."""
    out = {}
    if not sentiment_payload:
        return {"stocktwits": (STATE_MISSING, "no composite"),
                "reddit":     (STATE_MISSING, "no composite"),
                "hackernews": (STATE_MISSING, "no composite")}
    sources = sentiment_payload.get("sources") or {}
    for name in ("stocktwits", "reddit", "hackernews"):
        s = sources.get(name) or {}
        if s.get("present"):
            out[name] = (STATE_FRESH, "scored OK")
            continue
        err = s.get("error")
        if err:
            if is_transient_error(str(err)):
                out[name] = (STATE_ERR_TRANSIENT, str(err)[:120])
            else:
                out[name] = (STATE_ERR_PERMANENT, str(err)[:120])
        else:
            # present:false + no error = legitimate no-coverage
            out[name] = (STATE_NO_COVERAGE, "fetched OK, no data")
    return out


# ── Pure: aggregate state records into a summary ──────────────────────────
def summarize(state_records):
    """state_records: iterable of dicts with at least {'state': ...}.
    Records that also carry 'source' get split into server-refreshable vs
    agent-only counts so the UI can show honest actionability."""
    counts = {STATE_FRESH: 0, STATE_STALE: 0, STATE_ERR_TRANSIENT: 0,
              STATE_ERR_PERMANENT: 0, STATE_NO_COVERAGE: 0, STATE_MISSING: 0}
    # Single pass: tally state counts and split refreshable records by whether
    # a server job can fix them (vs agent-only). source_refresh_via returns None
    # for unknown sources (e.g. test records with no 'source'), which fall into
    # neither bucket.
    _refreshable = frozenset([STATE_STALE, STATE_ERR_TRANSIENT, STATE_MISSING])
    n_server = n_agent = 0
    for r in state_records:
        s = r.get("state")
        counts[s] = counts.get(s, 0) + 1
        if s in _refreshable:
            via = source_refresh_via(r.get("source") or "")
            if via is not None:
                if via[0] == "agent":
                    n_agent += 1
                else:
                    n_server += 1
    total = sum(counts.values())
    healthy = counts[STATE_FRESH] + counts[STATE_NO_COVERAGE]  # both are OK states
    health_pct = (healthy / total * 100) if total else 100.0
    return {
        "counts": counts,
        "total": total,
        "healthy_pct": round(health_pct, 1),
        "n_actionable": counts[STATE_ERR_TRANSIENT] + counts[STATE_ERR_PERMANENT] + counts[STATE_STALE],
        "n_transient": counts[STATE_ERR_TRANSIENT],
        "n_permanent": counts[STATE_ERR_PERMANENT],
        "n_stale": counts[STATE_STALE],
        "n_actionable_server": n_server,   # fixable by Quick/Full button
        "n_actionable_agent": n_agent,     # need an agent session to fix
    }


# ── Side-effects: walk caches and produce records ─────────────────────────
def _load_json_safe(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


# Each entry: (source_name, cache_subdir, ticker_key_fn, data_field)
# ticker_key_fn maps a watchlist ticker → filename stem (e.g. "9431.KL" → "9431")
def _us_key(t):     return t.upper()
def _klse_key(t):   return re.sub(r"\.KL$", "", t.upper())
def _crypto_key(t): return t.lower()  # CoinGecko slugs are lowercase
def _identity(t):   return t

PER_TICKER_SOURCES = [
    # (name,              subdir,                  asset_classes,        key_fn,      data_field)
    ("us_news",            "us_news",              ("us",),              _us_key,     "feed"),
    ("finnhub_news",       "finnhub_news",         ("us",),              _us_key,     "news"),
    ("klse_news",          "klse_news",            ("klse",),            _klse_key,   "items"),
    ("klse_announcements", "klse_announcements",   ("klse",),            _klse_key,   None),
    ("klse_fundamentals",  "klse_fundamentals",    ("klse",),            _klse_key,   None),
    ("crypto_news",        "crypto_news",          ("crypto",),          _crypto_key, "items"),
    ("reddit_sentiment",   "reddit_sentiment",     ("us", "klse", "crypto"), _identity, "posts"),
    ("stocktwits_sentiment", "stocktwits_sentiment", ("us", "klse", "crypto"), _identity, "messages"),
    ("hn_sentiment",       "hn_sentiment",         ("us", "klse", "crypto"), _identity, "stories"),
]

GLOBAL_SOURCES = [
    # (name,            relative_path,                  ttl_h)
    ("polymarket",      "polymarket/events.json",       12),
    ("sector_rotation", "sector_rotation/data.json",     6),
    ("screener",        "screener/candidates.json",     12),
]


def collect_health(watchlist, now=None):
    """Walk all sources and return per-record state list. Pure-ish:
    deterministic given disk state + watchlist."""
    now = now or datetime.now(timezone.utc)
    records = []
    # Per-ticker sources
    for src_name, subdir, asset_classes, key_fn, data_field in PER_TICKER_SOURCES:
        ttl = TTL_HOURS.get(src_name, 24)
        cache_dir = CACHE_ROOT / subdir
        for ac in asset_classes:
            for entry in (watchlist.get(ac, []) or []):
                ticker = entry.get("ticker") if isinstance(entry, dict) else entry
                if not ticker:
                    continue
                fname = f"{key_fn(ticker)}.json"
                fp = cache_dir / fname
                payload = _load_json_safe(fp) if fp.is_file() else None
                state, age_h, detail = classify_file_state(payload, ttl, data_field, now=now)
                records.append({
                    "source": src_name, "ticker": ticker, "asset_class": ac,
                    "state": state, "age_h": age_h, "detail": detail,
                })
    # Global sources
    for src_name, rel_path, ttl in GLOBAL_SOURCES:
        fp = CACHE_ROOT / rel_path
        payload = _load_json_safe(fp) if fp.is_file() else None
        state, age_h, detail = classify_file_state(payload, ttl, None, now=now)
        records.append({
            "source": src_name, "ticker": None, "asset_class": "global",
            "state": state, "age_h": age_h, "detail": detail,
        })
    # Sentiment composite — split per-source (mirrors what the dashboard reads)
    sent_dir = CACHE_ROOT / "sentiment"
    if sent_dir.is_dir():
        for ac in ("us", "klse", "crypto"):
            for entry in (watchlist.get(ac, []) or []):
                ticker = entry.get("ticker") if isinstance(entry, dict) else entry
                if not ticker:
                    continue
                fp = sent_dir / f"{ticker.upper()}.json"
                payload = _load_json_safe(fp) if fp.is_file() else None
                if payload is None:
                    records.append({"source": "sentiment_composite", "ticker": ticker,
                                    "asset_class": ac, "state": STATE_MISSING,
                                    "age_h": None, "detail": "not scored yet"})
                    continue
                # Composite-level age
                age_h = _payload_age_h(payload, now)
                per_src = classify_sentiment_sources(payload, now)
                for sname, (sstate, sdetail) in per_src.items():
                    records.append({
                        "source": f"sentiment.{sname}", "ticker": ticker,
                        "asset_class": ac, "state": sstate, "age_h": age_h,
                        "detail": sdetail,
                    })
    return records


def group_by_source(records):
    """Group records by source name; sort within each by state priority."""
    out = {}
    for r in records:
        out.setdefault(r["source"], []).append(r)
    for src in out:
        out[src].sort(key=lambda r: (-state_priority(r["state"]), r.get("ticker") or ""))
    return out
