---
name: macro-calendar
description: US scheduled-macro-event calendar (FOMC, CPI, NFP/Employment Situation, PCE) with §5 halt-window enforcement. Returns the next event of each type with hours-until, lists upcoming events in any window, and checks whether a specific entry time falls inside a 12h or 24h halt window. REQUIRED before any new US-equity or US-options directional entry, per AGENTS.md §5: "12h before FOMC / CPI / NFP". Without this skill, the §5 halt rule is unenforceable and the doctrine is unverified.
---

# US Macro Calendar Skill (FOMC / CPI / NFP / PCE)

## When to use

Trigger this skill **as a mandatory gate before every US-equity or US-options recommendation**, alongside the per-name earnings check. Specifically:

- **At every pre-trade gate**: run `check` on the planned entry time (now or scheduled).
- **At daily review**: run `next` to see what macro events are imminent across all types.
- **At watchlist planning**: run `list --days 30` to see all scheduled events in the next month, so trade planning can route around them.

Do NOT use this skill for:
- KLSE-specific macro (Bank Negara Malaysia rate decisions — different calendar, not covered).
- Earnings dates — that's `us-fundamentals earnings` for single-name event risk.
- Crypto-specific event halts — token unlocks live in `crypto-unlocks`.

## Why this exists

AGENTS.md §5 states unambiguously: **"Macro: 12h before FOMC / CPI / NFP"** — no new directional exposure within that window. The skill turns that rule from doctrine decoration into enforced behavior. Without it, every trade implicitly assumed "no macro event imminent," and recent history (Apr 2024 CPI shock, Jun 2024 surprise NFP) shows that's a real and unmodeled loss generator.

The §5 rule says 12h. This skill defaults to 12h but exposes a `--window-hours` flag (use 24h for the conservative-aggression profile per AGENTS.md USER CONFIG, or for trades with high macro sensitivity like long-duration / RGLD-type names).

## Source

**Static maintained catalog** in `schedule.json`. Each entry has type, date (YYYY-MM-DD), time_et (HH:MM, US Eastern), and a note. The catalog covers the next 6–12 months of FOMC / CPI / NFP / PCE releases, sourced from the official issuers:

| Event | Official source |
|---|---|
| FOMC | https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm |
| CPI | https://www.bls.gov/schedule/news_release/cpi.htm |
| Employment Situation (NFP) | https://www.bls.gov/schedule/news_release/empsit.htm |
| PCE | https://www.bea.gov/news/schedule |

The catalog has a `verified_through` date in its `_meta` block. The script auto-warns when < 60 days remain.

**Why static vs. scraped:**
- These schedules are published ~1 year in advance and change rarely.
- Scraping fragility (HTML changes, rate limits, paywalls) is not worth it for slow-moving data.
- Static dates are deterministic and inspectable — you can `cat schedule.json` and verify by eye.
- The script's runtime sanity check (e.g., NFP must fall on Friday) catches catalog entry errors automatically.

**Maintenance discipline:**
- Re-verify the catalog quarterly against the four official sources.
- Update `_meta.verified_through` and `_meta.last_updated` when refreshing.
- If a release date moves (rare — usually only for holidays), update immediately and note in the journal.

## Subcommands

### `next` — next event of each type

```
python3 .claude/skills/macro-calendar/macro_cal.py next
python3 .claude/skills/macro-calendar/macro_cal.py next --window-hours 24
```

Shows the next FOMC, CPI, PCE, and NFP with date, ET time, hours-until, and a halt-window flag (🛑 YES / ok). Use `--window-hours 24` for the more conservative gate.

### `list` — events in the next N days

```
python3 .claude/skills/macro-calendar/macro_cal.py list --days 14
python3 .claude/skills/macro-calendar/macro_cal.py list --days 30
```

Useful for trade-planning: route entries around the macro calendar.

### `check` — is a specific time inside any halt window?

```
python3 .claude/skills/macro-calendar/macro_cal.py check                                  # check now
python3 .claude/skills/macro-calendar/macro_cal.py check --at "2026-06-09 18:00 ET"       # check scheduled entry
python3 .claude/skills/macro-calendar/macro_cal.py check --at "2026-06-17 09:00 ET"       # FOMC day at 9 AM
python3 .claude/skills/macro-calendar/macro_cal.py check --window-hours 24                # stricter window
```

Returns one of:
- `✓ NOT in halt window` + the next event for context — entry permitted.
- `🛑 IN HALT WINDOW` + which event(s) and how soon — entry forbidden under §5.

Time formats accepted: `YYYY-MM-DD HH:MM` (interpreted as ET by default), `YYYY-MM-DD HH:MM ET`, `YYYY-MM-DD HH:MM UTC`, or `YYYY-MM-DDTHH:MMZ`.

## Hard rules

1. **The 12h §5 halt is non-negotiable for new directional exposure.** If `check` returns 🛑 IN HALT WINDOW, the recommendation is **NO-TRADE**. No exceptions on spot equity. Defined-risk options where the event IS the thesis are allowed at Phase 3 only — but currently DARK in Phase 1.

2. **`check` runs at the PLANNED entry time, not at recommendation time.** If you draft a recommendation Monday but the trigger fires Friday, the relevant check is Friday's entry time vs the macro calendar. Always specify `--at` for scheduled trades.

3. **Catalog freshness matters.** If `_meta.verified_through` is < 60 days away, the script warns. Refresh from the four official sources before relying on the calendar.

4. **The 24h window option exists for a reason.** Use it when:
   - The trade is in a duration-sensitive name (gold, REITs, long-tenor growth).
   - The trade is in a sector with strong known macro sensitivity (banks, semis, biotech).
   - Aggression profile is "Conservative."
   - You'd be embarrassed if a CPI surprise stopped you out 4 hours after entry.

5. **PCE is included even though §5 mentions only FOMC/CPI/NFP.** PCE is the Fed's preferred inflation gauge and moves markets nearly as much as CPI. Treating it the same way is conservative and aligned with §5's intent.

6. **The script does NOT cover non-US releases** (ECB, BOJ, BOE, China data). Add them later as a separate `macro-calendar-intl` skill if/when international exposure matters.

## Integration with the pre-trade workflow

For any new US-equity recommendation, the macro gate sits between the regime read and the doctrine gate:

1. `macro-rates regime` → top-down regime (RISK-ON / OFF / NEUTRAL).
2. **`macro-calendar check --at "<planned entry time>"`** → halt-window gate (THIS SKILL).
3. Massive aggregates + indicators → bottom-up technicals.
4. `us-fundamentals fundamentals` → valuation, growth, quality.
5. `us-fundamentals earnings` → single-name earnings halt.
6. `us-news` → sentiment + catalysts.
7. Confluence verdict per §4.
8. Doctrine gate per §7 — including macro tilt and event halt verdicts.

If step 2 returns 🛑, stop — do not proceed to steps 3–8 for this entry time. Re-run with a different entry time outside the window.

## What this skill does NOT cover

- **Non-US central banks** (ECB, BOJ, BOE, RBA). Different calendars.
- **Non-headline US releases** (Retail Sales, ISM, Consumer Confidence, GDP). Add to schedule if they matter for your trades.
- **Fed speaker calendar** (Powell remarks, Beige Book). Sometimes market-moving but not binary like the four events above.
- **Treasury auctions** (2y/5y/7y/10y/30y issuance). Real but secondary to the four covered events.
- **Earnings season aggregate** (single-name dates are in `us-fundamentals earnings`).
- **Crypto-specific halts** — `crypto-unlocks` for token unlocks; nothing comparable to FOMC for crypto natively, but Fed events still affect crypto via real-yields/DXY transmission.
