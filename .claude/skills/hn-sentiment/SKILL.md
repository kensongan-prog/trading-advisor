---
name: hn-sentiment
description: Manually refresh Hacker News sentiment for watchlist tickers via the free Algolia HN search API. Per-ticker stories + top comments, engagement-scored, persisted to a local JSON cache for the sentiment-cache LLM scorer to consume. HN comments are typically more substantive than retail forum chatter, so this is the "smart-money retail" leg of the §4 sentiment stack — especially valuable for tech tickers (RDDT, MRVL, RKLB, KTOS, NVDA-class names) and crypto majors. Raw-fetch leg; pairs with reddit-sentiment + stocktwits-sentiment under the sentiment-cache aggregator.
---

# Hacker News Sentiment Skill

## When to use

Trigger this skill on any US-listed (or crypto) ticker with potential HN coverage:

- **Tech-stack reads:** AI / semis / cloud / dev-tooling tickers (NVDA, MRVL, MSFT, RDDT, GOOG, etc.) — HN is where substantive technical opinion congregates *before* it migrates to retail forums.
- **Crypto majors:** BTC / ETH / SOL discussion on HN tends to be developer + infrastructure focused (different signal than r/CryptoCurrency).
- **Catalyst sanity check:** when a name's been in the news (acquisition, FDA decision, product launch), HN comment threads often surface dissenting expert views that don't appear on retail forums.

Do NOT use this skill for:
- KLSE tickers — HN has approximately zero Malaysian-equity coverage.
- Consumer-staples / industrial value names — HN signal is sparse to nonexistent.

## Why this exists

AGENTS.md §4 requires confluence: technicals + at least one of {sentiment, fundamentals, flow}. The retail-sentiment composite (`sentiment-cache` reading `reddit-sentiment` + `stocktwits-sentiment`) covers cheap-talk forums. HN sits in a different niche — fewer participants, much higher technical-substance bar, engagement that's read+thought-about rather than reflexive. Adding it as a third leg to the composite raises the floor on sentiment quality without changing the dashboard surface.

## Source

**Algolia HN API** — free, no auth, no rate limit at retail-research scale:

| Endpoint | Purpose |
|---|---|
| `https://hn.algolia.com/api/v1/search_by_date?query={Q}&tags=story&numericFilters=created_at_i>{30d_ago}` | Story discovery |
| `https://hn.algolia.com/api/v1/items/{story_id}` | Full comment tree for a story |

Engagement metric: `points + (num_comments × 2)` — mirrors HN's own ranking semantics where comment depth weighs heavier than a passive upvote.

## Setup

No API key. Free tier. Works out of the box.

## How to use

### Standard invocations

```bash
# All watchlist tickers (US + crypto; KLSE skipped automatically):
python3 .claude/skills/hn-sentiment/hn_sentiment.py

# Specific tickers:
python3 .claude/skills/hn-sentiment/hn_sentiment.py NVDA RDDT BTC

# Inspect a cached entry:
python3 .claude/skills/hn-sentiment/hn_sentiment.py --show RDDT

# Force-refresh (bypass cache age check):
python3 .claude/skills/hn-sentiment/hn_sentiment.py --force NVDA
```

### Per-ticker query strategy

Tickers map to company names via a curated lookup (e.g. `NVDA → Nvidia`, `RDDT → Reddit`, `BTC → Bitcoin`). HN search runs against the company name; the ticker symbol is used as a fallback for names without a curated mapping. Stories are filtered to last 30 days, minimum 5 comments (signal-to-noise floor).

For each ticker we fetch up to 10 stories, sorted by engagement, then for each of the top 5 stories we pull the comment tree and keep the top 5 top-level comments by points. Cap: ~25 comment bodies per ticker (matches `sentiment-cache`'s `MAX_MESSAGES_PER_TICKER` budget).

### Output

`.claude/cache/hn_sentiment/{TICKER}.json` — schema:

```json
{
  "ticker": "RDDT",
  "company_query": "Reddit",
  "fetched_at": "2026-06-09T15:00:00+00:00",
  "story_count": 5,
  "stories": [
    {
      "id": "12345",
      "title": "Reddit Q2 earnings: ad revenue up 40%",
      "url": "https://...",
      "points": 234,
      "num_comments": 89,
      "engagement": 412,
      "created_at": "2026-06-01T...",
      "top_comments": [
        {"body": "...", "points": 45, "author": "...", "created_at": "..."}
      ]
    }
  ]
}
```

## Hard rules

1. **HN coverage is sparse-by-design for non-tech names.** A `story_count: 0` result for an industrial / staples / KLSE ticker is *the truth*, not a fetch failure. Don't treat absence as bug.
2. **Engagement-weighted, not vote-counting.** A single 800-point thoughtful comment on a Reddit IPO thread carries more signal than 50 throwaway "to the moon" comments. The downstream `sentiment-cache` scorer uses `log1p(engagement)` weighting (mirrors the engagement-weighting we apply to Reddit + StockTwits).
3. **30-day window is the contract.** Older HN coverage isn't surfaced — by the time something's older than 30 days the market has long since priced it.
4. **Don't paraphrase HN content from LLM memory.** If the fetch fails or returns no stories, propagate that. No fabricated "smart money on HN says…" claims.

## Hand-off to sentiment-cache

After this skill writes its JSON cache, the `sentiment-cache` skill's per-ticker scorer reads it as a third source alongside Reddit + StockTwits and folds it into the composite bull/bear/neutral score that the dashboard renders in the Retail / News column.

Typical pipeline order:
```
reddit-sentiment      # raw forum posts
stocktwits-sentiment  # raw ST messages
hn-sentiment          # raw HN stories + comments  ← this skill
sentiment-cache       # LLM-score all three, compose composite
dashboard             # render composite as Retail / News column
```

The dashboard auto-fills missing tickers across all three raw sources, so adding a new watchlist entry will automatically pull HN coverage on the next build (subject to: name resolution available; ticker has any HN coverage).
