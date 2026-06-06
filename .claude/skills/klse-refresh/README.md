# KLSE Refresh — User Guide

Manual refresh of klsescreener.com fundamentals for your KLSE watchlist tickers. Pulls P/E, P/B, NTA, ROE, dividend yield, RSI(14), 52-week range, and market cap into a local JSON cache that the dashboard reads.

---

## Quick start

```bash
# From project root:

# Refresh every KLSE ticker in your watchlist
python3 .claude/skills/klse-refresh/klse_refresh.py

# Refresh specific Bursa codes
python3 .claude/skills/klse-refresh/klse_refresh.py 1155 7241

# Look at what's cached without re-fetching
python3 .claude/skills/klse-refresh/klse_refresh.py --show

# Wipe the cache
python3 .claude/skills/klse-refresh/klse_refresh.py --clear
```

Then refresh the dashboard to see the new columns:

```bash
python3 .claude/skills/dashboard/dashboard.py
```

---

## Why this exists

Your dashboard's KLSE grid has always had a gap:

- **Technicals come from yfinance** (`.KL` suffix) — price, RSI, SMA, volume. Works fine.
- **Fundamentals were missing** — yfinance has only sparse data for KLSE tickers. P/E, P/B, NTA, ROE, dividend yield: blank or stale.

The `klse-quote` skill solves this for one ticker at a time via WebFetch (an agent-only tool). But WebFetch can't run from a Python script — which means the dashboard's batch refresh can't pull klsescreener data automatically.

This script bridges the gap: direct HTTP fetch + regex parsing of the klsescreener page, run from a terminal whenever you want fresh fundamentals. Output cached to JSON files; the dashboard reads them on next build.

**It is manual by design.** No cron, no auto-refresh, no scheduled tasks. You run it when you want to.

---

## What gets cached per ticker

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

If a fetch errors, the file looks like:

```json
{
  "bursa_code": "1155",
  "error": "HTTP 503: Service Unavailable",
  "_fetched_at": "2026-06-04T02:40:54+00:00"
}
```

So you never silently use stale data with a fresh timestamp.

---

## How it shows up in the dashboard

After running the script, refresh the dashboard. The KLSE table grows four new columns:

| Code | Name | Price | 24h% | RSI | **P/E** | **P/B** | **DY** | **ROE** | Status | Reason |
|---|---|---|---|---|---|---|---|---|---|---|

The Reason column gets a small freshness tag at the end: `· fund 0h` (0 hours old, fresh), `· fund 3d` (3 days old), or `· no klse-refresh data` (never refreshed for this ticker — run the script).

The header of the panel also shows how many tickers have cached fundamentals.

---

## The five commands

### `klse_refresh.py` — refresh everything in watchlist

Default behavior. Reads `watchlist.md`, finds the KLSE section, refreshes every ticker in it. About 1 second per ticker (politeness delay).

### `klse_refresh.py 1155 7241` — refresh specific codes

Pass any number of Bursa codes as positional args. Accepts `1155`, `01155`, `1155.KL` — all normalized to the 4-digit form.

### `klse_refresh.py --show` — read-only view

Print every cached entry on one line each, with the fetch timestamp. No HTTP requests. Useful for "what do I have cached and when was it pulled."

### `klse_refresh.py --clear` — wipe cache

Delete every file in `.claude/cache/klse_fundamentals/`. Run before a full re-pull if you suspect stale data, or just to start fresh.

### `--delay <seconds>` — adjust politeness

Default 1.0s between requests. Lower to ~0.3 if you need to refresh dozens of tickers quickly; don't go below that or you'll start getting rate-limited.

---

## A typical workflow

You add three new KLSE names to your watchlist:

```bash
python3 .claude/skills/watchlist/wl.py add 5347
python3 .claude/skills/watchlist/wl.py add 5285
python3 .claude/skills/watchlist/wl.py add 1066
```

You want their fundamentals visible in the dashboard:

```bash
python3 .claude/skills/klse-refresh/klse_refresh.py
```

You see something like:

```
Refreshing 7 KLSE ticker(s): 0293, 1066, 4057, 5285, 5347, 7241, 9431
Source: klsescreener.com  |  delay between requests: 1.0s

[1/7] 0293  …  ✓ KJTS: KJTS GROUP BERHAD   px=0.74  P/E=27.5  RSI=34.3  DY=0.54
[2/7] 1066  …  ✓ RHBBANK: RHB BANK BERHAD  px=6.85  P/E=8.91  RSI=42.1  DY=5.84
...
✓ Done.  7 ok, 0 failed.
```

Then refresh the dashboard:

```bash
python3 .claude/skills/dashboard/dashboard.py
```

Done. The new tickers have full fundamentals in the table.

---

## When something looks wrong

| Symptom | Likely cause | Fix |
|---|---|---|
| `❌ HTTP 503: Service Unavailable` | klsescreener temporarily down or rate-limiting | Wait a few minutes, retry. Increase `--delay`. |
| Some fields missing in the JSON (P/B or DY null) | Parser couldn't find that field on this particular ticker | Run `klse-quote` via WebFetch to compare. If the field IS on the page, parser needs updating (see `parse_page()` in `klse_refresh.py`) |
| All fields null but no error | The page structure changed | Same as above — open the page manually and inspect, then update the regex |
| Dashboard says `no klse-refresh data` | Cache empty for that ticker | Run the script |
| RSI from this script doesn't match dashboard's yfinance RSI | Two different sources, computed differently | Expected, slight differences are normal. klsescreener's is shown by `--show`; dashboard uses yfinance's computed value in the RSI column. |

---

## What this skill does NOT cover

- **News / announcements** — use the `klse-news` skill (WebFetch-based, agent-driven, on-demand)
- **Historical OHLCV** — `klse-history` (yfinance, already powering the dashboard)
- **Earnings calendar** — derivable from `klse-news` announcements feed; not in this script
- **Sector classification** — parser doesn't reliably extract sector; missing for now
- **Live intraday data** — klsescreener fundamentals refresh roughly daily; not for tick-by-tick

---

## TL;DR

- Run `python3 .claude/skills/klse-refresh/klse_refresh.py` whenever you want fresh KLSE fundamentals
- Run `python3 .claude/skills/dashboard/dashboard.py` after to see them in the table
- Manual by design — no automation, no cron, your call when to refresh
- Cached files in `.claude/cache/klse_fundamentals/` — one JSON per ticker
- Failures are recorded too, so you never confuse "stale" with "fresh"
