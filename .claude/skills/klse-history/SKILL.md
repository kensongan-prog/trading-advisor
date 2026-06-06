---
name: klse-history
description: Fetch historical OHLCV data and compute technical indicators (RSI, SMA, ATR) for Bursa Malaysia tickers via yfinance. Use this whenever a KLSE recommendation requires price history, trend analysis, structure levels, ATR-based stops, or multi-indicator confluence — i.e. anything beyond a single-day snapshot. Pairs with the `klse-quote` skill (use that for fundamentals + intraday snapshot; use this for OHLCV history + technicals).
---

# KLSE History & Indicators Skill

## When to use

Trigger this skill for KLSE work that needs **any of the following**:

- A multi-day / multi-week chart picture (trend, structure, swing highs/lows).
- Computed technical indicators: RSI(14), SMA20/50/200, ATR(14).
- ATR-based stop placement.
- Historical drawdown context, period change, or volume regime.
- Confluence check on a snapshot from `klse-quote`.

Do NOT trigger for:
- A pure fundamentals look-up (P/E, EPS, dividend yield) — use `klse-quote` instead.
- US tickers, crypto, FX — use the Massive MCP.

## Why this exists

The project's primary market-data MCP (Massive) does not cover Bursa Malaysia. The `klse-quote` skill gives a snapshot but no history. Without history you cannot run playbook P1 (Trend Pullback) or place an ATR-based stop on a KLSE name — both required by `rules/risk-doctrine.md`. This skill closes that gap.

Data source is **yfinance** (Yahoo Finance backend). It is free, reasonably reliable for daily bars on liquid KLSE names, and returns real, timestamped data — never memory.

## How to use

The skill ships with a single Python script: `klse_history.py`. Invoke it via the Bash tool.

### Common invocations

**Standard daily history + full indicator suite (default 6mo window):**
```
python3 .claude/skills/klse-history/klse_history.py \
  --ticker 1155 \
  --period 6mo \
  --indicators rsi,sma20,sma50,sma200,atr14 \
  --rows 10
```

**Long window (needed for SMA200 to fill):**
```
python3 .claude/skills/klse-history/klse_history.py \
  --ticker 1155 --period 2y \
  --indicators rsi,sma20,sma50,sma200,atr14
```

**Custom date range:**
```
python3 .claude/skills/klse-history/klse_history.py \
  --ticker 5285 --start 2025-01-01 --end 2026-06-01
```

**Intraday (for execution-context checks only — daily bars are the primary signal):**
```
python3 .claude/skills/klse-history/klse_history.py \
  --ticker 1155 --period 5d --interval 30m
```

### Ticker normalization

- `1155` → resolved to `1155.KL`
- `1155.KL` → used as-is
- Named tickers (e.g. `MAYBANK`) — script passes them through but yfinance may not resolve. Prefer the numeric Bursa code.

### Available indicators (pass via `--indicators`, comma-separated)

| Name | Window | Notes |
|------|--------|-------|
| `rsi` | 14 (Wilder's) | Overbought >70, oversold <30 flagged in output. |
| `sma20` | 20 | Short-term trend. |
| `sma50` | 50 | Intermediate trend; P1 playbook needs this. |
| `sma200` | 200 | Long-term trend; requires ≥ 1y of history to fill. |
| `atr14` | 14 | Used for stop placement per risk doctrine. |

## Reading the output

The script prints a header, the last N OHLCV rows (with any indicators appended), a latest-bar summary, window stats, and latest indicator readouts with overbought/oversold tags. **Quote numbers directly from this output** in any recommendation — do not round, paraphrase, or fill from memory.

## Hard rules

1. **If the script prints `FETCH FAILED` or `NO DATA`, the recommendation MUST be NO-TRADE with reason "yfinance returned no data."** Do not substitute memory, estimates, or web search.

2. **Zero-volume bars are real and meaningful.** If you see a bar with `Volume: 0`, that's likely a market holiday or a yfinance gap; flag it rather than ignore it — it can distort SMA/RSI by one tick.

3. **SMA200 = NaN means you didn't fetch enough history.** Re-run with `--period 2y` if SMA200 is required for the playbook.

4. **Cross-check with `klse-quote` when both fundamentals and technicals matter.** The two skills hit different sources (yfinance vs klsescreener); agreeing prices/indicators across the two is a small but real data-integrity signal. Material disagreement = stop and investigate, do not trade.

5. **Timestamp every readout.** The script prints `Fetched (UTC): ...`. Carry that timestamp into the recommendation block.

## What this skill does NOT cover

- **Options chains.** Bursa options coverage on yfinance is essentially nil. Playbook P2 (Defined-Risk Premium Sale) is unavailable on KLSE until a real options feed is added.
- **News & sentiment.** Coming separately if/when Alpha Vantage or an equivalent is wired.
- **Corporate actions / earnings calendar.** Not surfaced here; manual check required before any trade with event proximity.
- **Real-time level-2 / order book.** Daily bars are the highest fidelity this skill provides reliably.

## Combined-skill recipe (the common one)

For any KLSE recommendation:

1. Run `klse-quote` → get fundamentals + snapshot + page-RSI.
2. Run `klse-history` with `--indicators rsi,sma20,sma50,sma200,atr14 --period 2y` → get OHLCV, structure, computed indicators, ATR for stops.
3. Confluence check: independently-computed RSI (this skill) vs page-RSI (quote skill). If they disagree by > ~5 points, investigate before trading.
4. Place stop at `entry − 1.5 × ATR14` or just beyond the relevant swing — whichever is wider, per risk doctrine.
5. Output in the standard CLAUDE.md recommendation block, with the `Fetched (UTC)` timestamps from both skills cited as the data snapshot.
