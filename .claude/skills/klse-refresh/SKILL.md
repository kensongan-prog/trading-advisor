---
name: klse-refresh
description: Manually refresh klsescreener.com fundamentals (P/E, P/B, NTA, ROE, dividend yield, RSI(14), 52w range, market cap) for KLSE / Bursa Malaysia tickers into a local JSON cache that the dashboard reads. Use when the user wants fresh fundamentals on KLSE names — the dashboard's KLSE grid will then surface P/E / P/B / DY / ROE columns. Uses urllib + regex parsing (no WebFetch) so it's runnable from any Python context. Manual by design — no automatic refresh, no cron.
---

# KLSE Refresh Skill

## When to use

Trigger this skill when the user says:

- "Refresh KLSE fundamentals" / "Update KLSE data"
- "Get the latest P/E on my Malaysian stocks"
- "Refresh 1155" / "Pull fresh klsescreener data for 7241"
- "Show me what's in the KLSE cache"

Do NOT trigger this skill for:
- US equities (use `us-fundamentals`)
- Crypto
- Single-shot lookups during analysis (use the existing `klse-quote` skill via WebFetch — faster for one ticker, but agent-only)

## Why this exists

The dashboard's KLSE grid uses yfinance for prices + technicals, but yfinance has only sparse fundamentals for `.KL` tickers. klsescreener.com has the full P/E / P/B / NTA / ROE / DY / RSI(14) / 52w range / sector data the doctrine needs for confluence on KLSE names — but it's a web page, not an API.

The `klse-quote` skill uses WebFetch to read that page — works great for one ticker mid-conversation, but WebFetch can't be called from a Python script, which means it can't power the dashboard's batch refresh.

`klse-refresh` solves that with direct `urllib` + regex parsing. The page structure is consistent enough that regex extraction is reliable for the published fundamental fields. Output lands in `.claude/cache/klse_fundamentals/{code}.json`, which the dashboard picks up on next build.

**Manual by design:** the user runs this when they want fresh data. There is no cron, no scheduled refresh, no auto-pull on dashboard build.

## Source

`https://www.klsescreener.com/v2/stocks/view/{bursa_code}` — direct HTTP fetch with a browser User-Agent. No auth, no rate limit at retail-research scale. A 1-second politeness delay between requests is the default.

## Usage

```bash
# Refresh all KLSE codes currently in watchlist.md
python3 .claude/skills/klse-refresh/klse_refresh.py

# Refresh specific codes (any number of args)
python3 .claude/skills/klse-refresh/klse_refresh.py 1155 7241

# Show cached values without re-fetching
python3 .claude/skills/klse-refresh/klse_refresh.py --show

# Clear the cache
python3 .claude/skills/klse-refresh/klse_refresh.py --clear

# Adjust politeness delay (default 1.0s between requests)
python3 .claude/skills/klse-refresh/klse_refresh.py --delay 0.5
```

Codes accepted in any of: `1155`, `01155`, `1155.KL` — all normalized to the 4-digit zero-padded form.

## Output

Per ticker, a JSON file at `.claude/cache/klse_fundamentals/{code}.json`:

```json
{
  "bursa_code": "4057",
  "page_title": "ASIAPAC: ASIAN PAC HOLDINGS BERHAD",
  "last_price": 0.13,
  "week52_low": 0.09,
  "week52_high": 0.145,
  "pe_ratio": 1.99,
  "eps": 6.53,
  "nta": 0.878,
  "pb_ratio": 0.15,
  "roe_pct": 7.44,
  "dividend_yield_pct": 0.0,
  "market_cap_raw": 193600000.0,
  "rsi_14": 51.0,
  "rsi_14_label": "Neutral",
  "_fetched_at": "2026-06-04T02:40:54+00:00"
}
```

If a fetch fails, the cache file records the error + timestamp so the dashboard can surface "last refresh failed."

## Dashboard integration

When the dashboard build runs, it loads everything in `.claude/cache/klse_fundamentals/` and populates four extra KLSE-grid columns: **P/E · P/B · DY · ROE**. The Reason column gets a freshness tag like `· fund 0h` or `· fund 3d`. If no cache exists for a ticker, the row shows `· no klse-refresh data` and you know to run this script.

The dashboard never auto-fetches klsescreener — your `klse-refresh` invocation is the only path.

## Hard rules

1. **If a fetch fails (HTTP error, parse error), record it but never invent data.** The cache file gets an `error` field + timestamp; the dashboard surfaces "fund 0h (error)" rather than silently using stale data.
2. **Politeness delay default 1.0s.** Don't hammer klsescreener — they're hosting a free service. Lower with `--delay` if you really need to, but think twice.
3. **One file per ticker, atomic write.** Re-running for one ticker won't corrupt others.
4. **Cache freshness is the user's responsibility.** No TTL, no auto-stale check. The dashboard shows the age; act on it.
5. **The script is Phase-agnostic.** It just refreshes data. The doctrine still decides whether a KLSE name is a P1 candidate based on technicals + the refreshed fundamentals.
6. **If klsescreener changes HTML structure, parsing breaks.** That's the scraping tax — the script returns partial data with missing fields. Re-run after the parser is updated.

## What this skill does NOT do

- **News / announcements** — use the `klse-news` skill (via WebFetch) on demand
- **Historical OHLCV / SMA / ATR** — that's `klse-history` (yfinance with `.KL`); dashboard already uses it
- **Live intraday updates** — klsescreener fundamentals refresh once or twice a day at most
- **Earnings calendar** — partially derivable from `klse-news` announcements feed; not in this script
- **Sector classification** — parser doesn't reliably extract sector from the page; treat as missing for now

## Maintenance

The regex parser keys on `<td>LABEL</td><td class="number">VALUE</td>` pairs and a couple of specialized patterns (RSI cell has a wrapper span, market cap has a suffix unit). If klsescreener restructures their page, these need updating:

- `_td_pair()` — primary key/value extractor
- `_td_pair_anyclass()` — for cells with non-`number` value classes
- The `parse_page()` function — fields list and special-case extraction

Test by comparing one ticker's output against a manual `klse-quote` WebFetch run. If they disagree materially, the parser needs work.
