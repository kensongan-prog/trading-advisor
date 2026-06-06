#!/usr/bin/env python3
"""
av_news.py — Alpha Vantage NEWS_SENTIMENT fetcher for US tickers.

Single-purpose CLI invoked by the `us-news` skill. Reads the API key from the
ALPHAVANTAGE_API_KEY env var (or --api-key flag). Never falls back to memory:
if the API errors, returns empty, or rate-limits, the script says so explicitly.

Usage:
    export ALPHAVANTAGE_API_KEY=YOUR_KEY
    python3 av_news.py --ticker AAPL --limit 10
    python3 av_news.py --ticker NVDA --topics earnings,technology --hours 48
    python3 av_news.py --ticker MSFT --limit 20 --min-relevance 0.3

Output is plain text formatted for an LLM to read and quote into a recommendation.
All values come from the Alpha Vantage response — nothing is synthesized.
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


AV_BASE = "https://www.alphavantage.co/query"


def load_dotenv_if_present():
    """Load KEY=VALUE pairs from a .env file sitting next to this script.

    Minimal, dependency-free. Only sets variables that aren't already in os.environ
    (env wins over .env, as is conventional). Silently does nothing if no file.
    """
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    try:
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception as e:
        # Don't fail the run if .env is malformed; just print to stderr.
        print(f"warning: failed to parse {env_path}: {e}", file=sys.stderr)


def parse_av_time(t):
    """Alpha Vantage uses 'YYYYMMDDTHHMMSS' (UTC)."""
    if not t or len(t) < 15:
        return t
    try:
        dt = datetime.strptime(t, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return t


def sentiment_label(score):
    """AV's published thresholds for the overall sentiment score."""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "unknown"
    if s <= -0.35:
        return "Bearish"
    if s <= -0.15:
        return "Somewhat-Bearish"
    if s < 0.15:
        return "Neutral"
    if s < 0.35:
        return "Somewhat-Bullish"
    return "Bullish"


def fetch(api_key, ticker, topics, hours, limit):
    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": ticker,
        "apikey": api_key,
        "sort": "LATEST",
        "limit": str(min(max(limit, 1), 1000)),
    }
    if topics:
        params["topics"] = topics
    if hours:
        # AV uses YYYYMMDDTHHMM for time_from
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        params["time_from"] = cutoff.strftime("%Y%m%dT%H%M")

    url = AV_BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "trading-advisor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as e:
        return None, f"HTTP error: {e}"

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"JSON decode error: {e}; raw[:200]={raw[:200]!r}"

    # AV returns errors and rate-limit messages inside 200 responses.
    if "Error Message" in data:
        return None, f"Alpha Vantage error: {data['Error Message']}"
    if "Information" in data and "feed" not in data:
        return None, f"Alpha Vantage info/limit: {data['Information']}"
    if "Note" in data and "feed" not in data:
        return None, f"Alpha Vantage rate limit: {data['Note']}"

    return data, None


def per_ticker_sentiment(item, ticker):
    """Pull the per-ticker sentiment block for the requested ticker, if present."""
    ticker_u = ticker.upper()
    for ts in item.get("ticker_sentiment", []) or []:
        if ts.get("ticker", "").upper() == ticker_u:
            return ts
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ticker", help="US ticker symbol, e.g. AAPL")
    p.add_argument("--limit", type=int, default=10, help="Max headlines to display")
    p.add_argument("--hours", type=int, default=None, help="Look-back window in hours (e.g. 24, 72, 168)")
    p.add_argument(
        "--topics",
        default=None,
        help="Comma list of AV topic filters: earnings, ipo, mergers_and_acquisitions, "
             "financial_markets, economy_fiscal, economy_monetary, economy_macro, "
             "energy_transportation, finance, life_sciences, manufacturing, real_estate, "
             "retail_wholesale, technology",
    )
    p.add_argument("--min-relevance", type=float, default=0.0, help="Drop articles whose per-ticker relevance is below this (0.0–1.0)")
    p.add_argument("--api-key", default=None, help="Override env var (debug only — prefer ALPHAVANTAGE_API_KEY)")
    p.add_argument("--budget", action="store_true", help="Show AV daily budget status and exit (no API call)")
    p.add_argument("--cache-list", action="store_true", help="List cached tickers with age + headline count, no API call")
    args = p.parse_args()

    # Inline import so the module can run standalone without the cache file
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import news_cache as nc

    # Read-only modes: --budget and --cache-list bypass API
    if args.budget:
        state = nc.load_budget()
        print(f"AV BUDGET — {state['date_utc']} UTC")
        print(f"  Calls used:           {state['calls_used']} / {state['calls_max']}")
        print(f"  Reserve for on-demand: {state['reserve_for_ondemand']}")
        print(f"  Remaining (total):    {nc.remaining_total(state)}")
        print(f"  Remaining (dashboard): {nc.remaining_for_dashboard(state)}")
        print(f"  Reset in:             {nc.time_until_reset_str()}")
        return 0

    if args.cache_list:
        tickers = nc.list_cached_tickers()
        if not tickers:
            print("No cached tickers yet.")
            return 0
        print(f"{'ticker':8}  {'age':>8}  {'items':>6}  fetched (UTC)")
        for t in tickers:
            d = nc.read_cache(t) or {}
            age = nc.cache_age_hours(t)
            age_s = f"{age:.1f}h" if age is not None and age < 48 else (f"{age/24:.1f}d" if age else "—")
            n_items = len(d.get("feed", []) or [])
            ts = d.get("_fetched_at", "—")
            print(f"{t:8}  {age_s:>8}  {n_items:>6}  {ts}")
        return 0

    if not args.ticker:
        print("ERROR: --ticker is required (unless using --budget or --cache-list)", file=sys.stderr)
        return 2

    load_dotenv_if_present()
    api_key = args.api_key or os.environ.get("ALPHAVANTAGE_API_KEY")
    if not api_key:
        print("ERROR: no API key. Set ALPHAVANTAGE_API_KEY in .claude/skills/us-news/.env, "
              "in the shell env, or pass --api-key.", file=sys.stderr)
        print("Get a free key at https://www.alphavantage.co/support/#api-key", file=sys.stderr)
        return 2

    # Pre-check: warn if budget is exhausted but still attempt (the user explicitly invoked)
    state = nc.load_budget()
    if nc.remaining_total(state) <= 0:
        print(f"⚠ AV BUDGET EXHAUSTED: {state['calls_used']}/{state['calls_max']} used today. "
              f"Reset in {nc.time_until_reset_str()}.", file=sys.stderr)
        print(f"  Cache for {args.ticker.upper()} (age):", nc.cache_age_hours(args.ticker), "h", file=sys.stderr)
        print(f"  Proceeding anyway — AV will likely return rate-limit error.", file=sys.stderr)
    elif nc.remaining_total(state) <= state["reserve_for_ondemand"]:
        print(f"⚠ AV budget low: {state['calls_used']}/{state['calls_max']} used "
              f"(reserve for on-demand = {state['reserve_for_ondemand']}).", file=sys.stderr)

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data, err = fetch(api_key, args.ticker, args.topics, args.hours, args.limit)
    if err:
        print(f"FETCH FAILED for {args.ticker}: {err}")
        print("DO NOT use LLM memory or web search as a substitute. Tell the user the source failed.")
        # Persist the error to cache so dashboard knows last attempt failed
        nc.write_cache(args.ticker, {"error": err, "feed": []})
        return 1

    # SUCCESS: write to cache + increment budget
    nc.write_cache(args.ticker, data)
    new_state = nc.increment_budget(1)
    print(f"  [budget: {new_state['calls_used']}/{new_state['calls_max']} used, {nc.remaining_total(new_state)} remaining]",
          file=sys.stderr)

    feed = data.get("feed", []) or []
    overall_relevance = data.get("relevance_score_definition", "")
    overall_sent_def = data.get("sentiment_score_definition", "")

    print(f"US NEWS — {args.ticker.upper()}")
    print(f"Source:        Alpha Vantage NEWS_SENTIMENT")
    print(f"Fetched (UTC): {fetched_at}")
    print(f"Window:        last {args.hours}h" if args.hours else "Window:        latest available")
    if args.topics:
        print(f"Topic filter:  {args.topics}")
    print(f"Items returned: {len(feed)}")
    print()

    if not feed:
        print("NO HEADLINES returned. Possible causes:")
        print("  - Ticker has no Alpha Vantage news coverage in the window.")
        print("  - Topic filter too narrow.")
        print("  - Rate limit hit silently (check AV usage).")
        print("Per project doctrine: this means NO sentiment confluence available for this name in this window.")
        return 0

    # Aggregate per-ticker sentiment across the feed.
    scores = []
    labels = []
    dropped_low_rel = 0
    rows = []
    for item in feed:
        ts = per_ticker_sentiment(item, args.ticker)
        try:
            rel = float(ts.get("relevance_score", 0.0)) if ts else 0.0
        except (TypeError, ValueError):
            rel = 0.0
        if rel < args.min_relevance:
            dropped_low_rel += 1
            continue
        try:
            sent = float(ts.get("ticker_sentiment_score", 0.0)) if ts else 0.0
        except (TypeError, ValueError):
            sent = 0.0
        if ts:
            scores.append(sent)
            labels.append(ts.get("ticker_sentiment_label", sentiment_label(sent)))
        rows.append({
            "time": parse_av_time(item.get("time_published", "")),
            "source": item.get("source", "?"),
            "title": item.get("title", "").strip(),
            "url": item.get("url", ""),
            "summary": (item.get("summary", "") or "").strip(),
            "overall_sent": item.get("overall_sentiment_label", sentiment_label(item.get("overall_sentiment_score", 0))),
            "overall_score": item.get("overall_sentiment_score", ""),
            "ticker_sent": ts.get("ticker_sentiment_label", "?") if ts else "—",
            "ticker_score": ts.get("ticker_sentiment_score", "") if ts else "",
            "relevance": ts.get("relevance_score", "") if ts else "",
            "topics": ", ".join(t.get("topic", "") for t in item.get("topics", [])[:3]),
        })

    if rows:
        print("HEADLINES (most recent first)")
        for i, r in enumerate(rows[: args.limit], 1):
            print(f"{i}. {r['time']}  [{r['source']}]")
            print(f"   {r['title']}")
            print(f"   ticker-sentiment: {r['ticker_sent']} ({r['ticker_score']})  "
                  f"relevance: {r['relevance']}  topics: {r['topics']}")
            if r["summary"]:
                snippet = r["summary"][:240] + ("…" if len(r["summary"]) > 240 else "")
                print(f"   {snippet}")
            print()

    if dropped_low_rel:
        print(f"(Dropped {dropped_low_rel} items below --min-relevance {args.min_relevance})")
        print()

    # Aggregate.
    if scores:
        avg = sum(scores) / len(scores)
        print("AGGREGATE")
        print(f"  Articles with per-ticker sentiment: {len(scores)}")
        print(f"  Avg ticker-sentiment score:         {avg:+.4f}  ({sentiment_label(avg)})")
        bucket = {"Bearish": 0, "Somewhat-Bearish": 0, "Neutral": 0, "Somewhat-Bullish": 0, "Bullish": 0}
        for lab in labels:
            bucket[lab] = bucket.get(lab, 0) + 1
        print(f"  Label distribution: {bucket}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
