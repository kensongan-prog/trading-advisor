---
name: klse-sentiment
description: Manually refresh KLSE (Bursa Malaysia) retail sentiment from klsescreener's per-stock community comment threads into a local JSON cache the sentiment-cache LLM scorer consumes. The Bursa-native retail leg — fills the gap StockTwits (404s on KLSE) and Reddit (thin r/Bursa_Malaysia) leave. Real, multilingual (English/Chinese/Malay) chatter, no login wall. Manual by design — no cron. REQUIRED before any §4 retail-sentiment read on a KLSE name.
---

# klse-sentiment — Bursa community-comment sentiment

The KLSE-native raw-fetch leg of the §4 retail-sentiment stack — sibling of
`stocktwits-sentiment` / `reddit-sentiment` / `hn-sentiment`. klsescreener hosts a
per-stock community thread with genuine retail chatter; this scrapes it into a
raw cache that the `sentiment-cache` LLM scorer turns into the canonical
`sentiment.json` composite.

**Why it exists:** for Bursa names the other three legs are usually empty —
StockTwits 404s on KLSE codes, Reddit's `r/Bursa_Malaysia` is thin. Before this,
KLSE tickers scored `UNKNOWN` (no source data). klsescreener comments fill that
slot: no login wall, and it's a site the project already scrapes for quote /
news / announcements.

## Endpoint (discovered 2026-07-01 — see notes/learned.md)

Full thread: `https://www.klsescreener.com/v2/comments/all/stock/{CODE}` (GET,
server-rendered HTML, no auth). The in-page AJAX pager (`/v2/comments/comment/...`)
was **deprecated** (commented out, 404s); the "all" page is the live surface and
caps at ~26 most-recent comments — fine, since we want recency.

## Usage

```bash
python3 .claude/skills/klse-sentiment/klse_sentiment.py            # all KLSE in watchlist, 180d window
python3 .claude/skills/klse-sentiment/klse_sentiment.py 9431 5099  # specific Bursa codes
python3 .claude/skills/klse-sentiment/klse_sentiment.py --days 90  # tighter window
python3 .claude/skills/klse-sentiment/klse_sentiment.py --show     # print cached values, no fetch
python3 .claude/skills/klse-sentiment/klse_sentiment.py --clear    # wipe cache
```

Then score it into the composite: run `sentiment-cache` (or a dashboard
`--refresh-sentiment` + rebuild) — `sentiment_cache.process_klse` reads this
cache's `messages[].body`, LLM-scores them (Chinese handled via the news-glyph
`COMPANY_LABELS` map + the relevance gate), and blends at weight 1.0 into the
`compute_composite` read.

## Cache

`.claude/cache/klse_sentiment/{CODE}.json` — keyed by 4-digit Bursa code:

```json
{
  "ticker": "9431", "asset_class": "klse", "window_days": 180,
  "messages": [{"date": "2026-06-27", "body": "Wait for the breakout above 55 cents…"}],
  "message_count": 21, "total_on_page": 21, "no_coverage": false, "error": null,
  "_fetched_at": "…"
}
```

Registered in `health.py` (`TTL_HOURS` 24h, `REFRESH_VIA` cli, `PER_TICKER_SOURCES`).

## Landmines

- **Coverage is uneven.** Actively-discussed names (blue-chips, hot small-caps)
  carry 12–25 recent comments; quiet names go dark for months and store as
  `no_coverage`. The composite coverage-haircut means a thin sample can't fire a
  high-conviction contrarian flag — thin data degrades safely.
- **Multilingual + noisy.** Comments mix English/Chinese/Malay and include
  off-topic rants; the classifier's `relevance: primary|mention|none` gate filters
  those, same as the other legs.
- **Manual by design** — no cron, no automatic refresh. A human clicking a
  refresh button IS manual initiation.
- Uses urllib + regex (no WebFetch) so it runs from any Python context. Be polite:
  default 1.2s inter-request delay.

## See also

- `stocktwits-sentiment` / `reddit-sentiment` / `hn-sentiment` — sibling raw legs
- `sentiment-cache` — the LLM scorer that consumes this (`process_klse`)
- `klse-news` / `klse-announcements` — other klsescreener feeds (news is scraped by
  `us-news/news_glyph.refresh_klse`, NOT a separate fetcher)
