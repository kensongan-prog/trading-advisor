---
name: klse-announcements
description: Manually refresh klsescreener.com Bursa announcements (Financial Results filings, Entitlements/dividends, AGMs/EGMs, Capital Changes, Shareholding changes) for KLSE tickers into a local JSON cache that the dashboard reads. Use when the user wants a real earnings/announcement halt check on KLSE names — the Risk Simulator's KLSE earnings gate consumes this cache. Uses urllib + regex (no WebFetch) so it's runnable from any Python context. Manual by design — no automation, no cron.
---

# KLSE Announcements Refresh Skill

## When to use

Trigger this skill when:

- The user wants the Risk Simulator's KLSE earnings gate to use real data (rather than the manual-check warning)
- "Refresh KLSE announcements"
- "Pull Bursa announcements for 1155 / 7241"
- Before sizing a KLSE trade where Q-results / ex-div / AGM proximity matters
- Audit: "Show me KLSE announcement cache"

Do NOT use for:
- News headlines (different feed: `klse-news` skill via WebFetch)
- Per-ticker fundamentals (use `klse-refresh`)

## Why this exists

The original `klse-news` skill fetches Bursa announcements via WebFetch — fine for in-conversation single-ticker analysis, but unusable from a Python script. The Risk Simulator's KLSE earnings gate previously had to warn "manual check needed" because Python couldn't fetch this data.

This script fixes that: direct HTTP + regex parsing of klsescreener's announcements page. Output lands in `.claude/cache/klse_announcements/{code}.json`, which the dashboard reads on build so the simulator can run a real halt-window check.

Manual by design — no cron, no scheduled refresh.

## What gets cached per ticker

```json
{
  "bursa_code": "4057",
  "stock_name": "ASIAN PAC HOLDINGS BERHAD",
  "announcements": [
    {"date": "2026-05-28", "category_code": "FA", "category": "Financial Results",
     "title": "Quarterly rpt on consolidated results for the financial period ended 31/03/2026",
     "time_of_day": "1:19 pm"},
    ...
  ],
  "most_recent_financial_results": {
    "filed_date": "2026-05-28",
    "title": "Quarterly rpt ... 31/03/2026",
    "period_end": "2026-03-31",
    "next_expected_period_end": "2026-06-30",
    "next_expected_filing_by": "2026-08-29"
  },
  "upcoming_events": [
    {"type": "ex_dividend", "date": "2026-08-12", "title": "...", "filed_on": "2026-07-15"},
    {"type": "agm", "date": "2026-05-27", "title": "...", "filed_on": "2026-04-15"}
  ],
  "_fetched_at": "2026-06-04T15:15:46+00:00"
}
```

The `next_expected_filing_by` field is derived: most recent period_end + 60 days (Bursa's mandated filing deadline).

## Usage

```bash
# Refresh every KLSE code in watchlist.md
python3 .claude/skills/klse-announcements/klse_announcements.py

# Specific codes
python3 .claude/skills/klse-announcements/klse_announcements.py 1155 7241

# Read-only view
python3 .claude/skills/klse-announcements/klse_announcements.py --show

# Wipe cache
python3 .claude/skills/klse-announcements/klse_announcements.py --clear

# Politeness delay (default 1.0s between requests)
python3 .claude/skills/klse-announcements/klse_announcements.py --delay 0.5
```

## Hard rules

1. **No fabrication.** If the fetch fails, the cache entry records the error + timestamp; the dashboard's simulator surfaces "Q-results filing window: refresh required" rather than silently using stale or invented data.
2. **Politeness delay 1.0s default.** klsescreener hosts a free service. Don't hammer.
3. **Manual refresh.** The cache is the user's responsibility — the dashboard never auto-fetches.
4. **The derived `next_expected_filing_by` is the Bursa-mandated worst case.** Companies often file 1-3 weeks before the deadline. The simulator treats:
   - within 7 trading days of the deadline → halt
   - within 14 trading days → warning ("filing could come early — re-check")
   - otherwise → clear
5. **Upcoming-event parsing is best-effort.** Title formats vary; the parser extracts ex-dividend / AGM / EGM dates when they appear in standard phrasing. Absence of an upcoming event in the cache does NOT guarantee none exists — the regex may have missed an unusual title. For high-conviction trades, supplement with the `klse-news` WebFetch skill.

## Dashboard integration

The Risk Simulator's KLSE earnings gate (previously a warning saying "manual check needed") now does a real check:

- Hard gate (**bad**) if the deadline is within ~7 trading days
- Warning if within ~14 days (filing could come early)
- Pass if more than 20 days out
- Separate **Upcoming corporate event** gate for ex-div / AGM / EGM:
  - within 7 days → halt
  - within 30 days → warning

The KLSE panel header on the dashboard also surfaces how many announcement caches exist and how old the oldest is.

## What this skill does NOT cover

- **News headlines** — use `klse-news` (WebFetch)
- **Per-ticker fundamentals** (P/E, P/B, ROE, NTA) — use `klse-refresh`
- **Real-time intraday updates** — Bursa announcements refresh once or twice a day
- **Bursa-wide event calendar** — only per-ticker filings here, not market-wide

## Maintenance

The regex parser keys on klsescreener's announcement card structure:
- `<a class="announcement-item">` wrapper
- `<div class="date-box">` with `<span class="day">` + `<span class="month">`
- `<span class="category-tag cat-XX">` for the type
- `<div class="title">` for the headline

If klsescreener restructures, update `ITEM_RE`, `DAY_RE`, `MON_RE`, `CAT_RE`, `TITLE_RE` in `klse_announcements.py`. The `parse_page()` function also extracts forward-looking dates from titles via `ex_re` and `agm_re` — those may need updating if Bursa changes title conventions.
