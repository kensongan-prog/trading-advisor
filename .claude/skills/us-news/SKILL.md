---
name: us-news
description: Fetch recent US-equity news headlines with per-ticker sentiment scores from Alpha Vantage's NEWS_SENTIMENT endpoint. Returns dated, sourced items with relevance scores, sentiment labels (Bearish / Somewhat-Bearish / Neutral / Somewhat-Bullish / Bullish), topic tags, and an aggregate sentiment readout. Use for any US-equity recommendation that needs a sentiment/catalyst read or an event-risk check on news flow. REQUIRED before any US-equity recommendation claims a sentiment edge, and recommended before any directional trade as part of the confluence gate.
---

# US News & Sentiment Skill (Alpha Vantage)

## When to use

Trigger this skill on any US-listed ticker when the analysis needs:

- **Sentiment confluence** with technicals (per CLAUDE.md Section 4: a high-conviction call requires technicals + at least one of {sentiment, fundamentals, flow}).
- **Catalyst detection**: M&A, earnings reactions, guidance changes, regulatory actions, analyst rating shifts.
- **Pre-trade event-window check** for non-earnings catalysts (FDA decisions, conference talks, product launches).
- **Sanity check on a price move**: is the move news-driven or noise?

Do NOT use this skill for:
- KLSE tickers — use `klse-news` instead.
- Crypto — coverage on AV is thin and unreliable; use a crypto-native source when wired.
- Earnings-release scheduling on US names — AV's news is reactive; for the actual earnings calendar use FMP or earnings-specific endpoints (not yet wired).

## Why this exists

Massive MCP gives prices and indicators, not news/sentiment. Per CLAUDE.md Section 4, technicals alone are not enough — confluence requires sentiment OR fundamentals OR flow. Without a news source, every US recommendation would be flying half-blind on confluence. Alpha Vantage's NEWS_SENTIMENT is the fastest, cheapest way to close that gap; it ships per-article ticker-level sentiment scores that AV pre-computes, plus topic tags, plus relevance scores per ticker.

## Setup — one-time

1. Get a **free** Alpha Vantage API key (≈20 seconds, no credit card): https://www.alphavantage.co/support/#api-key
2. Set the env var so the skill can read it:
   ```bash
   # In your shell profile (~/.zshrc, ~/.bashrc, ~/.bash_profile):
   export ALPHAVANTAGE_API_KEY="your-key-here"
   ```
   Then `source ~/.zshrc` (or restart the terminal / desktop app).
3. Verify:
   ```bash
   python3 /Users/aiagent/Documents/Claude/Projects/Trading\ Advisor/.claude/skills/us-news/av_news.py --ticker AAPL --limit 3
   ```

**Free-tier limits to be aware of:** 25 NEWS_SENTIMENT calls/day. That's enough for triage across a small watchlist, NOT enough to loop on. If you upgrade to a premium tier (75/min, 1200/day, etc.), the script doesn't need changing — same env var.

## How to use

The skill ships with `av_news.py`. Invoke via Bash.

### Standard invocations

**Latest 10 headlines + aggregate sentiment:**
```
python3 .claude/skills/us-news/av_news.py --ticker AAPL --limit 10
```

**Recent window (last 48 hours), useful for reaction-to-event checks:**
```
python3 .claude/skills/us-news/av_news.py --ticker NVDA --hours 48 --limit 20
```

**High-relevance only (drop weakly-tagged items):**
```
python3 .claude/skills/us-news/av_news.py --ticker MSFT --limit 15 --min-relevance 0.3
```

**Topic-filtered (earnings reactions only):**
```
python3 .claude/skills/us-news/av_news.py --ticker TSLA --topics earnings --hours 72
```

Available `--topics` filters (AV docs): `earnings`, `ipo`, `mergers_and_acquisitions`, `financial_markets`, `economy_fiscal`, `economy_monetary`, `economy_macro`, `energy_transportation`, `finance`, `life_sciences`, `manufacturing`, `real_estate`, `retail_wholesale`, `technology`. Comma-separate for multiple.

### Reading the output

Each headline shows: timestamp, source, title, AV's per-ticker sentiment label + numeric score, relevance score (0–1), topics, and a short snippet. The aggregate at the bottom shows the count of articles with per-ticker sentiment, the average sentiment score across them, AV's label for that average, and the distribution of labels.

**Quote numbers and labels directly from this output** in any recommendation — do not paraphrase, round, or fill from memory.

### AV's sentiment score interpretation (from AV docs)

| Score range | Label |
|-------------|-------|
| score ≤ −0.35 | Bearish |
| −0.35 < score ≤ −0.15 | Somewhat-Bearish |
| −0.15 < score < 0.15 | Neutral |
| 0.15 ≤ score < 0.35 | Somewhat-Bullish |
| score ≥ 0.35 | Bullish |

The **relevance score** is per-article-per-ticker: how relevant *this* article is to *this* ticker. An article mentioning AAPL once in a long sector roundup will score low; a dedicated AAPL story scores high. **`--min-relevance 0.3`** is a sensible default for serious confluence work.

## Hard rules

1. **If the script prints `FETCH FAILED` or `NO HEADLINES`, that is a real signal — propagate it.**
   - `FETCH FAILED` → recommendation is NO-TRADE-or-low-confidence-only with reason "AV unavailable." Do not LLM-memory the news.
   - `NO HEADLINES` for a major name across a 7-day window → suspicious; lower confidence and verify with a second source if available.
   - Rate limit hit (free tier = 25/day) → DON'T retry until next day; lower confidence on remaining names this session.

2. **Distinguish per-ticker sentiment from overall-article sentiment.** AV publishes both. For confluence, use the **per-ticker** number — it's what AV thinks the article means *for that specific ticker*. The overall sentiment can mislead when an article covers multiple names with opposite implications.

3. **Aggregate ≠ market view.** The aggregate is "sentiment of news AV indexed about this name." It is a proxy for press tone, not for positioning. Don't treat a strongly bullish aggregate as "the market is long" — it just means recent headlines were positive.

4. **Free-tier budget discipline.** 25 calls/day. Don't loop. Don't refetch within minutes. If running across a watchlist, prioritize names where the technicals are signaling and a sentiment read would actually change the decision.

5. **Recency matters more than count.** Three fresh headlines from the last 6 hours beat 20 from last week. Use `--hours 24` or `--hours 48` for active-trade decisions; longer windows only for context.

## Combined-skill recipe (US equity, full pre-trade workflow)

For any US-equity recommendation, run in order:

1. Massive `/v2/aggs/ticker/{TICKER}/prev` → previous-day OHLCV (snapshot tier is plan-locked).
2. Massive `/v1/indicators/rsi/{TICKER}` → RSI(14). Repeat for SMA20/50/200 if playbook requires (Massive has individual indicator endpoints).
3. **`us-news`** (`--hours 48 --limit 15 --min-relevance 0.3`) → recent sentiment + catalyst check.
4. Fundamentals: NOT YET WIRED — flag any thesis that depends on P/E, earnings growth, or DCF as "fundamentals unverified, lowered confidence."
5. Confluence verdict per CLAUDE.md §4.
6. Gate check per `rules/risk-doctrine.md` §7.
7. Output in CLAUDE.md format, citing the AV `Fetched (UTC)` timestamp in the data snapshot.

## What this skill does NOT cover

- **Earnings calendar / scheduled events.** AV NEWS is reactive (post-event coverage), not forward-looking. For the next earnings date, use a different source.
- **Social sentiment** (X/Twitter, Reddit, StockTwits). Not AV.
- **Options flow.** Different endpoint entirely; not in scope here.
- **Historical news archive.** AV typically returns recent items; for deep history (months back) you'll hit limits quickly.
- **Per-article translation.** AV news is English-only.
