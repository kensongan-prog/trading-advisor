---
name: us-fundamentals
description: Fetch US equity fundamentals (P/E, P/B, ROE, margins, growth, balance sheet, analyst targets) AND earnings calendar (next earnings date with 24h-halt-window check, plus recent earnings history with beat/miss surprise %) via yfinance. REQUIRED before any US-equity recommendation that cites valuation, growth, or quality, and as part of every US pre-trade event-risk check (CLAUDE.md §5 24h pre-earnings halt).
---

# US Fundamentals & Earnings Calendar Skill

## When to use

Trigger on any US-equity recommendation that needs:

- **Valuation context** — P/E, P/S, P/B, EV/EBITDA, PEG.
- **Profitability / quality** — margins, ROE, ROA, free cash flow.
- **Growth** — revenue and earnings YoY / QoQ.
- **Balance sheet health** — debt/equity, current ratio, cash position.
- **Analyst consensus** — recommendation, target prices, implied upside.
- **Earnings event-risk check** — mandatory per CLAUDE.md §5 (24h pre-earnings halt on new directional exposure).
- **Earnings track record** — beat/miss history is a quality signal.

Do NOT use this skill for KLSE (use `klse-quote`), crypto, or non-US tickers. yfinance can resolve some international tickers but the data quality is inconsistent.

## Why this exists

Two gaps closed by one skill:

1. **US fundamentals** — Massive gives prices and indicators but no fundamentals; `us-news` gives sentiment but not the underlying business. Without fundamentals, every US thesis citing valuation or growth is "unverified."
2. **US earnings calendar** — CLAUDE.md §5 forbids new directional exposure within 24h of earnings. Without an earnings-date source, this rule silently couldn't be enforced.

yfinance covers both with no API key required.

## Subcommands

### `fundamentals` — full quality + valuation snapshot

```
python3 .claude/skills/us-fundamentals/us_fundamentals.py fundamentals --ticker AAPL
```

Returns sections:
- **Header**: name, exchange, sector, industry, country.
- **Valuation**: market cap, EV, trailing/forward P/E, PEG, P/S, P/B, EV/EBITDA, EV/revenue.
- **Profitability & returns**: gross/operating/profit margins, ROE, ROA, FCF, operating cash flow.
- **Growth**: revenue and earnings YoY + quarterly.
- **Balance sheet**: cash, debt, debt/equity, current ratio, quick ratio.
- **Dividend**: yield, rate, payout ratio.
- **Share info**: shares outstanding, float, short %, insider/institutional ownership, beta.
- **Analyst consensus**: recommendation key, number of analysts, target mean/range, implied upside vs current price.

### `earnings` — next earnings + halt-window check + history

```
python3 .claude/skills/us-fundamentals/us_fundamentals.py earnings --ticker AAPL
python3 .claude/skills/us-fundamentals/us_fundamentals.py earnings --ticker NVDA --halt-window-hours 24
```

Returns:
- **Next earnings date** with hours-from-now math.
- **EPS / revenue estimates** for the upcoming report.
- **Event-window status**: explicit "WITHIN HALT WINDOW" / "outside halt window" / "earnings already passed" verdict aligned with CLAUDE.md §5.
- **Recent earnings history**: last 8 announced quarters with EPS estimate, reported EPS, and surprise %. A string of beats or misses is a quality / momentum signal.

`--halt-window-hours` defaults to 24 (CLAUDE.md §5 default). Push to 48 for the stricter "Conservative" aggression profile.

## Hard rules

1. **If yfinance fails (`FETCH FAILED`) or returns empty (`NO DATA`), the recommendation drops to NO-TRADE or low-confidence-with-source-cited. Do not substitute LLM memory or general web search.** yfinance is a backend wrapper — if Yahoo changes their API, this skill breaks; that's a known fragility tradeoff for "no key required."

2. **Earnings-date precision matters.** yfinance's next-earnings date is usually the company-confirmed date, but some are "best estimate" from research providers. For high-conviction trades within ~5 days of the reported date, **double-check on the company's investor-relations page or Nasdaq's earnings calendar**.

3. **The 24h pre-earnings halt is non-negotiable for spot/equity.** If the script reports "WITHIN HALT WINDOW," the only allowed structures per doctrine §5 are defined-risk options where the event IS the thesis. Spot equity entries are NO-TRADE.

4. **Forward P/E of "—" usually means no analyst coverage or recent IPO.** Treat as a quality flag, not a missing data field.

5. **yfinance's `dividendYield` field comes back as a percent number (not decimal), unlike the margin fields.** The script handles this; if you parse the raw JSON elsewhere, beware.

6. **Beat-streak ≠ guaranteed future beat.** A 4-quarter beat streak is a momentum signal worth noting in the case-for column, but the case-against must mention "estimate inflation may be catching up." Beat streaks end.

7. **Cross-check P/E with `us-news` sentiment.** Earnings news from `us-news` should be consistent with the trailing P/E and recent surprise % from this skill. Material disagreement = investigate before trading.

## Combined-skill recipe (US equity, full pre-trade workflow — FINAL)

For any US-equity recommendation, run in order:

1. **Massive** `/v2/aggs/ticker/{TICKER}/prev` → previous-day OHLCV.
2. **Massive** `/v1/indicators/rsi/{TICKER}` (and SMA endpoints) → technicals.
3. **`us-fundamentals fundamentals`** → valuation, quality, growth, analyst targets.
4. **`us-fundamentals earnings`** → next earnings date + halt-window gate + history.
5. **`us-news --hours 48 --min-relevance 0.3`** → sentiment + catalyst confluence.
6. Confluence verdict per CLAUDE.md §4 (technicals + sentiment + fundamentals).
7. Gate check per `rules/risk-doctrine.md` §7 — including the §5 earnings halt.
8. Output in CLAUDE.md format with all four `Fetched (UTC)` timestamps cited.

## What this skill does NOT cover

- **Detailed financial statements** (line-by-line income / cash flow / balance sheet over multiple years). yfinance has `.income_stmt`, `.balance_sheet`, `.cash_flow` properties — extend the script if a deep-dive is required.
- **DCF or valuation models.** This is data, not modeling. Build the model on top.
- **Insider transactions / Form 4 filings.** Different yfinance endpoint; add later if needed.
- **Sell-side research notes.** Pull from `us-news` instead — it surfaces analyst rating changes from press coverage.
- **Real-time earnings announcements / live tape.** This is calendar + historical, not live.
