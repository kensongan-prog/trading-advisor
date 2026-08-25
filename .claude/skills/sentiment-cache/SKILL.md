---
name: sentiment-cache
description: LLM-score raw retail-sentiment data (from reddit-sentiment and stocktwits-sentiment caches) into a composite per-ticker sentiment read with contrarian flag. Uses the authenticated OpenAI/Codex route with strict structured output and no cross-provider fallback. Output is the canonical sentiment.json that the dashboard reads. Final leg of the retail-sentiment build — consumes the raw fetchers, produces the §4 contrarian-filter signal. Manual by design — no automatic refresh, no cron.
---

# Sentiment Cache Skill

## When to use

Trigger this skill when the user says:
- "Score sentiment" / "Refresh composite sentiment"
- "Run the sentiment classifier"
- "Show me the contrarian flags"
- "Show me the sentiment cache"

Do NOT trigger for:
- Raw fetch (use `reddit-sentiment` or `stocktwits-sentiment` directly)
- Single-shot agent sentiment reads during analysis (read the JSON file directly)
- Professional news scoring (Alpha Vantage already scores those; use `us-news`)

## Why this exists

The raw fetchers (`reddit-sentiment`, `stocktwits-sentiment`) collect posts and messages but don't classify them. StockTwits has *some* user-tagged Bull/Bear labels, but coverage is partial (~40-60% on liquid US names) and the labels are self-reported (gameable).

This skill:
1. Reads the raw caches from both sources
2. Sends untagged message bodies through the authenticated OpenAI/Codex route for sentiment classification (bull/bear/neutral with conviction 0-1)
3. Combines user-tagged labels + LLM scores + Reddit post sentiment into a per-ticker composite
4. Applies the contrarian-filter logic (extreme bull → fade flag; extreme bear with constructive setup → buy flag)
5. Writes the canonical `sentiment.json` that the dashboard reads

Per AGENTS.md §4, retail sentiment is a **contrarian filter**, not an additive bull signal. Extreme retail bullishness + extended technicals = downgrade conviction; extreme retail bearishness + Phase 1 setup = upgrade conviction.

## Provider and model

- Provider: `openai-codex`, using the existing Hermes/Codex OAuth credential route.
- Default model: `gpt-5.6-luna` at low reasoning. A direct structured-output probe used 108 input tokens and returned schema-valid JSON; the generic agent wrapper was rejected for this path because its scaffold consumed roughly 15.9k input tokens for the same one-item task.
- Override only the model with `OPENAI_CODEX_MODEL`. No project API key is required.
- Calls go directly through the supported Responses client with strict JSON Schema and no tools. OpenRouter is not a fallback. Provider or parse failure preserves cached/stale data.
- Each composite stores a deterministic fingerprint of the exact message/engagement inputs. Unchanged raw data reuses the successful Codex result with zero model calls; transport timestamps do not invalidate it. Use `--force` only for an intentional re-score.

Runtime requirement: run under the managed Hermes Python used by the dashboard, or set `HERMES_AGENT_ROOT` to the existing Hermes Agent install. Authentication remains owned by Hermes/Codex; this skill never reads or stores the OAuth token.

## Usage

```bash
# Score all watchlist tickers from existing raw caches
python3 .claude/skills/sentiment-cache/sentiment_cache.py

# Score specific tickers
python3 .claude/skills/sentiment-cache/sentiment_cache.py AUPH NVDA BTC

# Show composite cache (badges + flags per ticker)
python3 .claude/skills/sentiment-cache/sentiment_cache.py --show

# Show one ticker in detail (rationale, source breakdown)
python3 .claude/skills/sentiment-cache/sentiment_cache.py --show AUPH

# Clear cache
python3 .claude/skills/sentiment-cache/sentiment_cache.py --clear
```

This skill **does not refetch** — it consumes whatever's in the raw caches. Run `reddit-sentiment` / `stocktwits-sentiment` first to refresh inputs.

## Output

`.claude/cache/sentiment/{TICKER}.json`:

```json
{
  "ticker": "AUPH",
  "asset_class": "us_equity",
  "scored_at": "2026-06-08T12:34:56Z",
  "provider": "openai-codex",
  "model": "gpt-5.6-luna",
  "sources": {
    "stocktwits": {
      "present": true,
      "n_messages": 30,
      "user_tagged_bull_pct": 1.0,
      "llm_bull_pct": 0.87,
      "llm_bear_pct": 0.07,
      "llm_neutral_pct": 0.06
    },
    "reddit": {"present": false}
  },
  "composite": {
    "bull_score": 0.93,
    "bear_score": 0.04,
    "neutral_score": 0.03,
    "conviction": 0.88,
    "label": "EXTREME_BULL",
    "badge": "🔥",
    "contrarian_flag": "FADE",
    "rationale": "ST: 30 msgs, 100% user-tagged bull (8 tagged), LLM-confirmed 87% bull on rest. No Reddit data."
  }
}
```

## Composite scoring

`bull_score`, `bear_score`, `neutral_score` are weighted averages across sources (and within source, across user-tagged and LLM scores). When both Reddit and StockTwits are present, they're weighted 50/50. When only one is present, it carries 100%.

`label` is derived from `bull_score` and `bear_score`:
- **EXTREME_BULL** (🔥): `bull_score ≥ 0.80` and `conviction ≥ 0.70` → contrarian_flag = `FADE`
- **BULL** (📈): `bull_score ≥ 0.60`
- **NEUTRAL** (—): everything else
- **BEAR** (📉): `bear_score ≥ 0.60`
- **EXTREME_BEAR** (🧊): `bear_score ≥ 0.80` and `conviction ≥ 0.70` → contrarian_flag = `BUY`

The `contrarian_flag` is what the §4 doctrine consumes. `FADE` is a one-tier downgrade on already-extended setups; `BUY` is a one-tier upgrade on already-constructive P1 setups. Mid-range labels are no-op (most names land here — which is correct).

## What this skill is NOT

- Not a raw fetcher — needs upstream caches populated
- Not a real-time stream — manual refresh
- Not the only sentiment input to §4 — combines with `us-news` (professional) and the user's read of the chart
- Not a trade signal on its own — purely a confluence modifier
