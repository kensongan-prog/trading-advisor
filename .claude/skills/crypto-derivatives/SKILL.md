---
name: crypto-derivatives
description: Fetch real, timestamped crypto derivatives positioning data from Binance Futures public API — funding rates (per-8h + annualized), open interest with trend, long/short account ratios (top traders vs retail), taker buy/sell ratio, and divergence flags. Use whenever a crypto recommendation needs a positioning/flow read — i.e. is the market crowded long, is there flush risk, is there a smart-money-vs-retail divergence. Required as part of crypto pre-trade confluence per CLAUDE.md §4 (positioning is the "flow" leg) and §5 (flush risk on leveraged crowded books).
---

# Crypto Derivatives Skill (Binance Futures Positioning)

## When to use

Trigger on any crypto recommendation where you need to know:

- **Is the market crowded long or short?** (funding rate, L/S ratio)
- **Is open interest rising or falling?** (fresh positioning vs unwind)
- **Are top traders disagreeing with retail?** (the classic divergence setup)
- **Is there flush risk?** (very crowded long with positive funding = liquidation cascade fuel)
- **Pre-trade event-risk check** for derivatives-driven moves before considering spot entry.

Do NOT trigger this skill on US equities, KLSE, or any non-crypto asset.

## Why this exists

Funding rates, open interest, and long/short ratios are first-class signals for crypto. CoinGecko (the `crypto-coingecko` skill) gives sentiment votes and dev activity but NOT derivatives positioning. Massive's crypto coverage is spot-focused. Without this skill, the "flow" leg of CLAUDE.md §4 confluence is missing for crypto.

## Source

**Binance Futures public REST API** (`fapi.binance.com`). No authentication required, no key needed, no rate-limit issues at retail-research scale. Binance is the largest futures venue by far — its book IS the market for BTC/ETH/SOL positioning. For altcoins with thinner Binance liquidity, the read is less reliable and you may need to cross-check with Bybit/OKX.

## Subcommands

### `snapshot` — current positioning + recent trend

```
python3 .claude/skills/crypto-derivatives/binance_derivs.py snapshot --symbol BTCUSDT --period 4h --lookback 8
```

Returns:
- **Funding rate** (per 8h + annualized % + signal label)
- **Mark / index price**
- **Open interest** (current contracts + USD value + % change over window)
- **Long/short ratio — top trader accounts** (smart-money proxy)
- **Long/short ratio — all accounts** (retail proxy)
- **Taker buy/sell ratio** (aggression read)
- **Divergence flag** if top traders and retail are on opposite sides

`--period` options: `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `12h`, `1d`. Use `4h` for swing decisions, `1h` for intraday.
`--lookback` controls how many bars of OI/LS history are pulled.

### `funding-history` — historical funding curve

```
python3 .claude/skills/crypto-derivatives/binance_derivs.py funding-history --symbol BTCUSDT --limit 30
```

Returns last N funding intervals (8h each on most majors). Use to spot persistent regimes ("BTC funding has been negative for 7 days = stubborn shorts, squeeze potential").

### Symbol normalization

- `BTCUSDT` → used as-is
- `btc`, `eth`, `sol`, ... → mapped to `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, ...
- Built-in map covers: btc, eth, sol, bnb, xrp, ada, doge, ton, trx, avax, matic, dot, link, uni, ltc, atom, near, apt, arb, op, ondo, hype, sui, ena, pyth, strk, wld, tia.
- Anything else → script appends `USDT` (use the Binance-listed symbol exactly if it doesn't auto-resolve).

## Reading the signals

### Funding rate (per 8h, annualized)

| Per-8h rate | Annualized | Label | Read |
|-------------|------------|-------|------|
| > +0.05% | > +55% | VERY CROWDED LONG | Leverage stacked; flush risk on any pullback. |
| +0.02% to +0.05% | +22% to +55% | crowded long | Long bias but not extreme. |
| −0.02% to +0.02% | −22% to +22% | neutral | No positioning edge. |
| −0.02% to −0.05% | −22% to −55% | crowded short | Squeeze fuel on any bounce. |
| < −0.05% | < −55% | VERY CROWDED SHORT | Capitulation; squeeze likely on first reclaim. |

**Counter-positioning trades are powerful but require a trigger.** Don't fade extreme funding without a price-action confirmation. Crowded can stay crowded for weeks.

### Open interest

- **OI rising + price rising** = real demand, sustainable move.
- **OI rising + price falling** = aggressive shorting, risk of squeeze if sentiment shifts.
- **OI falling + price rising** = short covering, may not have staying power.
- **OI falling + price falling** = capitulation, often near a low.
- **Sharp OI drop** (>10% in a few hours) = liquidation cascade, often marks a local extreme.

### Long/short ratio — top traders vs retail

**Top traders** are accounts in the top % by holdings on Binance — closer to smart money than retail. **Divergence** between top traders and all-account ratio is the signal worth watching:

- Top short while retail long → bearish (smart money positioned against the crowd).
- Top long while retail short → bullish (smart money fading the panic).

The skill prints these divergence flags automatically.

### Taker buy/sell ratio

> 1.2 = aggressive taker buying (impatient demand)
< 0.8 = aggressive taker selling (impatient supply)
~1.0 = balanced

Higher fidelity than OI alone for "are buyers reaching across the spread right now."

## Hard rules

1. **Funding and OI are positioning data, not price predictions.** A crowded-long book can stay crowded for weeks; don't enter a short just because funding is positive. Wait for technical confirmation.

2. **Single-exchange caveat.** This data is Binance only. For BTC/ETH/SOL it's the dominant venue and the read is robust. For altcoins where Binance is a minority of futures volume, cross-check with Bybit/OKX before trusting the signal (skill does not currently do this — flag as a confidence reduction in the recommendation).

3. **CLAUDE.md §5 flush-risk rule:** when funding is in "VERY CROWDED LONG" territory AND you're entering a long, size DOWN and acknowledge the cascade risk explicitly. When entering a long against "VERY CROWDED SHORT," the squeeze probability is in your favor but you still need a price trigger.

4. **If FETCH FAILED, the positioning leg of confluence is unavailable.** Drop confidence one level and explicitly say so in the recommendation. Do not fill from memory.

5. **Funding-history skill is for regime detection, not market timing.** Don't try to predict the next funding rate from the trend — predict the regime ("structurally positive for 7 days = persistent long demand").

## Combined-skill recipe (full crypto pre-trade workflow, updated)

For any crypto recommendation, run in order:

1. `crypto-coingecko quote` → price + sentiment % + dev signals.
2. Massive daily OHLCV + indicator endpoints (RSI/SMA) → technicals on a long history.
3. WebFetch on `coingecko.com/en/coins/{id}` → news + catalysts.
4. **`crypto-derivatives snapshot`** → funding + OI + L/S divergence (THIS SKILL).
5. **`crypto-unlocks` check** → 48h unlock-halt window (sibling skill).
6. Risk doctrine gate (§7).
7. Output recommendation with all four `Fetched (UTC)` timestamps in the data snapshot.

## What this skill does NOT cover

- **Cross-exchange aggregation** — Binance only. Use Coinglass via WebFetch for multi-venue checks when needed.
- **Liquidation maps / heatmaps** — Coinglass and Hyblock charge for this.
- **On-chain flows** (whale movements, exchange in/out) — Glassnode/Nansen/Santiment.
- **Options flow** (gamma exposure, dealer positioning) — Deribit data, not Binance.
- **Token unlock schedules** — separate `crypto-unlocks` skill.
