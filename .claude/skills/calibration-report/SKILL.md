---
name: calibration-report
description: Buckets CLOSED journal entries' realized R by the gate state captured at entry (RSI band, sentiment flag, RS-vs-SPY leader/laggard, sector, structural-quality flags) so the operator can see which entry conditions actually produce edge, not just an aggregate win-rate/expectancy number. Read-only analysis over the journal; never mutates it. Use whenever asked "what's working" / "should I trust RSI-oversold entries" / "am I overweight one sector's wins."
---

# calibration-report — outcome engine (Analysis C1)

Aggregate expectancy (`portfolio.py expectancy`) answers "am I net positive."
This answers "**why**" — which entry conditions the wins/losses cluster
around — so the 20-trade Phase-2 calibration gate means something more than
a raw count.

## Usage

```bash
python3 .claude/skills/calibration-report/calibration_report.py report          # human-readable
python3 .claude/skills/calibration-report/calibration_report.py report --json    # machine-readable
```

Read-only, no config, no cron — run it whenever you want a cut of closed-trade
outcomes by entry context.

## What it does

For every CLOSED journal entry with a realized R-multiple, reads the entry's
`### Data snapshot` table (RSI, sector, sentiment flag, RS vs SPY 1m) and
`### Structural risk flags` section, then buckets win-rate/avg-R/sum-R by:

- **RSI band at entry** (`<30`, `30-50`, `50-70`, `>=70`)
- **Sentiment flag at entry** (FADE / BUY / unknown)
- **RS vs SPY (1m) at entry** (leader / laggard / flat / unknown)
- **Sector**
- **Structural-quality flags at entry** (has flags / clean)

Buckets with `n < 3` are printed but marked low-confidence — directional
only, never hidden (same warn-loudly-never-block spirit as `quality_flags.py`).

## Data-capture dependency

Sector / sentiment flag / RS-vs-SPY are only recorded in prospectuses created
via `j.py new` **after 2026-07-02** (when `--sector`/`--sentiment-flag`/`--rs-1m`
were added, threaded from the Risk Simulator's already-computed sim values —
no extra fetch). Closed trades from before that date show `unknown` for those
three dimensions; RSI band and structural-quality flags were captured earlier
and work for all closed trades.

## See also

- `dashboard/portfolio.py` — `closed_trades()` / `expectancy()`, the source list this reads
- `journal/j.py` — writes the Data snapshot table this reads
- Doctrine §9 — win/loss classification (and therefore realized R) is always a human call at `j.py close`, never inferred
