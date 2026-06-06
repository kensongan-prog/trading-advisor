---
name: sector-rotation
description: Relative-strength ranking of the 11 SPDR sector ETFs (XLK/XLF/XLV/XLY/XLP/XLE/XLI/XLB/XLU/XLRE/XLC) vs SPY over 1m/3m/6m windows. Outputs a composite vs-SPY score (50% weight on 1m, 30% on 3m, 20% on 6m) so you can see which sectors are leading vs lagging the broad market. Dashboard's Discovery panel renders this as a color-coded heat strip. Use to focus the us-screener on leading sectors and to detect narrow-market signals (only 1 green sector = fragile rally). Manual refresh, 1h cache TTL.
---

# Sector Rotation Skill

## When to use

- "Where is money flowing right now?"
- "Which sectors are leading / lagging?"
- Before running the us-screener — bias your candidate review toward leading sectors
- Detecting narrow-market signals (e.g. only XLK green = AI-only rally = fragile)
- Monthly portfolio review — has your exposure been in the leading or lagging buckets?

Do NOT use for:
- Individual stock analysis (use `us-fundamentals`, `us-news`)
- Crypto sector rotation (categories live on CoinGecko; different tool)
- Macro regime (use `macro-rates regime` for that — different signal)

## Why this exists

A trader running stock-by-stock analysis without sector context is fishing in random ponds. Sector rotation answers a strictly different question than P1 setups: not "is this stock ready?" but "is this part of the market where I should even be looking?"

The 11 SPDR sectors cover the entire S&P 500. Comparing each sector ETF vs SPY tells you:
- **+composite** = sector outperforming the broad market (where money is rotating IN)
- **−composite** = sector underperforming (money rotating OUT)
- **Spread between top and bottom** = market breadth (narrow = fragile, wide = healthy)

## Methodology

Single composite score = weighted average of vs-SPY relative performance:
- **1-month** weight: 0.5 (most recent, most actionable)
- **3-month** weight: 0.3 (intermediate trend)
- **6-month** weight: 0.2 (long-trend confirmation)

Color thresholds (heat-map cells on dashboard):
- 🟢 **strong**: composite > +2 (clear leadership)
- 🔴 **weak**: composite < −2 (clear lag)
- ⚪ **neutral**: composite ∈ [−2, +2]

## Universe (the 11 sectors)

| Symbol | Name | Why it matters |
|---|---|---|
| XLK | Technology | Mega-cap tech, AI infra, semis, software |
| XLF | Financials | Banks, insurance, capital markets — rate-sensitive |
| XLV | Health Care | Pharma, biotech, payers, devices |
| XLY | Consumer Disc. | Discretionary spend, autos, travel, retail |
| XLP | Consumer Staples | Defensives — food, beverage, household |
| XLE | Energy | Oil & gas — commodity proxy |
| XLI | Industrials | Cap goods, transports, defense |
| XLB | Materials | Chemicals, miners, paper |
| XLU | Utilities | Defensive yield play, bond proxy |
| XLRE | Real Estate | REITs — rate-sensitive, dividend-heavy |
| XLC | Communication Services | Telecom, media, internet platforms |

(SPY is the baseline, not in the rotation table.)

## Usage

```bash
# Standard run — uses 1h cache if fresh
python3 .claude/skills/sector-rotation/sector_rotation.py

# Force re-fetch (ignore cache)
python3 .claude/skills/sector-rotation/sector_rotation.py --refresh
```

Output to terminal: ranked table with 1m/3m/6m % + vs-SPY columns + composite.

Dashboard reads `.claude/cache/sector_rotation/data.json` on build and renders as the heat strip at top of the Discovery panel.

## Cache

- `.claude/cache/sector_rotation/data.json` — single file with all 12 tickers' data
- TTL: 1 hour (intra-day prices shift, but rankings don't change every minute)
- Bulk fetch via single `yf.download()` call (~10s for all 12 ETFs)

## How to read the output

Three patterns to recognize:

**1. Narrow leadership** (one or two sectors strong, everything else weak)
- e.g. XLK +18, rest red
- Signals: AI/tech-only rally, broad market exposed to single-theme reversal
- Action: be selective in screener; don't chase tech leaders blindly
- Doctrine echo: "five tech longs is one bet" (correlation tax)

**2. Defensive rotation** (XLP / XLU / XLV leading)
- Risk-off behavior — money fleeing cyclicals
- Often precedes broader weakness
- Action: tighten stops, lean defensive, lower portfolio heat

**3. Cyclical rotation** (XLY / XLI / XLB leading)
- Risk-on, growth-friendly environment
- Often a healthy market sign
- Action: P1 setups in cyclicals get a green light

## Hard rules

1. **No fabrication.** If yfinance returns None for a sector, that row shows `—`, not zero. Composite stays None.
2. **Manual refresh.** Cache reads automatically when fresh; pass `--refresh` to override.
3. **Composite is informational.** It's a useful summary but doesn't override per-name P1 gates. A passing P1 setup in a weak sector is still a passing setup.

## Honest limitations

1. **Sector ETF != all stocks in that sector.** XLK is mostly AAPL/MSFT/NVDA — it does not represent small-cap tech well. Use as a directional read, not a granular one.
2. **6-month window** is the longest lens; longer-term rotations (1y+) require manual review.
3. **No intra-day data.** End-of-day close prices only. Don't make timing decisions on this.
4. **yfinance fragility.** Same caveat as us-screener — Yahoo backend changes occasionally break things.

## Pairing with other skills

| Skill | Role |
|---|---|
| `us-screener` | Use sector rotation to bias which candidates you take seriously |
| `macro-rates regime` | Sector rotation is a complement, not a substitute — macro regime tells WHY, sector rotation tells WHERE |
| `dashboard` | Reads the cache and renders the heat strip on the Discovery panel |
