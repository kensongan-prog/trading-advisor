---
name: sentiment-inline
description: Re-score retail sentiment using the current Claude Code session as the classifier instead of OpenRouter's free models — no metered API, no spend, and a stronger model than the free Gemma/GPT-OSS pair. A manual, session-driven alternative to the sentiment-cache LLM leg (the slow part of a build). Use when the operator wants fresh sentiment NOW without waiting on the free-tier 429 backoffs and without paying for a model. Re-scores the EXISTING raw social caches (stocktwits/reddit/hn) in place; it does not fetch new social data and does not run during automated builds.
---

# Sentiment Inline Skill

## When to use
- The operator wants the stale watchlist sentiment refreshed **now**, and the normal
  sentiment-cache pass (OpenRouter free tier) is too slow or the operator doesn't want spend.
- A session is active (this skill needs a session model to do the classification — it is **not**
  headless). Automated builds / the watcher still use the normal `sentiment-cache` path.

## What it does (and doesn't)
- **Does:** re-classifies the already-fetched raw social messages in
  `.claude/cache/{stocktwits,reddit,hn}_sentiment/*.json` using *you* (the session model), then
  writes the canonical `.claude/cache/sentiment/<TICKER>.json` the dashboard reads — reusing
  `sentiment_cache.py`'s real aggregation, engagement weighting, coverage haircut, composite math,
  rationale, and cache format. Only the LLM call is swapped for you.
- **Doesn't:** fetch fresh social data (run the stocktwits/reddit/hn fetchers first if the raw
  caches themselves are stale), and doesn't run unattended.

## Workflow (three steps — you are step 2)

1. **Dump** the body batches the real scorer would send to the LLM:
   ```
   python3 .claude/skills/sentiment-inline/score_inline.py dump --stale
   # or: dump TICK1 TICK2   |   dump --all   |   --ttl-hours N
   ```
   Writes `/tmp/ta_sentiment_inbox.json` with a `batches` array; each batch has `ticker`,
   `source` (stocktwits/reddit/hackernews), `bodies` (the messages), and `scores: null`.

2. **Score** — read the inbox and, for every batch, fill its `scores` array with **one object per
   body, in the same order**:
   ```json
   {"relevance": "primary|mention|none", "sentiment": "bullish|bearish|neutral", "conviction": 0.0-1.0}
   ```
   Rubric (matches `sentiment_cache.SYSTEM_PROMPT`):
   - **relevance** — `primary`: the ticker/company is the main subject. `mention`: it appears but
     isn't the focus (peer mention, sector roundup). `none`: the ticker doesn't actually appear
     (a look-alike word for a different company/topic, e.g. Solana vs "Solara").
   - **sentiment** — bullish / bearish / neutral on the named ticker.
   - **conviction** — how *clear* the sentiment is (0–1), **not** how strong the directional view.
     Sarcasm, irony, and hedge-language lower conviction.
   Write the filled JSON back to the same path (edit `scores` in place; leave `bodies`/`key`
   untouched — `key` is how ingest matches your scores to the batch).

3. **Ingest** — replay the real scorer with your scores and write the caches:
   ```
   python3 .claude/skills/sentiment-inline/score_inline.py ingest /tmp/ta_sentiment_inbox.json
   ```
   Prints a bull/conviction/flag summary. Each written cache records
   `"model": "inline (claude session, hand-scored)"` and a fresh `scored_at` (so the dashboard's
   24h sentiment staleness resets). Then rebuild the dashboard to surface it:
   `python3 .claude/skills/dashboard/dashboard.py`.

## Notes
- `scored_at` resets on ingest, so the dashboard's §4 contrarian factor and the Risk Simulator
  pick up the new read immediately.
- Tickers with no raw social data are skipped and reported — nothing is overwritten with an empty
  read.
- The composite/coverage/flag thresholds are unchanged: this skill only supplies classifications;
  `compute_composite` (v2.6.0 coverage haircut) still decides the FADE/BUY flag, so a thin sample
  still can't fire a high-conviction flag.
