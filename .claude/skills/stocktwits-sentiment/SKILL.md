---
name: stocktwits-sentiment
description: Manually refresh retail sentiment for watchlist tickers from StockTwits — per-ticker bull%/bear% from user-tagged messages, message volume, watcher count. Free public API (no auth). Sibling of `reddit-sentiment`; together they form the raw retail-sentiment layer that LLM scoring (in `sentiment-cache`) consumes. Manual by design — no automatic refresh, no cron. Covers US equities + crypto (with `.X` suffix); KLSE returns 404 gracefully and stores as no-coverage.
---

# StockTwits Sentiment Skill

## When to use

Trigger this skill when the user says:
- "Refresh StockTwits sentiment"
- "What's StockTwits saying about NVDA?"
- "Pull retail sentiment from StockTwits"
- "Show me the StockTwits cache"

Do NOT trigger for:
- Reddit (use `reddit-sentiment` — different forum, different signal)
- Professional news (use `us-news`, `klse-news`)
- KLSE tickers as a primary source — StockTwits has near-zero KLSE coverage; the skill will store a no-coverage marker but you won't get signal

## Why this exists

StockTwits is the practical retail-sentiment alternative to FinTwit. The X API ($100/mo basic, $5k+ for real data) was deprioritized during the build; StockTwits provides the same signal class (bull% / bear% / message velocity from retail traders) via a free, unauthenticated public API.

Many StockTwits messages carry **user-tagged sentiment** (Bullish / Bearish badge the poster sets when composing). Roughly 40-60% of messages are tagged on liquid US names. Untagged messages will be LLM-scored downstream by the `sentiment-cache` layer (next step).

## Source

`https://api.stocktwits.com/api/2/streams/symbol/{TICKER}.json` — returns last 30 messages. No auth required. Public rate limit applies (~200 requests/hour per IP — far above our ~25-name refresh).

**Ticker formatting:**
- **US equity:** bare symbol (e.g. `NVDA`, `AUPH`)
- **Crypto:** symbol + `.X` suffix (e.g. `BTC.X`, `ETH.X`, `HYPE.X`)
- **KLSE:** no coverage. The skill stores a `no_coverage: true` marker so the dashboard can render `—` cleanly without spamming errors

## Usage

```bash
# Refresh all watchlist tickers (US + crypto; KLSE marked no-coverage)
python3 .claude/skills/stocktwits-sentiment/stocktwits_sentiment.py

# Refresh specific tickers
python3 .claude/skills/stocktwits-sentiment/stocktwits_sentiment.py NVDA BTC

# Show cached values without re-fetching
python3 .claude/skills/stocktwits-sentiment/stocktwits_sentiment.py --show

# Show one ticker in detail (recent messages)
python3 .claude/skills/stocktwits-sentiment/stocktwits_sentiment.py --show NVDA

# Clear the cache
python3 .claude/skills/stocktwits-sentiment/stocktwits_sentiment.py --clear
```

## Output

Per-ticker JSON at `.claude/cache/stocktwits_sentiment/{ticker}.json`:

```json
{
  "ticker": "NVDA",
  "asset_class": "us_equity",
  "stocktwits_symbol": "NVDA",
  "fetched_at": "2026-06-08T12:34:56Z",
  "message_count": 30,
  "watchers": 649247,
  "tagged_counts": {"Bullish": 13, "Bearish": 4, "untagged": 13},
  "tagged_bull_pct": 0.76,
  "messages": [
    {
      "id": 12345,
      "body": "NVDA breaking out, $150 next",
      "created_at": "2026-06-08T12:00:00Z",
      "user": "trader42",
      "tagged_sentiment": "Bullish",
      "likes": 5,
      "reshares": 1
    }
  ],
  "no_coverage": false,
  "error": null
}
```

`tagged_bull_pct = Bullish / (Bullish + Bearish)` — null if no tagged messages. Messages are kept verbatim (body retained) so the LLM scoring layer can re-score and dig deeper than the user-tagged labels.

KLSE entries store `no_coverage: true` with empty messages — distinguishes "we tried, no data" from "we never tried".

## What this skill is NOT

- Not a sentiment classifier — LLM scoring layers on top (see `sentiment-cache` skill)
- Not a real-time stream — manual refresh only
- Not a substitute for `us-news` — that's professional + Alpha Vantage sentiment; this is retail self-tagged
- Not authoritative on its own — the bull% can be gamed; combine with Reddit + LLM-scored body text for confluence
