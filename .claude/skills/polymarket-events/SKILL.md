---
name: polymarket-events
description: Manually refresh prediction-market implied probabilities for macro + crypto + geopolitical events from Polymarket's Gamma public-search API. No auth, no rate limit at retail-research scale. Returns the current probability + resolution date for tracked event categories (Fed rate cuts, recession, inflation, BTC/ETH price targets, geopolitical risk). Macro-confluence leg of the §4 sentiment stack — feeds the dashboard's Event Probabilities panel and the §5 halt-window doctrine. Manual by design — no automatic refresh, no cron.
---

# Polymarket Events Skill

## When to use

Trigger this skill when the user says:
- "Refresh prediction markets" / "Refresh Polymarket"
- "What does Polymarket think about Fed cuts?"
- "What's the recession probability?"
- "Show me the event probabilities"

Do NOT trigger for:
- Individual ticker sentiment (use `reddit-sentiment` + `stocktwits-sentiment` + `sentiment-cache`)
- Macro fundamentals (use `macro-rates` for FRED data — actual rates, not implied)
- Scheduled-event halt windows (use `macro-calendar` — that's the event *dates*, this skill is the implied probability of *outcomes*)

## Why this exists

Polymarket is the only large-scale liquid prediction market open to the public. It aggregates the *money-weighted consensus* of speculators on:
- **Fed policy** (rate cuts/hikes, FOMC outcomes)
- **Macro outcomes** (recession, inflation prints, unemployment)
- **Crypto price targets** (BTC/ETH at specific dates)
- **Geopolitics** (tail-risk events)

These signals are *different* from §4 retail forum sentiment (cheap talk) — Polymarket participants are putting cash on outcomes, so the implied probabilities are less gameable. The doctrine treats Polymarket as a **macro confluence signal**, not a contrarian filter:

- **Aligned** (Polymarket agrees with our macro thesis) → confluence boost
- **Diverged** (Polymarket disagrees) → reconsider thesis, don't auto-fade
- **Tight uncertainty** (probabilities clustered near 50%) → respect the noise, don't overcommit

§5 halt-window doctrine also uses Polymarket: e.g., if FOMC market shows 80% prob of a cut, the regime read for rate-sensitive positions tilts more dovish than the headline FRED number alone suggests.

## Source

**Polymarket Gamma API public-search endpoint:**
`https://gamma-api.polymarket.com/public-search?q={query}&limit=N`

Returns `{events: [...], profiles, tags}` — each event contains nested markets with current outcome prices. No auth required.

**Tracked queries by category** (defined in the skill — curate as needed):
- **macro_rates:** "fed rate cuts", "fed decision", "rate hike"
- **macro_econ:** "recession", "inflation", "unemployment"
- **crypto:** "bitcoin price", "ethereum price"
- **geopolitics:** "china taiwan", "russia ukraine"

Why curated queries instead of generic discovery: Polymarket's tag system is community-driven and noisy (the top "crypto" tag returned Rihanna albums and Jesus return markets at last probe). Curated keyword queries give consistent, on-topic results.

## Usage

```bash
# Refresh all tracked categories
python3 .claude/skills/polymarket-events/polymarket_events.py

# Show cached probabilities (no fetch)
python3 .claude/skills/polymarket-events/polymarket_events.py --show

# Show one category in detail
python3 .claude/skills/polymarket-events/polymarket_events.py --show macro_rates

# Clear cache
python3 .claude/skills/polymarket-events/polymarket_events.py --clear

# Add/replace a query for a category
python3 .claude/skills/polymarket-events/polymarket_events.py --probe "fed rate cuts"
```

## Output

`.claude/cache/polymarket/events.json`:

```json
{
  "fetched_at": "2026-06-08T12:34:56Z",
  "previous_fetched_at": "2026-06-07T08:00:00Z",
  "categories": {
    "macro_rates": {
      "events": [
        {
          "title": "How many Fed rate cuts in 2026?",
          "slug": "fed-rate-cuts-2026",
          "end_date": "2026-12-31",
          "volume_24h": 152345.67,
          "liquidity": 250000.0,
          "url": "https://polymarket.com/event/fed-rate-cuts-2026",
          "markets": [
            {"question": "0 cuts", "yes_price": 0.05, "no_price": 0.95, "delta_7d": -0.02},
            {"question": "1 cut", "yes_price": 0.25, "no_price": 0.75, "delta_7d": 0.04}
          ],
          "headline_prob": 0.80,
          "headline_question": "Any cut in 2026"
        }
      ]
    }
  }
}
```

`headline_prob` is the sum of "Yes" probabilities for outcomes implying the headline question (e.g., for "How many Fed rate cuts" the headline is "any cut" = 1 - prob(0 cuts)). Computed per-category.

`delta_7d` is the change in `yes_price` since the most recent snapshot ≥ 7 days old (null on first refresh).

## What this skill is NOT

- Not real-time orderbook — implied prices update as Polymarket trades but the cache is a snapshot
- Not a trade signal — confluence/divergence with our thesis, not a standalone call
- Not a substitute for `macro-rates` — that's actual FRED data; this is implied speculator consensus
- Not authoritative on probability — Polymarket has known biases (US-political markets skew, thin liquidity on long-dated markets); treat as one input among many
