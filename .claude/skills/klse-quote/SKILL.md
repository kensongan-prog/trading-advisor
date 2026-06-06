---
name: klse-quote
description: Fetch a real, timestamped quote and key fundamentals for a Bursa Malaysia (KLSE) listed stock from klsescreener.com. Use whenever the user mentions a Malaysia-listed ticker — either a 4-digit Bursa code (e.g. 1155, 5285, 7277) or the `.KL` form (e.g. 1155.KL). REQUIRED before any analysis or recommendation involving a KLSE name, because the project's primary market-data MCP (Massive) does NOT cover Bursa Malaysia.
---

# KLSE Quote Skill

## When to use

Trigger this skill whenever the user references a Malaysia-listed (Bursa Malaysia / KLSE) stock. Recognize KLSE tickers as:

- A 4-digit numeric code: `1155`, `5285`, `7277`, etc.
- The code with the `.KL` suffix: `1155.KL`, `MAYBANK.KL`
- A KLSE company name explicitly mentioned in a Malaysia-equities context (e.g. "Maybank", "Public Bank", "Tenaga", "Petronas Chemicals")

Do NOT use this skill for US tickers, crypto, or anything Massive already covers — use the Massive MCP for those.

## Why this exists

The project's primary data MCP (`mcp_massive`) does not cover Bursa Malaysia. Per `CLAUDE.md` Section 2 ("Never fabricate a number"), any KLSE recommendation without this skill must return **NO-TRADE: data source missing**. This skill is the only sanctioned data path for KLSE tickers in this project.

## How to use

1. **Normalize the ticker** to the 4-digit Bursa code.
   - If user gave `1155.KL` → use `1155`.
   - If user gave a company name without a code, ask once: "What's the Bursa code? (e.g. Maybank = 1155)." Do not guess.

2. **Fetch the quote page** with the WebFetch tool:
   ```
   URL:    https://www.klsescreener.com/v2/stocks/view/{CODE}
   Prompt: "Extract the following as a structured response. Return 'NOT FOUND'
            for any field genuinely missing from the page; never guess.
            - stock_name
            - bursa_code
            - last_price (numeric, MYR)
            - change_abs (numeric, MYR)
            - change_pct (numeric, %)
            - volume (shares traded today)
            - market_cap (with unit, e.g. '127.5B')
            - pe_ratio
            - eps (sen)
            - dividend_yield_pct
            - week52_high
            - week52_low
            - nta (net tangible assets per share)
            - pb_ratio (price-to-book)
            - roe_pct (return on equity)
            - rsi_14 (if shown — klsescreener publishes this directly)
            - sector / industry if shown
            - last_updated timestamp on the page (if shown)"
   ```

3. **Timestamp the fetch.** Record the wall-clock time of the WebFetch call in your response — this is the "data freshness" timestamp the user needs to judge intraday vs end-of-day.

4. **Return in this exact format** (so it composes cleanly with the CLAUDE.md recommendation block):

   ```
   KLSE QUOTE — {NAME} ({CODE})
   Source:          klsescreener.com (scraped HTML)
   Fetched:         {ISO timestamp of WebFetch call}
   Page timestamp:  {value from page, or "not shown"}

   Last price:      MYR {price}
   Change:          {abs} ({pct}%)
   Volume:          {volume} shares
   Market cap:      MYR {market_cap}
   52w range:       {low} – {high}

   Fundamentals (TTM/last reported):
     P/E:           {pe}
     EPS:           {eps} sen
     Div yield:     {dy}%
     P/B:           {pb}    | NTA: MYR {nta}    | ROE: {roe}%

   Technical (from page, if shown):
     RSI(14):       {rsi}   — note "Overbought" if >70, "Oversold" if <30

   Sector:          {sector or "not shown"}
   ```

5. **Mandatory caveats to surface** in every KLSE response (do not skip these — they're load-bearing for the doctrine):
   - "Source is scraped from klsescreener.com — schema may break without warning, and data lag vs. live Bursa feed is unknown but real (typically 15-min delayed on retail screeners)."
   - If the user is asking for an intraday entry trigger: "Intraday precision not guaranteed by this source; confirm at execution."
   - If P/E, EPS, or dividend yield is being used in the thesis: state when the underlying financials were last reported (this is not on the quote page — note it as unknown unless we add a fundamentals fetch).

## What this skill does NOT cover (yet)

- **Historical OHLCV / charts.** Quote page is a snapshot only. For technical analysis (RSI, MACD, structure), this skill is insufficient — say so and decline the recommendation rather than analyze on one data point.
- **Options chains.** Bursa options are thin; klsescreener doesn't surface chains in a parseable form.
- **Real-time intraday ticks.** Retail screener data is delayed.
- **Indices (KLCI, FBM70, etc.).** Different URL path on klsescreener — extend the skill if needed.

When any of these is required for the user's question, return: **"NO-TRADE: KLSE data stack insufficient for this analysis (needs {what's missing})."** Do not paper over the gap with memory or web search.

## Escalation path (future work)

The fragile-scraping concern is real. When this skill breaks or coverage limits bite, the upgrade path is, in order of preference:

1. **yfinance MCP / module** with `.KL` suffix tickers — gives structured JSON plus historical OHLCV. This skill's contract (return shape, caveats) is designed to be swap-compatible with a yfinance backend.
2. **A paid Bursa data subscription** (Refinitiv, Bursa Marketplace API).

Do not silently fall back to LLM-memory or web search if WebFetch fails — return an explicit error.
