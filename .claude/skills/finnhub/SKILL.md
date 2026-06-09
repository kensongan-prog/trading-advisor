---
name: finnhub
description: Finnhub free-tier REST client used as a secondary US-equity data source alongside Massive/yfinance. Currently provides daily OHLCV candles, real-time quotes, basic valuation metrics, recent company news headlines (24-72h window), and analyst rating actions (upgrades/downgrades). Used by sector-rotation, screener, the dashboard's news glyph, and the per-row live-quote refresh button. Free tier is 60 calls/min with no daily cap — generous enough to refresh a full watchlist without budget gymnastics.
---

# Finnhub client skill

## When to use

- **Live quote on demand** — the dashboard's per-row 🔄 button calls `quote(symbol)`.
- **Bulk OHLCV** — sector rotation + screener pull daily candles via `stock_candle` / `candle_closes`.
- **Analyst rating actions** — `upgrade_downgrade(symbol)` is the only free source that returns analyst actions as a *structured* field (date + from-grade + to-grade + action). Used by the dashboard's news glyph to surface the `❗` analyst-action modifier.
- **Recent company news** — `company_news(symbol, days)` cross-checks Alpha Vantage's `us-news` feed and fills coverage gaps on names AV missed.

Do NOT use for:
- KLSE tickers (no coverage on free tier — use `klse-*` skills).
- Crypto (use `crypto-coingecko` / `crypto-derivatives` / `hyperliquid-flow`).
- Per-article sentiment scoring (Finnhub returns headlines without sentiment; if you need sentiment, score elsewhere or read AV's pre-scored items).

## Setup

1. Free signup at https://finnhub.io/register (no card).
2. Drop the key into `.claude/skills/finnhub/.env`:
   ```
   FINNHUB_API_KEY=your-key-here
   ```
3. The client auto-loads `.env` on import. Verify:
   ```python
   from finnhub_client import is_configured, quote
   assert is_configured()
   print(quote("AAPL"))
   ```

## Library interface (Python)

All functions return `(data, error)` tuples. `error` is None on success, a string on failure. Callers MUST check `error` and never silently substitute fabricated data.

| Function | What it returns |
|---|---|
| `quote(symbol)` | Current snapshot: `c` (current), `h`/`l`/`o`, `pc` (prev close), `t` (unix ts) |
| `stock_candle(symbol, resolution="D", days_back=400)` | Daily OHLCV arrays `{t, o, h, l, c, v}`; note free-tier 1-year cap on `D` |
| `candle_closes(symbol, days_back=400)` | Convenience — just the closes list, oldest→newest |
| `metric(symbol, kind="all")` | Basic ratios; many fields paid-only |
| `company_news(symbol, days=2)` | List of recent headlines `{datetime, headline, source, summary, url, category}` |
| `upgrade_downgrade(symbol)` | List of analyst actions `{gradeTime, fromGrade, toGrade, company, action}` — `action` ∈ `up`/`down`/`init`/`main`/`reit` |

## Hard rules

1. **Rate limit:** 60 calls/min. The client paces via `PACE_SECONDS = 1.05` but loops MUST still respect it — don't fan out N parallel calls.
2. **No daily cap, but be reasonable.** Free tier is generous but not infinite — refresh per ticker once per dashboard build, not on every read.
3. **`upgrade_downgrade` returns the full history.** Filter by `gradeTime` for the 24h window yourself; don't assume the API trims.
4. **`company_news` headlines have no sentiment field.** Score externally if you need sentiment. The dashboard's news glyph cross-references AV's pre-scored items for sentiment direction.
