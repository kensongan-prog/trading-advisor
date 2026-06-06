---
name: crypto-unlocks
description: Check upcoming token unlock events for any crypto asset via Tokenomist.ai (formerly TokenUnlocks). Returns the next unlock date, type (cliff vs linear), estimated size, and a YES/NO on whether the unlock falls inside the doctrine's 48-hour halt window. REQUIRED before any new directional crypto position per CLAUDE.md §5 — entering a long inside the 48h pre-unlock window for an unlock > 1% of float is a doctrine violation.
---

# Crypto Token Unlocks Skill

## When to use

Trigger this skill **as a mandatory gate before any new directional crypto recommendation**, especially for altcoins. Also trigger when the user asks:

- "Is there an unlock coming on X?"
- "When does Y next unlock?"
- "What's the next big unlock?"

Do NOT trigger for:
- BTC (no scheduled unlocks — Bitcoin's emission is gradual mining, not a vesting cliff).
- Stablecoins (USDC/USDT — no equity-like vesting).
- US equities, KLSE, forex.

## Why this exists

CLAUDE.md §5 (event-halt rule): **"Crypto: 48h before a scheduled token unlock > 1% of float"** — no new directional exposure. Without an unlock data source, every alt recommendation would silently violate this rule. This skill is the source of truth for the gate.

## Source

**Tokenomist.ai** (formerly TokenUnlocks.app — same product, rebranded). Public website, no auth required for the basic next-unlock date and type. Some sizing details are gated to their Pro tier, but the **next-unlock date is what triggers the halt rule**, and that's freely available.

Fallback: We tried the DeFiLlama emissions API — it has moved behind a paid plan (HTTP 402). If Tokenomist is unreachable, current options are:
1. Manual check on coingecko.com (coin overview sometimes mentions vesting).
2. The project's token blog / docs.
3. Declare NO-TRADE — per doctrine, no source = no go.

## How to use

Tokenomist has a per-token URL pattern: `https://tokenomist.ai/{coin-slug}` where `{coin-slug}` is typically the lowercase coin name (e.g. `hyperliquid`, `ethena`, `arbitrum`, `optimism`, `aptos`). Do NOT assume the slug equals the ticker — verify by fetching once and checking the page resolves.

### Per-token check (the standard pre-trade gate)

Use WebFetch:

```
URL:    https://tokenomist.ai/{coin-slug}
Prompt: "What is the next scheduled token unlock event for this token?
         Provide:
           - exact date (and time if shown)
           - type: cliff vs linear vesting
           - amount of tokens unlocked (if shown — Pro-gated values are OK to report as 'gated')
           - USD value (if shown)
           - % of circulating supply or % of max/total supply (if shown)
           - recipient / category (team / investors / treasury / community)
         Then answer two yes/no questions explicitly:
           1. Is the next unlock within 48 hours of today ({YYYY-MM-DD})?
           2. If sizing is visible, is it >1% of float?
         If the page is missing for this token, say 'NOT TRACKED'.
         Do not invent dates."
```

### Market-wide upcoming-unlock scan

```
URL:    https://tokenomist.ai/
Prompt: "List the 10 most imminent token unlock events from the homepage cliff-unlock
         list. For each: ticker, date, USD value if shown, recipient category, and
         whether it falls within 48 hours of today ({YYYY-MM-DD}). Note which tokens
         are sized >$10M as a rough size threshold."
```

Use this when the user asks "what's coming up this week" or as part of a watchlist sweep.

### Slug-resolution tips

Common slugs (verified):
- HYPE → `hyperliquid`
- ENA → `ethena`
- ARB → `arbitrum`
- OP → `optimism`
- APT → `aptos`
- SUI → `sui`
- STRK → `starknet`
- PYTH → `pyth-network`
- ONDO → `ondo-finance`
- TIA → `celestia`
- WLD → `worldcoin`

If the slug doesn't resolve, try the CoinGecko ID, then the lowercase coin name with dashes for spaces.

## Hard rules

1. **If the next unlock is within 48 hours AND sizing is unknown (Pro-gated), treat as inside the halt window.** Per CLAUDE.md §5 doctrine: unknown defaults to halt, not to "probably small." NO-TRADE on new directional exposure; existing positions get a risk-doctrine review (consider trimming or hedging).

2. **If the next unlock is within 48 hours AND sizing is < 1% of float**, technically it doesn't trigger the halt rule. BUT: state this explicitly in the recommendation, lower confidence one level, and note "supply event during trade — exit if price weakness coincides."

3. **If Tokenomist returns NOT TRACKED**, the unlock-event leg of the doctrine gate is unverified. Default to NO-TRADE on a fresh long unless the coin is a major (BTC, ETH, stablecoins) where unlocks are not the relevant risk model.

4. **Do not extrapolate unlock impact.** "% of circulating supply" is the right denominator for selling-pressure read. Recipient category matters: team unlocks are sell-likely; treasury unlocks may or may not hit market; investor unlocks vary by lockup terms.

5. **Cliff > linear in halt severity.** A cliff unlock = all tokens released at once = sharp supply shock. A linear unlock spreading over months has a much smaller per-day impact. The skill should distinguish them in output.

## Combined-skill recipe (the final crypto pre-trade workflow)

For any crypto recommendation, run in order:

1. `crypto-coingecko quote` → price + sentiment + dev signals.
2. Massive aggregates + indicators → technicals on a long daily history.
3. WebFetch on `coingecko.com/en/coins/{id}` → news.
4. `crypto-derivatives snapshot` → funding + OI + L/S divergence.
5. **`crypto-unlocks` per-token check** → 48h gate (THIS SKILL).
6. Apply CLAUDE.md §5/§7 doctrine gates.
7. Output in CLAUDE.md recommendation format with all `Fetched (UTC)` timestamps cited.

## What this skill does NOT cover

- **Bitcoin halvings** — different schedule, baked into protocol; if a halving is within ~30 days, flag manually.
- **Inflation / staking emissions** — continuous, not event-driven; handled differently in size models.
- **Stablecoin issuance / redemption events** — different risk model.
- **Exact unlock sizing on Pro-gated tokens** — Tokenomist Pro covers this; treat as "unknown → halt" per doctrine.
- **Pre-TGE / private rounds** — out of scope; no public schedule.
