"""
news_cache.py — Shared budget + per-ticker news cache for Alpha Vantage NEWS_SENTIMENT.

Used by:
    - av_news.py        — writes cache + increments budget on every successful fetch
    - dashboard.py      — reads cache for the US news panel; honors budget when refreshing

Storage:
    .claude/cache/us_news/{TICKER}.json     — per-ticker headlines + per-ticker sentiment
    .claude/cache/us_news_budget.json       — daily budget tracker (resets UTC midnight)

Doctrine: never serve stale data without flagging it. Budget tracker is authoritative;
on-demand callers and dashboard share the same 25-call/day pool.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


# ── Path resolution ───────────────────────────────────────────────────────
# This module lives in .claude/skills/us-news/. Project root is 3 levels up.
_THIS = Path(__file__).resolve()
PROJECT_ROOT = _THIS.parent.parent.parent.parent
CACHE_DIR = PROJECT_ROOT / ".claude" / "cache" / "us_news"
BUDGET_PATH = PROJECT_ROOT / ".claude" / "cache" / "us_news_budget.json"

# Defaults
DAILY_LIMIT = 25
DEFAULT_RESERVE_ONDEMAND = 8  # carved out from dashboard budget for on-demand callers


# ── Budget tracker ────────────────────────────────────────────────────────
def _today_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_budget():
    """Return current budget state. Resets if the UTC day has rolled over."""
    today = _today_utc()
    if not BUDGET_PATH.is_file():
        BUDGET_PATH.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "date_utc": today,
            "calls_used": 0,
            "calls_max": DAILY_LIMIT,
            "reserve_for_ondemand": DEFAULT_RESERVE_ONDEMAND,
        }
        BUDGET_PATH.write_text(json.dumps(state, indent=2))
        return state
    try:
        state = json.loads(BUDGET_PATH.read_text())
    except Exception:
        # Corrupt — reset
        state = {
            "date_utc": today,
            "calls_used": 0,
            "calls_max": DAILY_LIMIT,
            "reserve_for_ondemand": DEFAULT_RESERVE_ONDEMAND,
        }
    if state.get("date_utc") != today:
        # New UTC day → reset counters, keep config
        state = {
            "date_utc": today,
            "calls_used": 0,
            "calls_max": state.get("calls_max", DAILY_LIMIT),
            "reserve_for_ondemand": state.get("reserve_for_ondemand", DEFAULT_RESERVE_ONDEMAND),
        }
        BUDGET_PATH.write_text(json.dumps(state, indent=2))
    return state


def increment_budget(n=1):
    """Atomically increment calls_used. Returns new state."""
    state = load_budget()
    state["calls_used"] = state.get("calls_used", 0) + n
    BUDGET_PATH.write_text(json.dumps(state, indent=2))
    return state


def remaining_total(state=None):
    """Total calls remaining today (ignoring reserve)."""
    state = state or load_budget()
    return max(0, state["calls_max"] - state["calls_used"])


def remaining_for_dashboard(state=None):
    """Calls dashboard can use today (total remaining minus on-demand reserve)."""
    state = state or load_budget()
    return max(0, state["calls_max"] - state["calls_used"] - state["reserve_for_ondemand"])


def time_until_reset_str():
    """Hours/minutes until the next UTC midnight."""
    now = datetime.now(timezone.utc)
    tomorrow = (now.replace(hour=0, minute=0, second=0, microsecond=0)).timestamp()
    # Next midnight UTC = today 00:00 + 24h if we're past it
    if now.hour > 0 or now.minute > 0 or now.second > 0:
        tomorrow += 86400
    secs = int(tomorrow - now.timestamp())
    h, rem = divmod(secs, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h{m:02d}m"


# ── Per-ticker cache ──────────────────────────────────────────────────────
def cache_path(ticker):
    return CACHE_DIR / f"{ticker.upper()}.json"


def write_cache(ticker, payload):
    """Write the AV response (or a curated subset) to cache, with fetched_at."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["_ticker"] = ticker.upper()
    payload["_fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cache_path(ticker).write_text(json.dumps(payload, default=str))


def read_cache(ticker):
    p = cache_path(ticker)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def cache_age_hours(ticker, default=None):
    """Hours since the cache was written, or default if missing/corrupt."""
    d = read_cache(ticker)
    if not d:
        return default
    ts = d.get("_fetched_at")
    if not ts:
        return default
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds() / 3600.0
    except Exception:
        return default


def list_cached_tickers():
    if not CACHE_DIR.is_dir():
        return []
    return sorted([p.stem for p in CACHE_DIR.glob("*.json")])


# ── Priority queue logic (used by dashboard) ──────────────────────────────
# Priority buckets, each with a TTL in hours. Lower priority number = more important.
PRIORITY_TTL_HOURS = {
    "P0_active":    6,    # LIVE — paper / real
    "P1_armed":     12,   # PROSPECTUS — pending trigger
    "P2_ready":     24,   # 🟢 P1_READY badge on dashboard
    "P3_context":   48,   # other watchlist tickers — matches health.TTL_HOURS["us_news"]
    # NOTE: P3 must stay <= health.TTL_HOURS["us_news"] (48h). If health flags a
    # name stale but this gate is looser, --refresh-stale silently skips it (the
    # Data Health panel then promises a refresh the news queue won't deliver).
    # AV budget is protected separately by remaining_for_dashboard()'s reserve.
}


def priority_for_ticker(ticker, journal_statuses, dashboard_status_badges):
    """Compute priority for a ticker based on dashboard context.

    Args:
        ticker:                    str (uppercase)
        journal_statuses:          dict {ticker_upper: status_string} — latest journal status per ticker
        dashboard_status_badges:   dict {ticker_upper: badge_string e.g. "P1_READY"}

    Returns:
        priority key (one of PRIORITY_TTL_HOURS keys) or None if SPY/skip.
    """
    if ticker.upper() == "SPY":
        return None
    js = (journal_statuses.get(ticker.upper()) or "").lower()
    if "live" in js:
        return "P0_active"
    if "prospectus" in js or "pending" in js:
        return "P1_armed"
    badge = (dashboard_status_badges.get(ticker.upper()) or "").upper()
    if "P1_READY" in badge:
        return "P2_ready"
    return "P3_context"


def is_stale(ticker, priority):
    """True if cache is missing or older than the priority's TTL."""
    if priority is None:
        return False
    ttl = PRIORITY_TTL_HOURS.get(priority)
    if ttl is None:
        return False
    age = cache_age_hours(ticker)
    if age is None:
        return True
    return age > ttl


# ── Curating cache for dashboard display ──────────────────────────────────
def top_signal_items(min_relevance=0.5, hours_window=48, max_items=8):
    """Across all cached tickers, return the top N high-signal news items.

    Sorted by (recency × relevance) descending. Used to render the
    'Recent News Flags' panel on the dashboard.
    """
    now = datetime.now(timezone.utc)
    items = []
    for ticker in list_cached_tickers():
        d = read_cache(ticker)
        if not d:
            continue
        for item in d.get("feed", []) or []:
            # Filter to time window
            tp = item.get("time_published", "")
            try:
                dt = datetime.strptime(tp[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
            except Exception:
                continue
            age_h = (now - dt).total_seconds() / 3600
            if age_h < 0 or age_h > hours_window:
                continue
            # Per-ticker sentiment + relevance
            ts = None
            for x in (item.get("ticker_sentiment") or []):
                if (x.get("ticker") or "").upper() == ticker:
                    ts = x; break
            try:
                rel = float((ts or {}).get("relevance_score", 0))
            except (TypeError, ValueError):
                rel = 0.0
            try:
                sent = float((ts or {}).get("ticker_sentiment_score", 0))
            except (TypeError, ValueError):
                sent = 0.0
            if rel < min_relevance:
                continue
            # Score: relevance × recency-decay (linear over the window)
            recency = max(0, 1 - (age_h / hours_window))
            score = rel * (0.5 + 0.5 * recency)
            items.append({
                "ticker": ticker,
                "title": (item.get("title") or "").strip(),
                "source": item.get("source") or "?",
                "time": dt,
                "age_h": age_h,
                "relevance": rel,
                "sentiment_score": sent,
                "sentiment_label": (ts or {}).get("ticker_sentiment_label") or "?",
                "url": item.get("url") or "",
                "score": score,
            })
    items.sort(key=lambda x: x["score"], reverse=True)
    return items[:max_items]
