# Sector Rotation — User Guide

Daily compass for "where is money flowing in the US equity market?" Ranks the 11 SPDR sector ETFs by their relative performance vs SPY over 1m/3m/6m windows, producing a single composite score per sector.

---

## Quick start

```bash
# Refresh (1h cache, runs fast after first call)
python3 .claude/skills/sector-rotation/sector_rotation.py

# Then rebuild dashboard — the Discovery panel's top strip will reflect new data
python3 .claude/skills/dashboard/dashboard.py
```

Open the dashboard, look at the top of the **🔭 Discovery** panel. Green cells = leading sectors. Red cells = lagging. Hover any cell for full 1m/3m/6m breakdown.

---

## How to read the heat strip

Each of the 11 cells shows the sector symbol, its composite score, and its name. Cells are sorted left-to-right by rank (strongest first).

The **composite score** is a weighted average of vs-SPY relative performance:
- 50% weight on the last 1 month (recent action)
- 30% weight on the last 3 months (intermediate trend)
- 20% weight on the last 6 months (long-term confirmation)

So a composite of **+10** means the sector has, on average, beaten SPY by ~10 percentage points across those windows. A composite of **−5** means it's lagged by ~5.

| Color | Threshold | Meaning |
|---|---|---|
| 🟢 Green | composite > +2 | Clear sector leadership — money rotating IN |
| ⚪ Neutral | composite ∈ [−2, +2] | Tracking the broad market |
| 🔴 Red | composite < −2 | Clear lag — money rotating OUT |

---

## Three patterns worth recognizing

### 1. Narrow leadership (only 1-2 green sectors)

Example: XLK at +18, everything else red.

**What it means:** the rally is concentrated in one theme (often tech / AI). Broad market exposure is fragile — a reversal in the leading sector takes the whole index down.

**Action:**
- Be selective with screener candidates
- Don't chase tech leaders late
- Remember the correlation tax: "five tech longs is one bet"

### 2. Defensive rotation (XLP / XLU / XLV / XLRE leading)

Money fleeing cyclicals into bond-proxy/defensive names.

**What it means:** risk-off behavior, often precedes broader weakness.

**Action:**
- Tighten stops on existing positions
- Lower portfolio heat
- Be skeptical of new long entries — wait for the rotation to complete

### 3. Cyclical rotation (XLY / XLI / XLB / XLF leading)

Discretionary, industrials, materials, financials in the lead.

**What it means:** healthy, risk-on environment. Often early/mid-cycle.

**Action:**
- P1 setups in these sectors get a green light
- Tech leaders can be safely added (broad participation)
- Consider increasing portfolio heat closer to the 6% ceiling

---

## Why this exists

Without sector context, stock-by-stock analysis is fishing in random ponds. The us-screener might surface a beautiful P1 setup in Real Estate, but if XLRE is at −15 composite, you're fighting the tape. Sector rotation tells you which ponds are stocked.

Pair this with the us-screener: when you see a leading sector, expect more candidates from it. When everything's red except one sector, expect a narrow candidate list and adjust your size-down accordingly.

---

## Cache behavior

- **TTL:** 1 hour. Sector rankings don't shift minute-to-minute.
- **Location:** `.claude/cache/sector_rotation/data.json`
- **Refresh:** automatic when stale; pass `--refresh` to force.
- **Speed:** ~10 seconds for the full 12-ETF fetch (bulk yfinance call).

---

## Common questions

**Q: Why these 11 sectors, not Russell-style sub-industries?**
A: The 11 SPDR sectors cover the entire S&P 500 with no overlap. Sub-industries (semis vs software vs hardware) add granularity but also noise. For a $20k account, sector-level is the right resolution.

**Q: Why not include international ETFs (EFA, EEM)?**
A: This is a *US-equity rotation* tool. International rotation is a separate question (and the watchlist is currently US + KLSE + crypto, not international ETFs).

**Q: Can I change the weights (1m/3m/6m)?**
A: Yes — edit `sector_rotation.py`, the `weights` variable inside the composite calc. Heavier 6m weight = slower, more durable signal. Heavier 1m weight = more reactive.

**Q: My XLK score looks crazy high — is that a bug?**
A: Probably not. Tech routinely rotates to +20 or higher composite when AI/megacap names rip. The signal is real; the action is "don't chase blindly."

---

## Honest limitations

1. **Sector ETF != all stocks in that sector.** XLK is mostly AAPL/MSFT/NVDA by weight. Small-cap tech (e.g. fintech, smaller SaaS) may diverge.
2. **6-month is the longest window.** Multi-year rotations require manual review (e.g. checking 1y/2y charts).
3. **End-of-day data only.** Don't use this for intraday timing decisions.
4. **yfinance can break** when Yahoo changes their backend. If sector ETFs return "no data", wait a day or longer-term switch to FMP.

---

## TL;DR

- Run before any new-trade decision
- Green sectors = preferred hunting ground; red sectors = avoid
- Watch the spread: narrow leadership = fragile; broad leadership = healthy
- Pairs with us-screener — the two together tell you "where" AND "what"
