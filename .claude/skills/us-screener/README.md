# US Screener — User Guide

Daily discovery layer for US equities. Surfaces names that pass the Phase 1 technical filter AND meet Buffett-style quality/value thresholds, excluding anything already on your watchlist.

---

## Quick start

```bash
# Run the scan (uses cache where fresh, ~30-60s first time, faster after)
python3 .claude/skills/us-screener/screener.py

# Rebuild dashboard to see the Discovery panel update
python3 .claude/skills/dashboard/dashboard.py
```

Open the dashboard, scroll to **🔭 Discovery**. Top of the panel shows sector rotation; below it lists ranked candidates with one-click "+ Add" buttons.

---

## How candidates get tagged

Each candidate must pass the **8 P1 technical gates** (trend filter, RSI 35-50, healthy pullback, etc.) — same logic as the dashboard's per-ticker status badges. Names that pass technicals then get scored on two fundamental dimensions:

**Quality (need 4 of 5)** — is this a *good business*?
- ROE > 15% (capital efficiency)
- Gross margin > 35% (pricing power)
- Operating margin > 15% (operational quality)
- Debt/Equity < 1.5 (balance sheet)
- Revenue growth YoY > 8% (growing)

**Value (need 2 of 3)** — is it *attractively priced*?
- Trailing P/E < 25
- Forward P/E < Trailing P/E (improving)
- FCF yield > 4%

### Tags

| Tag | Meaning | Action |
|---|---|---|
| 💎 **BUFFETT** | P1 + Quality + Value | Best signal — rare. Strong candidate for the watchlist. |
| 🏆 **QUALITY** | P1 + Quality only | Great business at full price. Add to watchlist; wait for a better entry. |
| 💰 **VALUE** | P1 + Value only | Cheap, lower quality. OK as a tactical play; not a long hold. |
| ⚡ **TECH** | P1 only | Technical setup is there but neither quality nor value support it. Trade if you must, but don't fall in love. |

---

## Why you might see only a few candidates

The screener intentionally combines **strict technical filters** (RSI 35-50, all 8 P1 gates) with **strict fundamental filters** (4/5 quality, 2/3 value).

In a **CAUTIOUS** macro regime, expect 0-5 candidates from a 180-name universe.
In **NEUTRAL**, expect 5-15.
In **RISK-ON**, expect 15-30.

Zero candidates is a valid signal — it means doctrine isn't seeing a clean setup right now. The honest action is no trade, not loosening filters.

---

## Subcommands

```bash
python3 .claude/skills/us-screener/screener.py                # standard scan
python3 .claude/skills/us-screener/screener.py --refresh      # force re-fetch all
python3 .claude/skills/us-screener/screener.py --tech-only    # skip fundamentals (fast)
python3 .claude/skills/us-screener/screener.py --show         # print last cached output
```

---

## Refresh cadence (what gets re-pulled when)

| What | TTL | Why that long |
|---|---|---|
| Daily OHLCV + RSI/SMA/ATR for universe (178 names) | 24h | Technical setups change daily; one bulk yfinance call (~30-60s) covers all |
| Per-ticker fundamentals (only for P1 passers) | 7d | P/E, margins, ROE don't change daily; refreshing weekly saves rate limits |
| Sector rotation (separate skill) | 1h | ETF prices shift intra-day; fast refresh is cheap |

---

## Tuning the universe

`.claude/skills/us-screener/universe.json` is a plain JSON file grouped by sector. Edit it freely:

- **Add** a name: append the ticker symbol to the appropriate sector array
- **Remove** a name: delete the line
- **Reorganize** sectors: keep the 11 SPDR sector buckets so sector-rotation alignment stays clean

After editing, run `--refresh` to repopulate caches with the new universe.

---

## Tuning the gate thresholds

The Q+V thresholds live as inline constants in `screener.py`. Search for `eval_quality()` and `eval_value()` and edit the numbers. Common adjustments:

- **Too few 💎 BUFFETT** results? Lower Quality to 3/5 OR Value to 1/3, OR raise the absolute P/E ceiling above 25.
- **Too many low-conviction passes**? Tighten ROE >20%, gross margin >40%, FCF yield >5%.
- **Sector-specific tuning**: tech names often pass quality easily, financials often pass value easily. Don't over-tune — the universal thresholds are deliberately blunt so a high score means something.

---

## Common issues

| Symptom | Cause | Fix |
|---|---|---|
| "possibly delisted" warnings | Tickers in `universe.json` got renamed (SQ → XYZ, HES → CVX) | Edit `universe.json` to remove or rename |
| 0 candidates after a scan | Strict gates + tough regime — usually correct | Check sector rotation; if everything's red, no trade is the answer |
| `--show` returns empty | Cache not populated yet | Run without `--show` first |
| `data error` on many tickers | yfinance backend broke (Yahoo changes API periodically) | Wait a day, try `--refresh`; longer-term: switch to FMP |
| Fundamentals stale despite refresh | 7d TTL still valid; use `--refresh` to override | `python3 screener.py --refresh` |

---

## How it integrates with the rest of the app

```
┌─────────────────────┐     ┌─────────────────────┐
│ sector-rotation     │ ──▶ │   Discovery panel   │
│ (11 SPDR ETFs)      │     │   on dashboard.html │
└─────────────────────┘     │                     │
                            │  sector heatmap     │
┌─────────────────────┐     │      +              │
│ us-screener         │ ──▶ │  candidate table    │
│ (this skill)        │     │      +              │
└─────────────────────┘     │  + Add buttons      │
                            └──────────┬──────────┘
                                       │ clicking + Add copies:
                                       ▼
                            python3 wl.py add TICKER --thesis "…"
                            (paste in terminal → ticker on watchlist)
                                       │
                                       ▼
                            Now appears in US grid + Risk Sim dropdown
```

---

## Honest limitations

1. **yfinance fundamentals can lag or break.** When Yahoo changes their backend, expect a wave of `data error` entries for a few days. FMP is the planned upgrade path if reliability becomes painful.
2. **ROE distortion** on heavy-buyback names (AAPL, MSFT often show 100%+ ROE because equity base shrank from buybacks). Not a bug — known artifact.
3. **No DCF / intrinsic value**. Value gates are blunt thresholds, not full-blown valuation models. Doctrine §1 (no fabrication) means we won't bake in growth-rate assumptions.
4. **Universe is curated, not exhaustive.** ~180 names misses thousands of investable US equities. Add names you specifically care about to `universe.json`.
5. **Forward P/E is sell-side optimism.** Use the "forward < trailing" gate as supporting evidence, not definitive.

---

## TL;DR

- Run `screener.py` daily (or before any new-trade decision)
- Rebuild dashboard
- Read the Discovery panel — fresh candidates appear at the top
- Click + Add to pipe into the watchlist
- Combine with `sector-rotation` to see WHERE money is flowing
- Manual by design — you decide when fresh data flows
