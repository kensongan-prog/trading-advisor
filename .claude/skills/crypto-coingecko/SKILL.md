---
name: crypto-coingecko
description: Fetch real, timestamped crypto data from CoinGecko — prices, % changes, market cap, ATH/ATL, community sentiment votes, GitHub/dev activity, OHLC history with computed RSI/SMA/ATR indicators, and recent news headlines (via WebFetch on the coin page). Use whenever the user references any crypto asset — Bitcoin, Ethereum, alts, stablecoins, or a specific CoinGecko ID. Required before any crypto recommendation because Massive's crypto coverage is solid for prices/aggregates but lacks community sentiment, dev signals, and per-coin news.
---

# CoinGecko Skill (Crypto Prices, Sentiment, News)

## When to use

Trigger this skill on any crypto-related request:

- A coin symbol (BTC, ETH, SOL, ONDO, etc.) or CoinGecko ID (`bitcoin`, `ondo-finance`).
- Phrases like "is X overbought," "what's the sentiment on Y," "any recent news on Z."
- Pre-trade confluence check on a crypto thesis (CLAUDE.md §4 requires sentiment + technicals).
- Multi-coin comparison: "BTC vs ETH vs SOL momentum."

Do NOT use this skill for:
- US equities (Massive + `us-news`).
- KLSE (the three klse-* skills).
- Forex (Massive forex endpoints).

## Why this exists

Massive MCP covers crypto prices and aggregates, but **not**:
- Community sentiment votes (CoinGecko's % up/down)
- Developer activity (GitHub stars, commits, PRs — a real moat-vs-deadcoin signal)
- Per-coin news headlines (Massive's news/sentiment is US-equity focused)
- Smaller alts that may not be in Massive's universe

CoinGecko fills these gaps with a generous free tier (no key required, ~10-30 req/min).

## Setup — optional

Works without a key. If you want higher rate limits, get a free Demo API key (no credit card) at https://www.coingecko.com/en/api/pricing and add to `.claude/skills/crypto-coingecko/.env`:

```
COINGECKO_API_KEY=your-demo-or-pro-key
```

The script auto-loads the .env if present. **Without a key**, it uses the public endpoint — which has lower rate limits but works fine for ad-hoc research.

## Subcommands

The skill ships a single Python script `cg.py` with three subcommands.

### `quote` — single-coin snapshot

```
python3 .claude/skills/crypto-coingecko/cg.py quote --coin bitcoin
python3 .claude/skills/crypto-coingecko/cg.py quote --coin sol
```

Returns:
- Price, 24h/7d/30d/1y % change
- Market cap, 24h volume, supply (circ/total/max)
- ATH and ATL with % distance from each
- **Community sentiment votes** (% up / % down) — note: contrarian signal at extremes; do not blindly follow
- **Developer activity** (last 4 weeks of commits, PRs, GitHub stars) — a real coin-vs-shitcoin filter
- Categories and CoinGecko market cap rank

### `history` — OHLC + indicators

```
python3 .claude/skills/crypto-coingecko/cg.py history --coin btc --days 90 --indicators rsi,sma20,sma50,sma200,atr14 --rows 10
```

Returns recent OHLC bars + computed RSI(14), SMA20/50/200, ATR(14).

**Resolution caveat (CoinGecko free /ohlc):**
- `--days 1` → 30-minute candles
- `--days 2..30` → 4-hour candles
- `--days 31..max` → 4-day candles (NOT daily)

This means **SMA200 effectively requires ~800 days of data**, which the free /ohlc endpoint won't give in daily resolution. If you need SMA200 on crypto, the workaround is to fall back to the Massive MCP's daily aggregates endpoint for that coin — Massive has daily granularity over longer windows. Massive also has its own RSI/SMA endpoints for crypto. **Prefer Massive for technicals on majors (BTC/ETH/SOL); use this skill for sentiment + community + dev + sub-$100M-cap alts that Massive may not index.**

### `regime` — composite crypto regime read

```
python3 .claude/skills/crypto-coingecko/cg.py regime
```

Returns a top-down crypto regime read combining four free public sources, modeled on the `macro-rates regime` output:

- **Crypto Fear & Greed Index** (alternative.me, no auth) — current value (0-100) with classification + 7d trend
- **BTC dominance** (CoinGecko /global) — % of total mcap in BTC
- **ETH dominance** (CoinGecko /global) — % in ETH
- **Total crypto market cap** + 24h % change
- **Stablecoin dominance** — combined USDT+USDC+DAI+USDE+FDUSD+TUSD share (proxy for "dry powder on sidelines")

Composite verdict is one of:
- **STRONG ACCUMULATION** (score ≥ +1.5) → extreme fear + alt-friendly setup; bias toward DCA buys with structural triggers
- **CONSTRUCTIVE** (+0.5 to +1.5) → mild contrarian-buy lean
- **NEUTRAL** (−0.5 to +0.5) → no crypto-specific regime tilt; confluence must stand on its own
- **DISTRIBUTION** (−0.5 to −1.5) → mild bearish/cautious lean
- **EUPHORIA** (≤ −1.5) → likely late-cycle / top zone; bias to take profits, no new chase entries

**Signal interpretation:**

| Fear & Greed | Read | Doctrine action |
|---|---|---|
| ≤ 25 (Extreme Fear) | Contrarian buy zone | Be ready, but extremes can persist — wait for a price-trigger reversal |
| 26-45 (Fear) | Mild contrarian buy | Standard sizing, prefer pullback setups |
| 46-54 (Neutral) | No edge | Confluence-driven |
| 55-74 (Greed) | Mild caution | Tighten R:R; avoid chase entries |
| ≥ 75 (Extreme Greed) | Top zone | No new long-side chasing; consider trims |

| BTC dominance | Read |
|---|---|
| > 60% | BTC-dominant regime; alts under pressure — avoid alts unless idiosyncratic |
| 45-60% | Neutral |
| < 45% | Alt-season territory; alts viable per playbook |

| Stablecoin dominance | Read |
|---|---|
| ≥ 8% | Significant dry powder on sidelines — buying capacity available |
| 4-8% | Normal |
| < 4% | Most capital deployed — less buying power left, vulnerable to forced-selling cascade |

### `markets` — side-by-side comparison

```
python3 .claude/skills/crypto-coingecko/cg.py markets --coins btc,eth,sol,ondo
```

Returns price + 1h/24h/7d/30d % + market cap + 24h volume in one table. Useful for regime checks ("is alt season starting?") and correlation sanity checks.

### Symbol → ID mapping

The script knows common symbols (btc, eth, sol, bnb, xrp, ada, doge, ton, trx, avax, matic, dot, link, uni, ltc, atom, near, apt, arb, op, ondo, hype, sui). Anything else **must be the explicit CoinGecko ID** — find it at coingecko.com (it's in the URL of the coin's page, e.g. `ondo-finance`, `the-graph`).

## News (via WebFetch on the coin page)

CoinGecko's free API has no real news endpoint. Their public coin page DOES embed a "Latest News" section. Fetch it with WebFetch:

```
URL:    https://www.coingecko.com/en/coins/{COINGECKO_ID}
Prompt: "Locate the 'Latest News' section for this coin. List the 10 most recent
         headlines with: date/time-ago, source publication, headline, and a
         one-line summary. Explicitly flag any item that:
           - mentions an exchange listing, delisting, or regulatory action
           - mentions an exploit, hack, depeg, or governance attack
           - is a price-prediction / analyst note (and what direction/target)
           - mentions a partnership, integration, or product launch
           - is from a primary source vs an aggregator
         Return 'NO HEADLINES' if the section is missing/empty; do not invent items."
```

For broader market context (not just one coin), use `https://www.coingecko.com/en/news` instead. Each headline there has tagged coins with confidence scores.

## Hard rules for `regime`

1. **Fear & Greed is contrarian, not directional.** Extreme Fear at 11/100 does not mean "buy now." It means "the conditions for a bottom are forming." Wait for a price-action confirmation (a reclaim of SMA20, a higher-low structure, etc.) before sizing in.

2. **F&G and BTC dominance can disagree** — F&G can be extreme fear while BTC dominance is rising (BTC outperforming on the downside, alts crashing harder). Read them as separate signals, not as confirmations of each other.

3. **The crypto regime is independent of the US macro regime.** They can point in opposite directions (e.g., macro CAUTIOUS due to real yields + crypto CONSTRUCTIVE due to F&G extreme fear). When they disagree, the doctrine says: macro tilts position sizing, crypto regime tilts confluence threshold. Don't average them.

4. **`regime` is a context layer, NOT a green light.** A CONSTRUCTIVE regime read does not mean "skip the per-coin work." You still need `crypto-derivatives snapshot` (positioning) + `crypto-unlocks` (event halt) + Massive technicals before any entry.

5. **If `regime` fetch fails** (alternative.me down, CoinGecko rate-limited), proceed with explicit note "crypto regime unverified — proceeding without regime adjustment" and lower conviction one level.

## Combined-skill recipe (crypto pre-trade workflow)

For any crypto recommendation, run in order:

1. **`cg.py regime`** → top-down crypto regime (F&G, BTC.D, total mcap, stable %) — sets confluence threshold.
2. **`cg.py quote --coin {ID}`** → price, community sentiment %, dev signals, supply.
3. **Massive `/v2/aggs/ticker/X:BTCUSD/range/1/day/{from}/{to}`** → reliable daily OHLCV for technicals (longer history than CoinGecko /ohlc free tier).
4. **Massive RSI / SMA endpoints** OR `cg.py history` for indicators.
5. **WebFetch on `coingecko.com/en/coins/{id}`** → news + catalysts + event risk.
6. **`crypto-derivatives snapshot --symbol {COIN}USDT`** → funding + OI + L/S divergence.
7. **`hyperliquid-flow asset --coin {COIN}`** or `compare` → on-chain positioning + venue divergence.
8. **`crypto-unlocks` per-token check** → 48h supply-event halt gate.
9. **Check `cg.py quote` dev stats**: a "trending alt" with 0 commits in 4 weeks is a major flag. Real projects ship code.
10. Apply CLAUDE.md §5 risk doctrine. Note crypto-specific rules:
   - Weekend gap risk: spot crypto stops can blow through overnight/weekend. Size down or cap loss with a defined sleeve allocation.
   - Funding rate / open-interest flush risk: not in CoinGecko free; flag as unverified.
   - **Token unlocks within 48h** (CLAUDE.md §5 event halt rule): not directly in CoinGecko free — you'll need a separate unlock-schedule check (TokenUnlocks.app, or manual).
7. Recommendation in CLAUDE.md format with all `Fetched (UTC)` timestamps cited.

## Hard rules

1. **If `FETCH FAILED` or `NO DATA`, recommendation drops to NO-TRADE or low-confidence with the failure called out.** Never substitute LLM memory or general web search.

2. **Sentiment votes are noisy.** CoinGecko community votes are a contrarian gauge at extremes (>70% bullish or <30% bullish), not a directional signal. Do not use them as a primary input.

3. **Dev activity matters more for alts than for BTC.** Bitcoin's "commits" number is moderate by design (mature codebase, conservative changes). For a Layer 1 or DeFi protocol, **zero commits in 4 weeks is a red flag**.

4. **Cross-check price against Massive for majors.** CoinGecko's price feed aggregates across exchanges; Massive uses different sources. Material disagreement (>1%) on a major like BTC = data-integrity issue, stop and investigate before trading.

5. **Token-unlock event risk is NOT covered by this skill.** CLAUDE.md §5 requires checking unlocks within 48h of entry; this is a manual external check until a dedicated source is wired.

## What this skill does NOT cover

- **Funding rates / open interest** (perpetual futures positioning) — not in CoinGecko free; needs a derivatives-specific source.
- **On-chain flows** (whale movements, exchange in/out) — needs Glassnode, Nansen, or Santiment.
- **Token unlock schedule** — needs TokenUnlocks or a manual check.
- **Real-time alerts / watchlist monitoring** — pull model, not push.
- **NFT data** — out of scope.
