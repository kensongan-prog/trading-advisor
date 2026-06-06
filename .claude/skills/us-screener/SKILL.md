---
name: us-screener
description: Discovery layer for US equities. Runs the 8 Phase 1 technical gates (trend filter, RSI 35-50, SMA20 tag, volume profile, etc.) across a curated ~180-name universe and layers Buffett-style quality+value filters on top. Outputs ranked candidate list of names that pass P1 AND meet quality/value thresholds, excluding watchlist names. Tags each candidate 💎 BUFFETT / 🏆 QUALITY / 💰 VALUE / ⚡ TECH. Cached output read by the dashboard's Discovery panel. Manual by design — no cron.
---

# US Screener Skill

## When to use

- "Run the screener" / "Find candidates" / "What's setting up?"
- Weekly or daily morning routine to surface new names matching doctrine
- Before adding any new US name to watchlist — verify it passes P1 + has reasonable quality/value
- "Show me Buffett candidates" / "Anything cheap and trending?"

Do NOT use for:
- Crypto discovery (use `crypto-coingecko` + future crypto-screener)
- KLSE discovery (no equivalent yet — small market, manual curation works)
- Existing watchlist analysis (use dashboard's per-ticker grids)

## Why this exists

The app was strong on analysis but weak on discovery. Manually scanning hundreds of names for P1 setups is a poor use of time. This skill automates the universe scan and only surfaces names that:

1. Pass all 8 P1 technical gates (same logic as `us_status()` in dashboard.py)
2. Aren't already on the watchlist (no noise on names you already track)
3. Carry a Buffett tag showing whether they're quality compounders, value plays, or technical-only

The output answers: "Which names should I consider adding to my watchlist today?"

## Universe

Hardcoded JSON at `.claude/skills/us-screener/universe.json` — ~180 liquid US names across all 11 sectors. Curated, not the full Russell 1000, because:
- Smaller universe = faster scans (~30-60s instead of 5+ minutes)
- Liquidity-filtered (no microcaps where the doctrine doesn't fit)
- Editable: add names you'd consider trading, remove ones you wouldn't

Refresh cadence: edit the JSON when new megacaps emerge (IPOs that prove themselves) or old names get delisted.

## Gate logic

### Technical (must pass ALL — same as us_status())

1. price > SMA50 > SMA200 (trend filter)
2. SMA200 exists (not too new)
3. RSI ∈ [35, 50] (P1 entry zone — cooled but not broken)
4. |today's change| ≤ 5% (not violent)
5. SMA50 slope ≥ -0.5%/5d (not rolling over)
6. 5d/30d volume ratio ≤ 1.3 (no distribution)
7. price within -5% to +10% of SMA20 (clean pullback shape)
8. (Earnings/macro halt gates are entry-specific and skipped here — sim checks at trade time)

### Quality (need 4 of 5 — Buffett-style)

- ROE > 15% (capital efficiency)
- Gross margin > 35% (pricing power)
- Operating margin > 15% (operational quality)
- Debt/Equity < 150 (balance sheet — yfinance reports as %-style, 150 ≈ 1.5×)
- Revenue growth YoY > 8% (growing, not stagnant)

### Value (need 2 of 3)

- Trailing P/E < 25 (not richly priced)
- Forward P/E < Trailing P/E (cheaper looking forward)
- FCF yield > 4% (FCF / market cap — actual cash return)

### Tag composition

- Pass P1 + 4/5 Quality + 2/3 Value → **💎 BUFFETT** (best signal — rare in any regime)
- Pass P1 + 4/5 Quality only → **🏆 QUALITY** (good business, currently expensive)
- Pass P1 + 2/3 Value only → **💰 VALUE** (cheap, lower quality)
- Pass P1 only → **⚡ TECH** (technically set up, doesn't earn fundamental conviction)

## Usage

```bash
# Standard daily run — uses cache where fresh (24h tech, 7d fund)
python3 .claude/skills/us-screener/screener.py

# Force re-fetch everything (use if data feels stale)
python3 .claude/skills/us-screener/screener.py --refresh

# Skip fundamentals (faster, technical-only output)
python3 .claude/skills/us-screener/screener.py --tech-only

# Just print last cached output without re-running
python3 .claude/skills/us-screener/screener.py --show

# Then rebuild dashboard so the Discovery panel reads the new cache
python3 .claude/skills/dashboard/dashboard.py
```

## Caches

| File | TTL | Purpose |
|---|---|---|
| `.claude/cache/screener/technicals.json` | 24h | Per-ticker price + RSI + SMAs + ATR + volume + slope |
| `.claude/cache/screener/fundamentals.json` | 7d | Per-ticker P/E, ROE, margins, FCF, debt — only fetched for P1 passers |
| `.claude/cache/screener/candidates.json` | (output) | Ranked candidate list dashboard reads |

## Hard rules

1. **No fabrication.** If yfinance returns None for a metric, that gate counts as fail — never assume.
2. **P1 passers only get fundamentals.** Saves rate limits and avoids spending budget on names that aren't candidates anyway.
3. **Already-on-watchlist filter.** Output sorts watchlist names LAST, fresh discoveries first.
4. **Universe is editable** — `.claude/skills/us-screener/universe.json`. Add/remove freely.
5. **Manual refresh.** No cron. You decide when fresh data flows.

## Honest limitations

1. **yfinance is fragile.** Yahoo changes their backend periodically and breaks fundamentals. If a wave of "data error" entries appears, that's likely the cause. FMP is the long-term upgrade path.
2. **ROE distortion on heavy-buyback names** (e.g. AAPL shows 141% ROE because equity base shrank). The quality filter accepts this; it's a known yfinance artifact, not a bug.
3. **No DCF / intrinsic value.** Value gates are relative + absolute thresholds, never DCF — doctrine §1 (no fabrication) means we can't bake in growth assumptions.
4. **Forward P/E < Trailing P/E** is a weak signal — sell-side estimates are often optimistic. Treat as supporting evidence, not definitive.
5. **Universe excludes** small-caps, ADRs (beyond a few), pre-IPO, and anything you wouldn't trade with $20k account size. By design.
6. **Dead tickers** silently fail (e.g. SQ→XYZ after rename). Periodically audit the universe.

## Pairing with other skills

| Skill | Role |
|---|---|
| `sector-rotation` | Tells you WHERE money is flowing — focus screener attention on leading sectors |
| `watchlist` | Add a candidate to the active watchlist (Discovery panel surfaces the command) |
| `us-fundamentals` | Deeper per-ticker dive once a candidate makes the cut |
| `us-news` | Sentiment + catalyst check before sizing |
| `dashboard` | Reads the candidates cache, renders the Discovery panel |

## Typical workflow

```bash
# Morning routine
python3 .claude/skills/sector-rotation/sector_rotation.py    # which sectors are leading?
python3 .claude/skills/us-screener/screener.py               # which names pass P1 + Q+V?
python3 .claude/skills/dashboard/dashboard.py                # rebuild dashboard

# Open dashboard, scroll to 🔭 Discovery panel
# Pick a 💎 BUFFETT or 🏆 QUALITY candidate
# Click "+ Add" to copy watchlist command, paste in terminal
# Now the candidate is on the watchlist — run Risk Sim when ready to size
```
