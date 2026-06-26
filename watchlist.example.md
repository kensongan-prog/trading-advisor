# Watchlist

Instruments the agent should actively monitor. Keep this lean — a focused watchlist beats a sprawling one. Add a thesis line for each so we know *why* it's here.

> **This is a template.** Copy it to `watchlist.md` (which is git-ignored — your real list stays local and private) and edit it via the `watchlist` skill (`python3 .claude/skills/watchlist/wl.py add|remove|update`). The entries below only illustrate the format and section structure — replace them with your own names.

Format:
- `TICKER` — thesis / setup we're watching for / timeframe

## Equities / ETFs
- `SPY` — broad market regime gauge (not a trade, a context signal)
- `AAPL` — example US large-cap; replace with your own name + thesis

## KLSE (Bursa Malaysia, spot equity only — no options per scope)
- `1155.KL` — example Bursa name (use the 4-digit code or the `.KL` form); replace with your thesis

## Crypto
- `BTC` — regime / dominance reference + core position
- `ETH` — L1 #2, regime + DeFi proxy

## Options (underlyings of interest)
- _Phase 3 only — DARK in Phase 1/2. Candidates land here for future eligibility._

## Removed / retired
_Move tickers here when they stop earning their watchlist slot, with a one-line reason. Don't delete history — calibration depends on it._
- `EXMPL` — example retired entry; keep a one-line reason (removed YYYY-MM-DD: why)
