---
name: dashboard
description: Build a self-contained HTML trading dashboard at <project_root>/dashboard.html that consolidates all wired data sources (FRED macro regime, crypto regime, halt-window timeline, watchlist with live technicals/status, journal tail) into one decision-shaping surface. Use when the user wants to view their full trading state at a glance, refresh their dashboard, or audit which names on the watchlist are Phase 1-eligible. The dashboard is static HTML — refresh by re-running the script; no server, no automation.
---

# Dashboard Skill

## When to use

Trigger this skill when the user asks for:

- "Show me my dashboard" / "refresh the dashboard" / "build the dashboard"
- "What does my system look like right now?"
- A unified view across regimes, watchlist, prospectuses, and journal
- A printable snapshot of trading state at a moment in time

Do NOT use for: individual ticker analysis (use the underlying skills directly), trade execution, or alerting (out of scope).

## What it produces

A single self-contained HTML file at **`dashboard.html`** in the project root. Open in any browser. Sections:

1. **Header strip** — Account, Phase, heat used/available, Phase 2 trade-count gate
2. **Regime read** — US Macro (FRED) + Crypto (F&G + CoinGecko /global), side-by-side with composite scores and signal tables
3. **Halt-window timeline** — Next 10 FOMC/CPI/NFP/PCE events with hours-until and 🛑 in-halt tags
4. **Active prospectuses** — Journal entries with PROSPECTUS / LIVE / PENDING status
5. **US equities grid** — Per-ticker price, 24h%, RSI, vs SMA50/200, next earnings, P1 status badge (🟢/🟡/🔴/⚪/❓), reason
6. **KLSE grid** — Per-code price (MYR), technicals, status; fundamentals require `klse-quote` separately
7. **Crypto grid** — Per-coin price, 24h/7d/30d %, Binance funding annualized %, market cap, status
8. **Journal tail** — Last 8 journal entries with their status

## How to use

```
# Standard refresh (uses cache where fresh)
python3 .claude/skills/dashboard/dashboard.py

# Force a full refetch (bypass all caches)
python3 .claude/skills/dashboard/dashboard.py --force

# Refresh + open in default browser
python3 .claude/skills/dashboard/dashboard.py --open

# Skip Alpha Vantage news (preserve daily budget) — currently a no-op stub
python3 .claude/skills/dashboard/dashboard.py --no-news
```

Run from project root. The script logs progress through 8 phases and writes `dashboard.html` on completion.

## Architecture

- **Single Python file**: `.claude/skills/dashboard/dashboard.py`
- **Sources of truth (read-only)**:
  - `watchlist.md` — canonical watchlist; edit directly in your editor
  - `journal/*.md` — prospectuses and trade records
  - Skill `.env` files for FRED_API_KEY, COINGECKO_API_KEY, ALPHAVANTAGE_API_KEY
- **Data fetchers** (embedded in the script — does NOT subprocess the other skills):
  - FRED API for macro regime
  - alternative.me + CoinGecko `/global` for crypto regime
  - yfinance for US + KLSE ticker technicals
  - CoinGecko `/coins/markets` (batch) for crypto prices
  - Binance Futures public API for crypto funding
  - `macro-calendar/schedule.json` (static, no API) for events
- **Cache**: per-section JSON files in `.claude/cache/dashboard/` with TTLs
  - Regime, calendar: 60 min
  - Tickers (US, KLSE): 30 min
  - Crypto markets, funding: 30 min
- **Output**: `dashboard.html` (~25KB, embedded CSS + vanilla JS for sortable tables)
- **No automation**: no cron, no LaunchAgent, no server. Refresh button copies the rebuild command to clipboard.

## Status badge logic

For each US/KLSE ticker, the dashboard runs a P1-eligibility check:

| Badge | Label | Meaning |
|---|---|---|
| 🟢 P1_READY | trend OK + RSI 35-50 + P1 conditions met | Phase 1 entry candidate |
| 🟡 WATCH / EXTENDED / OVERSOLD / NEW | trend OK but other conditions outside band | Monitor, not yet entry |
| 🔴 DOWNTREND / BELOW50 / NO_GOLDEN_CROSS / OVERBOUGHT / TREND_FAIL | hard fail of P1 trend filter or chase risk | No-trade |
| ⚪ CONTEXT | reference signal (e.g., SPY) | Not for entry |
| ❓ DATA | data unavailable / insufficient bars | Re-check later |

Crypto uses a simpler bias read (no formal P1 playbook for crypto spot).

## Hard rules

1. **Dashboard never trades.** It's a read-only visualization layer.
2. **Cache staleness is visible.** Each section shows its data age. If a number looks suspiciously old, run `--force`.
3. **API budget discipline.** Alpha Vantage's 25/day is the tightest constraint. The dashboard currently does NOT pull AV news per-ticker (would burn budget); news flags come from journal/prospectus context. If you want news in the dashboard later, the right design is on-demand-per-ticker, not bulk-on-every-refresh.
4. **The watchlist is edited in `watchlist.md`, not the dashboard.** The dashboard renders what's in the file; edits go in the file.
5. **If a skill source fails**, the section shows "data unavailable" with the error. No fabrication.

## Known limits (mostly addressed in later releases)

This section was once a roadmap of intentional omissions. Most have since shipped — but the dashboard is still **read-only by design** for the source-of-truth files (`watchlist.md`, `journal/*.md`). The remove-row button and prospectus action buttons generate CLI commands you paste into your terminal; they do not write to disk directly. Edits to thesis lines, the doctrine, and watchlist additions all happen via the corresponding CLI skills (`wl.py`, `j.py`), not via the dashboard's HTML.

## Maintenance

- The dashboard's data fetchers duplicate logic from the underlying skills for performance (no subprocess overhead). If you change a skill's data shape (e.g., add a field), the dashboard fetcher needs the same change.
- The status-badge thresholds (RSI 35-50, etc.) are baked into `us_status()`. Adjust there if doctrine changes.
- The HTML template (CSS + JS) is embedded — modify directly in the script.
