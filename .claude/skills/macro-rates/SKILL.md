---
name: macro-rates
description: Fetch real, timestamped US macro data via FRED (Federal Reserve Bank of St. Louis) — Fed funds rate, 2y/10y/30y Treasury yields, yield-curve spreads (10y-2y, 10y-3m), 10y TIPS real yield, 10y breakeven inflation, headline + Core CPI, headline + Core PCE, unemployment rate, monthly NFP delta, trade-weighted USD index, VIX. Returns a one-shot macro snapshot, individual series lookups, or a composite regime read (RISK-ON / RISK-OFF / NEUTRAL / mixed). Use whenever a recommendation needs macro context — rate regime, inflation trajectory, dollar trend, vol regime — or before any directional trade as a top-down sanity check on the single-name confluence.
---

# Macro Rates Skill (FRED)

## When to use

Trigger this skill when a recommendation, watchlist sweep, or daily review needs:

- **Rate regime** — what is the Fed funds rate, where are 2y/10y/30y, is the curve inverted?
- **Real yields + inflation expectations** — TIPS yield and 10y breakeven (the BTC/gold/duration sensitivity inputs).
- **Inflation trajectory** — most recent CPI and PCE prints (headline + core), MoM and YoY.
- **Labor** — unemployment rate, last NFP delta.
- **Dollar trend** — 30d move on the broad trade-weighted USD (EM/crypto/gold headwind/tailwind).
- **Vol regime** — VIX level (option premium rich/cheap; equity risk-on/off).
- **Composite regime read** — one-line verdict that should bias every recommendation per AGENTS.md §4.

Recommended cadence:
- **Daily** before opening any new position (`snapshot` once).
- **At every CPI/PCE print** (~mid-month) — `series` lookup on the specific release.
- **At every FOMC** — `series` lookup on DFF before/after; verify the move was priced in.
- **Whenever a recommendation cites duration sensitivity** (RGLD, treasury, long-tenor growth) — `series` on DGS10 + DFII10.

Do NOT use for non-US macro (BNM, ECB, BOJ). Different sources needed for those.

## Why this exists

AGENTS.md §4 specifies confluence across {technicals + sentiment OR fundamentals OR flow}, but the doctrine also assumes regime-awareness: e.g., §5 says "12h before FOMC/CPI/NFP" no new exposure on macro names. Without a macro feed, regime context is unverified — every recommendation is implicitly assuming "macro is fine." This skill makes the macro state observable.

It also makes the doctrine's risk-on/off bias explicit. The `regime` subcommand outputs a composite read that should adjust position sizing and conviction in every recommendation downstream.

## Setup — one-time

1. **Get a free FRED API key** (instant, no credit card, no email verification beyond initial):
   👉 https://fredaccount.stlouisfed.org/apikeys

2. **Save it** to `.claude/skills/macro-rates/.env`:
   ```
   FRED_API_KEY=your-key-here
   ```
   The script auto-loads `.env` on each call. The `.env` is gitignored at the project root.

3. **Verify:**
   ```bash
   python3 .claude/skills/macro-rates/fred.py snapshot
   ```
   You should see rates, curve, inflation, NFP, DXY, VIX, with timestamps.

FRED is generous on rate limits — you can hammer it. No daily-call budget concern.

## Subcommands

### `snapshot` — one-shot macro dashboard

```
python3 .claude/skills/macro-rates/fred.py snapshot
```

Returns sections:
- **Rates & curve**: Fed Funds, 2y/10y/30y, 10y-2y and 10y-3m spreads with INVERTED/NORMAL tags.
- **Real yields & inflation expectations**: 10y TIPS, 10y breakeven, with a headwind/tailwind interpretation for duration assets.
- **Inflation**: CPI All Urban, Core CPI, PCE, Core PCE — MoM and YoY for each.
- **Labor**: Unemployment rate, last NFP delta.
- **Dollar & vol**: Trade-weighted USD (broad) with 30d change, VIX with regime tag.

### `series` — single series with recent observations

```
python3 .claude/skills/macro-rates/fred.py series --id DGS10 --limit 30
python3 .claude/skills/macro-rates/fred.py series --id CPILFESL --limit 24
python3 .claude/skills/macro-rates/fred.py series --id VIXCLS --limit 60
```

Useful FRED series IDs:

| ID | Series | Cadence |
|---|---|---|
| `DFF` | Federal Funds Effective Rate | daily |
| `DGS2` / `DGS10` / `DGS30` | 2y / 10y / 30y Treasury | daily |
| `T10Y2Y` | 10y minus 2y spread | daily |
| `T10Y3M` | 10y minus 3m spread (Fed's recession signal) | daily |
| `DFII10` | 10y TIPS yield (real) | daily |
| `T10YIE` | 10y breakeven inflation | daily |
| `CPIAUCSL` | CPI All Urban (headline) | monthly |
| `CPILFESL` | Core CPI | monthly |
| `PCEPI` | PCE Price Index | monthly |
| `PCEPILFE` | Core PCE (Fed's preferred) | monthly |
| `UNRATE` | Unemployment Rate | monthly |
| `PAYEMS` | Total Nonfarm Payrolls (NFP) | monthly |
| `DTWEXBGS` | Trade-weighted USD (broad) | daily |
| `VIXCLS` | VIX close | daily |

For arbitrary FRED IDs (there are >800k series), just pass the ID. The catalog above is the curated decision-relevant subset.

### `regime` — composite regime read

```
python3 .claude/skills/macro-rates/fred.py regime
```

Combines: yield-curve shape, real yield level and 30d trend, Core CPI YoY, broad USD 30d trend, VIX level. Each signal carries a weighted sign; the composite produces one of:

- **RISK-ON tailwind** (score ≥ +1.5) → standard sizing OK; high-beta names viable.
- **CONSTRUCTIVE — mixed with bullish lean** (+0.5 to +1.5) → moderate tailwind.
- **NEUTRAL — no clear regime** (−0.5 to +0.5) → confluence must stand on its own.
- **CAUTIOUS — mixed with bearish lean** (−0.5 to −1.5) → consider tighter R:R, smaller sizes.
- **RISK-OFF headwind** (≤ −1.5) → bias defensive; avoid high-beta; tighten R:R floors.

The `regime` output should be cited in every recommendation's `DATA SNAPSHOT` block. A trade entered against the regime requires explicit acknowledgement in the `CASE AGAINST`.

## How to apply the regime read

| Regime | Position sizing | R:R floor | Asset bias | New entries gate |
|---|---|---|---|---|
| RISK-OFF | Cut by 50% | 2R+ | Defensive only (RGLD-type, low-beta) | Skip marginal setups |
| CAUTIOUS | Standard | 2R+ | Mixed, no high-beta | Confluence must be airtight |
| NEUTRAL | Standard | 1.5R | No bias | Standard doctrine |
| CONSTRUCTIVE | Standard | 1.5R | Mild risk-on lean | Standard doctrine |
| RISK-ON | Standard or +25% | 1.5R | Growth / beta OK | Standard doctrine |

These adjustments are MULTIPLICATIVE with single-name conviction. Macro tailwind does not justify entering a broken setup; macro headwind does not justify skipping a perfect one — it just nudges the size and selectivity.

## Hard rules

1. **If FETCH FAILED, regime context is unavailable.** Every downstream recommendation must explicitly note "macro context unverified — proceeding without regime adjustment" and lower conviction one level.

2. **Inflation and labor data lag.** CPI prints ~2 weeks after the reference month; NFP ~1 week after. The "as of" date in the output is the reference month, not the release date. Don't treat last month's CPI as "current."

3. **Don't compound regime signals.** If `regime` is RISK-OFF and you cut size 50%, do NOT also cut from 2% to 1% per-trade — that's double-counting. Pick one adjustment lever, not both.

4. **Macro can be wrong about you.** A RISK-OFF regime doesn't mean every long fails. Single-name idiosyncratic edge can dominate macro on a 4-8 week swing horizon. Use regime as a tilt, not a veto, unless the headwind is extreme.

5. **The `T10Y3M` inverted spread is the Fed's best recession signal**, but the lag from inversion to recession averages 18 months. Don't treat inversion as "sell everything." Treat it as "shift gradually toward quality and defensives over months."

## Combined-skill recipe (updated workflow)

For any new US-equity recommendation:

1. **`macro-rates regime`** → top-down context (THIS SKILL). Note regime in DATA SNAPSHOT.
2. Massive aggregates + indicators → bottom-up technicals.
3. `us-fundamentals fundamentals` → valuation, quality, growth.
4. `us-fundamentals earnings` → next earnings + halt-window gate.
5. `us-news` → sentiment + catalysts.
6. Confluence verdict per §4, adjusted per regime per the table above.
7. Doctrine gate per §7 — including macro-tilted sizing.
8. Output with macro `Fetched (UTC)` in the snapshot.

For crypto: same recipe, plus macro context matters MORE because real yields and DXY directly drive BTC. Always run `regime` before any crypto entry.

For KLSE: macro context partially applies (USD trend affects emerging Asia flows), but the BNM/MYR local macro is the bigger driver and is NOT in this skill — flag as "US macro context only; local KLSE macro unverified."

## What this skill does NOT cover

- **Non-US macro** (BNM, ECB, BOJ, PBOC). Different sources needed.
- **Scheduled-event calendar** (next FOMC date, CPI release date, NFP release date). The §5 12h-halt rule still needs the `macro-calendar` skill (next on the build list).
- **High-frequency moves intra-CPI / intra-FOMC**. FRED publishes after the fact, not in real-time. For the moment of the print, use a live news/data terminal.
- **Specific Fed speaker remarks / forward guidance text**. News-driven; not in FRED.
- **Forward expectations** (Fed funds futures, OIS curve). Different feed (CME / BFV).
