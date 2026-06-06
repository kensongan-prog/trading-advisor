# KLSE Announcements Refresh — User Guide

Manual refresh of klsescreener.com Bursa announcements for your KLSE watchlist tickers. Pulls recent filings (Financial Results, dividends, AGMs, EGMs, capital changes, shareholding changes) and derives the next-expected Q-results filing date for the Risk Simulator's earnings gate.

---

## Quick start

```bash
# Refresh every KLSE code in your watchlist
python3 .claude/skills/klse-announcements/klse_announcements.py

# Specific codes
python3 .claude/skills/klse-announcements/klse_announcements.py 1155 7241

# See what's cached without re-fetching
python3 .claude/skills/klse-announcements/klse_announcements.py --show

# Wipe cache
python3 .claude/skills/klse-announcements/klse_announcements.py --clear
```

Then rebuild the dashboard so the Risk Simulator picks up the new cache:

```bash
python3 .claude/skills/dashboard/dashboard.py
```

---

## Why this exists

The Risk Simulator's KLSE earnings gate used to read:

> ⚠️ KLSE Bursa announcements not in cache — run `klse-news` skill manually

That was honest but inconvenient. `klse-news` uses WebFetch (agent-only), so the dashboard couldn't auto-call it. This script bridges the gap with direct HTTP scraping, cached to JSON files the dashboard reads.

Now the same gate reads something concrete like:

> ✅ Q-results filing window: next deadline in 86d (2026-08-29) — clear

or, when close:

> 🛑 Q-results filing window: next deadline in 6d (2026-06-10) — inside the 7 trading-day pre-window. Filing could land any day.

---

## What gets cached per ticker

For each Bursa code, a JSON file at `.claude/cache/klse_announcements/{code}.json` contains:

| Field | What it means |
|---|---|
| `announcements` | Up to ~30 most recent filings with date, category, title |
| `most_recent_financial_results.filed_date` | When the last quarterly report was filed |
| `most_recent_financial_results.period_end` | Which quarter it covered |
| `most_recent_financial_results.next_expected_period_end` | The following quarter end |
| `most_recent_financial_results.next_expected_filing_by` | Bursa's filing deadline (60 days after quarter end) |
| `upcoming_events` | Forward-looking ex-div / AGM / EGM dates parsed from titles |

---

## How the simulator uses it

The Risk Simulator's KLSE gates now do real checks instead of warning:

**Q-results filing window** (derived from the 60-day Bursa deadline):
- within 7 trading days of deadline → 🛑 **halt new exposure**
- within ~14 trading days → ⚠️ warning ("filing often comes 7-14d before deadline — re-check")
- > 20 days → ✅ clear

**Upcoming corporate event** (from parsed entitlement / meeting titles):
- ex-div / AGM / EGM within 7 days → 🛑 halt (dividend price gap risk)
- within 30 days → ⚠️ warning (outside halt window but inside trade duration)
- otherwise → ✅ clear

---

## Example session

```
$ python3 .claude/skills/klse-announcements/klse_announcements.py 1155
Refreshing announcements for 1 ticker(s): 1155
Source: klsescreener.com  |  delay between requests: 1.0s

[1/1] 1155  …  ✓ MALAYAN BANKING BERHAD    30 announcements  · next FR by 2026-08-29  · 0 upcoming events

✓ Done.  1 ok, 0 failed.  Cache: .claude/cache/klse_announcements
```

```
$ python3 .claude/skills/klse-announcements/klse_announcements.py --show 1155

1155 MALAYAN BANKING BERHAD  (cached 2026-06-04T15:15:56+00:00)
  Most recent Financial Results: 2026-05-28 (period ended 2026-03-31)
  Next expected filing by:       2026-08-29 (next period end 2026-06-30)
  Total announcements cached: 30
```

---

## Pairing with the other KLSE skills

You now have three Python-callable KLSE caches the dashboard reads:

| Skill | Refresh script | What it pulls |
|---|---|---|
| `klse-refresh` | `klse_refresh.py` | Per-ticker fundamentals (P/E, P/B, NTA, ROE, DY, RSI, 52w range) |
| `klse-announcements` | `klse_announcements.py` | Filings + derived next-earnings date + upcoming corporate events |
| (existing) `klse-quote` | WebFetch (agent-only) | Same fundamentals, fetched on-demand mid-conversation |
| (existing) `klse-news` | WebFetch (agent-only) | News headlines + same announcement feed, on-demand |

A typical pre-trade workflow for KLSE:

```bash
# Morning routine — refresh both caches once, ~10s of clock time
python3 .claude/skills/klse-refresh/klse_refresh.py
python3 .claude/skills/klse-announcements/klse_announcements.py

# Rebuild dashboard so simulator picks up fresh data
python3 .claude/skills/dashboard/dashboard.py

# Open the dashboard, pick a KLSE ticker in the Risk Simulator, fill in the form
# — every KLSE gate now runs against real cached data, no manual checks needed.
```

---

## Honest limitations

1. **The parser may miss unusual title formats.** Bursa announcement titles vary — most ex-div / AGM titles include the future date in standard phrasing (`Ex Date: 12 Aug 2026`, `to be held on 27 May 2026`), and the parser catches those. Some don't, and those upcoming events won't surface. For high-conviction KLSE trades, supplement with the `klse-news` WebFetch skill.

2. **The 60-day Bursa filing deadline is a worst case.** Companies often file 1–3 weeks before the deadline; the simulator's "filing could come early" warning between 14–20 days out reflects this. For the exact filing date once it's actually scheduled, refresh and check the live announcements.

3. **News headlines are not included.** This script only pulls the announcements feed. For news flow (analyst rating changes, market commentary), use `klse-news` on-demand.

4. **Manual refresh only.** No cron, no auto-update on dashboard rebuild. Refresh when you want fresh data — same model as `klse-refresh`.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `❌ HTTP 503` | klsescreener rate-limited or down | Wait, retry; increase `--delay` |
| `0 announcements` for a ticker | Page returned but parser missed structure | Inspect raw HTML; the parser regex may need updating |
| `next FR by` shows a passed date | klsescreener data is older than 60 days OR the period-end couldn't be parsed | Re-run to refresh; check the title format manually |
| Dashboard sim still warns "no klse-announcements cache" | Cache empty or dashboard not rebuilt | Run the script, then `python3 .claude/skills/dashboard/dashboard.py` |
| Upcoming ex-div / AGM not in cache | Either none exists, or title format isn't parseable | If you know one exists, supplement via `klse-news` WebFetch |

---

## TL;DR

- Run `python3 .claude/skills/klse-announcements/klse_announcements.py` whenever you want fresh KLSE announcement data
- Then `python3 .claude/skills/dashboard/dashboard.py` to refresh the simulator
- The simulator's KLSE earnings gate is now a real check, not a manual-check warning
- Manual by design — no automation
