---
name: hyperliquid-flow
description: Fetch on-chain perpetuals data from Hyperliquid's public API — per-coin funding (per-hour + annualized), open interest, order-book imbalance, ANY address's open positions / leverage / P&L / recent fills, and cross-venue funding comparison vs Binance. Use whenever a crypto recommendation needs Hyperliquid-specific positioning, whale-position visibility, or a Binance-vs-HL divergence read. Hyperliquid's L1 makes the orderbook AND every user's position public — unique informational edge not available on CEXes.
---

# Hyperliquid Flow Skill (On-Chain Perp Positioning)

## When to use

Trigger this skill when a crypto recommendation needs any of:

- **HL-specific funding/OI** for a coin (especially HL-native coins like HYPE that are not on Binance).
- **Cross-venue check**: do HL and Binance agree on positioning? Material divergence = signal.
- **Whale watching**: positions, leverage, recent fills for any wallet you can identify.
- **Order-book imbalance** at the top of book — micro-flow read.
- **Crowded book scan**: find the most-extreme funding rates across all 230 HL perps in one shot.

Do NOT trigger for:
- US equities, KLSE, forex.
- Generic crypto price/news questions where HL specifics don't matter (use `crypto-coingecko` + `crypto-derivatives`).

## Why this exists

Hyperliquid is a perpetual DEX running on its own L1. **Because it's on-chain, the entire orderbook AND every user's positions are public.** On a CEX (Binance, Bybit) you can see aggregate L/S ratios but not individual whales. On HL you can pull any address's exact positions, leverage, P&L, and recent fills.

This is the unique informational edge the `crypto-derivatives` skill cannot provide. Combined with that skill (Binance) plus `crypto-coingecko` (sentiment/dev) and `crypto-unlocks` (event gate), the crypto picture is now multi-source.

## Source

**`api.hyperliquid.xyz/info`** — official public API. POST endpoint with JSON body. No auth, no key, no rate-limit issues at retail-research scale. Returns:
- Universe of 230+ perp assets with mark/funding/OI/volume.
- Full L2 order book on any asset.
- Any wallet's clearinghouse state (positions + margin).
- Any wallet's recent fills.

## Subcommands

### `assets` — snapshot of all HL perps with sort options

```
python3 .claude/skills/hyperliquid-flow/hl_flow.py assets --sort funding-abs --top 15
python3 .claude/skills/hyperliquid-flow/hl_flow.py assets --sort oi --top 20
python3 .claude/skills/hyperliquid-flow/hl_flow.py assets --sort change-abs --top 10
```

`--sort` options:
- `funding-abs` — most-extreme funding (long OR short), the **crowded-book scan**.
- `funding` — most positive funding (most-long-crowded).
- `oi` — biggest open-interest books.
- `volume` — biggest 24h notional volume.
- `change-abs` — biggest 24h price movers (both directions).
- `change` — biggest 24h gainers.

Output columns: coin, mark price, 24h %, OI (USD), 24h volume, funding/hr, annualized funding %, regime label, max leverage.

### `asset` — single-coin deep-dive + order-book imbalance

```
python3 .claude/skills/hyperliquid-flow/hl_flow.py asset --coin HYPE
python3 .claude/skills/hyperliquid-flow/hl_flow.py asset --coin BTC --book-depth 20
```

Returns:
- Mark / oracle / mid prices, premium-vs-oracle.
- Funding (per-hour + annualized + regime label).
- OI in tokens and USD.
- 24h notional + base volume.
- **Order book imbalance**: bid size vs ask size in top N levels, with buy-heavy / sell-heavy / balanced verdict and top-of-book spread in bps.

### `whale` — any address's positions, P&L, fills

```
python3 .claude/skills/hyperliquid-flow/hl_flow.py whale --address 0xdfc24b077bc1425ad1dea75bcb6f8158e10df303
python3 .claude/skills/hyperliquid-flow/hl_flow.py whale --address 0x... --fills 25
```

Returns:
- **Account**: account value, total notional position, raw USD, margin used, effective leverage.
- **Open positions**: coin, side (LONG/SHORT), size, entry, leverage, mark, unrealized P&L, liquidation price.
- **Recent fills**: time, coin, side, price, size, $ notional, fee, closed P&L per fill.

**Finding addresses to watch:**
- HypurrScan.io leaderboards (largest accounts).
- Hyperliquid's own /stats page.
- Twitter/X — many large positions are doxxed publicly. Maintain a small list in the project (a `whales.md` file would be a useful add-on).

### `compare` — HL vs Binance funding for the same coin

```
python3 .claude/skills/hyperliquid-flow/hl_flow.py compare --coin BTC
python3 .claude/skills/hyperliquid-flow/hl_flow.py compare --coin ETH
```

Prints side-by-side: mark price, raw funding rate, cadence (HL per-hour vs Binance per-8h), annualized %, regime, OI USD. Then a **divergence read**:
- |spread| < 10 pp annualized → aligned, no signal.
- > 20 pp → one venue's longs paying materially more than the other → positioning split.
- Mark price spread > 50 bps → ⚠ data-integrity / arb opportunity.

For HL-native coins (HYPE etc.), Binance side gracefully prints "not found, HL-native."

## Reading the signals

### Funding cadence math (IMPORTANT)

Hyperliquid funds **every hour**; Binance funds **every 8 hours**. Raw numbers are not comparable. Always annualize:

- HL annualized: `rate × 24 × 365 × 100`
- Binance annualized: `rate × 3 × 365 × 100`

The skill does this automatically and labels with cadence.

### HL funding regime thresholds (per-hour rate)

| Per-hour rate | Annualized | Label |
|---------------|------------|-------|
| > +0.00006 | > +53% | VERY CROWDED LONG (flush risk) |
| +0.000025 to +0.00006 | +22% to +53% | crowded long |
| −0.000025 to +0.000025 | −22% to +22% | neutral |
| −0.00006 to −0.000025 | −22% to −53% | crowded short |
| < −0.00006 | < −53% | VERY CROWDED SHORT (squeeze fuel) |

### Order-book imbalance

`(bid_size − ask_size) / (bid_size + ask_size)` over the top N levels:
- > +5% → buy-heavy (resting demand exceeds offers near touch)
- < −5% → sell-heavy
- Otherwise → balanced

This is a micro signal — useful for execution timing within an already-decided trade, NOT for thesis. Imbalances can flip in seconds.

### Whale position interpretation

- **Effective leverage** (totalNtlPos / accountValue) > 5x = aggressive. Forced-liquidation risk if the book moves.
- **Unrealized P&L** sign + size tells you whether the whale is in profit or hurting — a deeply-underwater whale on a large position is a forced-seller candidate.
- **Liquidation price** proximity to current mark = how much room they have before forced unwind.
- **Recent fills cadence**: scaling in (multiple same-side fills) vs flipping (sides changing) tells you conviction direction.

### Cross-venue divergence

- HL annualized funding > Binance annualized by > 20 pp → HL crowd more bullish (or HL has higher leverage longs paying for them).
- Reverse holds for shorts.
- **Tradeable interpretation:** the venue with HIGHER funding has the more-crowded book — that's where the flush is more likely if price moves against the crowd.

## Hard rules

1. **HL on-chain transparency does NOT mean you know more than the market.** Whale wallets you can identify are sometimes deliberately leaving signals (or are HFT bots). Use whale data as one input, not as gospel.

2. **Cadence trap:** never compare raw HL funding (per-hour) to Binance funding (per-8h). Always annualize. The skill labels cadence explicitly to prevent this.

3. **HL-native coins (HYPE, etc.) have NO Binance cross-check.** `compare` will print "not found" — note this lowers confidence on the positioning read by one level (single-venue data).

4. **Order-book imbalance is intraminute signal.** Do not anchor a swing trade on it. Re-check at execution time.

5. **Whale address verification:** an address you assume is a whale could be a hot wallet, a market maker, or a vault. Cross-reference with HypurrScan or the public Twitter @-tracking community before treating positions as conviction signal.

6. **If FETCH FAILED, the HL leg of confluence is unavailable.** Drop confidence one level and say so. Do not fabricate.

## Combined crypto pre-trade workflow (final, all six skills)

For any crypto recommendation:

1. **`crypto-coingecko quote`** → price, sentiment %, dev signals.
2. **Massive** daily aggregates + indicators → long-window technicals.
3. **WebFetch on `coingecko.com/en/coins/{id}`** → news.
4. **`crypto-derivatives snapshot`** → Binance funding + OI + L/S divergence.
5. **`hyperliquid-flow asset` or `compare`** → HL-side positioning + cross-venue divergence (THIS SKILL).
6. **`crypto-unlocks` per-token check** → 48h unlock-halt gate.
7. Risk doctrine gate (§7) including any flush/halt warnings.
8. Output with all `Fetched (UTC)` timestamps cited.

## What this skill does NOT cover

- **Hyperliquid spot markets** — only perps in scope here.
- **Vault performance / HLP returns** — different endpoint family.
- **Historical funding curves on HL** — current snapshot only; add later via `fundingHistory` request type if needed.
- **Liquidation events** — HL surfaces these but it's a separate endpoint; add later.
- **Bridge inflow/outflow data** — needs a different L1 explorer (HypurrScan).
- **EVM / L1 transactions outside perp activity** — out of scope.
