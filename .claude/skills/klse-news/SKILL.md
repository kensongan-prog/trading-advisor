---
name: klse-news
description: Fetch recent news headlines AND official Bursa announcements for a specific KLSE-listed stock from klsescreener.com. Returns dated, sourced items (TheEdge, TheStar, NST, Bursa filings) including analyst rating changes, earnings releases, dividend declarations, and shareholding changes. REQUIRED for any KLSE recommendation that claims a sentiment, catalyst, event, or news edge — and for the mandatory pre-trade event-risk check (earnings, AGM, ex-dividend dates).
---

# KLSE News & Announcements Skill

## When to use

Trigger this skill on any KLSE ticker when the analysis needs:

- **Sentiment / catalyst** read: recent news tone, analyst rating actions, sector headlines.
- **Event risk check** (mandatory per `rules/risk-doctrine.md` Section 2): upcoming earnings, AGM, ex-dividend dates, material announcements.
- **Confirmation of a price move's cause** (e.g. "RSI is oversold — is this earnings-miss-driven or noise?").
- **Pre-recommendation gate**: every KLSE recommendation must check this skill at least for the event-risk window, even if no sentiment claim is in the thesis.

Do NOT use this skill for US tickers (use Alpha Vantage news once wired), crypto (use crypto-specific sources), or non-KLSE Asian markets.

## Why this exists

CLAUDE.md Section 4 requires confluence across {technicals + sentiment OR fundamentals OR flow}. The `klse-quote` and `klse-history` skills cover price/fundamentals/technicals. This skill is the third leg — news, sentiment, and the event calendar — without which we cannot honor Section 5's event-halt rules ("no new directional exposure within 24h before earnings") on KLSE names.

## Two endpoints

klsescreener exposes per-ticker pages at predictable URLs:

| Source | URL | What it gives |
|--------|-----|---------------|
| News | `https://www.klsescreener.com/v2/news/stock/{CODE}` | Headlines from TheEdge, TheStar, NST, Nanyang, Oriental Daily, etc. — dated, sourced, with analyst rating changes called out. |
| Announcements | `https://www.klsescreener.com/v2/announcements/stock/{CODE}` | Official Bursa filings: quarterly results, dividends, AGMs, shareholding changes, capital changes. |

`{CODE}` is the 4-digit Bursa code (e.g. `1155` for Maybank). Strip any `.KL` suffix.

## How to use

### Step 1 — Fetch both endpoints

Use the WebFetch tool. **Always fetch both** unless the user explicitly only wants one — event-risk depends on the announcements feed, sentiment on the news feed.

**News fetch prompt:**
```
URL: https://www.klsescreener.com/v2/news/stock/{CODE}
Prompt: "List the 10 most recent news headlines for this stock.
         For each: date, source, headline (translate non-English to English
         in brackets), and a one-line summary.
         Explicitly flag any item that:
           - is an analyst rating change (Buy / Hold / Sell, target price)
           - mentions earnings beat/miss
           - mentions M&A, capital raise, or material guidance change
           - mentions regulatory action, litigation, or fraud
         Return 'NO HEADLINES' if the feed is empty; do not invent items."
```

**Announcements fetch prompt:**
```
URL: https://www.klsescreener.com/v2/announcements/stock/{CODE}
Prompt: "List the 10 most recent Bursa announcements for this stock.
         For each: date, category (Financial Results / Dividend /
         General Meeting / Changes in Shareholdings / Capital Change /
         Other), and a one-line summary.
         Identify and explicitly call out:
           - the date of the next or most recent Financial Results filing
             (this is the proxy for earnings release date)
           - any scheduled AGM or EGM in the next 30 days
           - any ex-dividend / book-closure date in the next 30 days
         Return 'NO ANNOUNCEMENTS' if the feed is empty; do not invent items."
```

### Step 2 — Synthesize

Combine the two into a single block in this format:

```
KLSE NEWS & EVENTS — {NAME} ({CODE})
Source:    klsescreener.com (news + announcements feeds)
Fetched:   {ISO timestamp of WebFetch calls}

SENTIMENT (last 10 headlines)
  {date}  {source}  {headline}    [TAG: analyst-action / earnings / M&A / etc.]
  ...

DOMINANT TONE: positive / neutral / negative / mixed   (one line of why)
ANALYST ACTIONS (last 30d): {Buy: N, Hold: N, Sell: N, or "none flagged"}

EVENT CALENDAR (from announcements)
  Last earnings release:   {date} — {summary, beat/miss if mentioned}
  Next earnings (proxy):   {expected window based on Bursa filing cadence; "unknown" if not derivable}
  Ex-dividend / AGM / EGM in next 30d: {dates, or "none scheduled"}
  Material recent filings: {top 3 non-routine items}

EVENT-WINDOW STATUS (per risk doctrine §2):
  - In 24h pre-earnings window? YES / NO / UNKNOWN
  - In 48h pre-token-unlock window? N/A (not crypto)
  - Other binary catalyst in window? {if yes, name it}
```

### Step 3 — Apply the doctrine

This skill's output feeds straight into the recommendation gate (`rules/risk-doctrine.md` §7):

- If `EVENT-WINDOW STATUS` flags an earnings or material catalyst within the halt window → recommendation is **NO-TRADE** (KLSE spot has no defined-risk options alternative; cannot trade through the event with capped loss).
- If `DOMINANT TONE` is negative AND a recent analyst downgrade is present AND technicals confirm weakness → that's confluence for a "no trade" / "stand aside" call, not contrarian-buy bravado.
- If the news feed is empty for a name that *should* have coverage (large cap) → flag as a data-integrity issue and lower confidence on the recommendation.

## Hard rules

1. **Never paraphrase a headline you didn't actually fetch.** If WebFetch returns "NO HEADLINES" or fails, say so explicitly — do not fill from LLM memory of what's "probably happening" with the name.

2. **Dates are load-bearing.** Quote them verbatim. A two-week-old "downgrade" is different from a two-day-old one.

3. **Non-English headlines must be flagged.** klsescreener carries Malay and Chinese sources (Nanyang, Oriental Daily, China Press). Translate in-brackets and tag the original language so the user can verify if it matters.

4. **Foreign / unfamiliar source = lower weight.** Treat aggregator items, blogs, and unsourced rumors as context, not as confluence signal. TheEdge, TheStar, NST, Bursa filings = primary.

5. **Earnings release date is the most important number this skill produces.** If you cannot determine the date of the most recent Financial Results filing from the announcements feed, the event-window check is **UNKNOWN**, and per doctrine that defaults to "treat as inside the window" — i.e. no new directional spot exposure until clarified.

## Combined-skill recipe (the full KLSE pre-trade workflow)

For any KLSE recommendation, run in order:

1. `klse-quote` → snapshot + fundamentals.
2. `klse-history` (`--period 2y --indicators rsi,sma20,sma50,sma200,atr14`) → OHLCV + computed indicators + ATR.
3. `klse-news` → sentiment + event calendar + earnings-window check.
4. Confluence verdict: technicals + (sentiment OR fundamentals) align?
5. Gate check per `rules/risk-doctrine.md` §7. Any unchecked box → NO-TRADE.
6. Output in CLAUDE.md format with all three `Fetched (UTC)` timestamps cited.

## What this skill does NOT cover

- **Social sentiment** (Twitter/X, Reddit, Telegram). Not on klsescreener.
- **Real-time alerts.** This is a pull model; if you need watchlist-style monitoring, that's a separate scheduled-task design.
- **Translation quality for non-English headlines.** WebFetch translation is "good enough for triage" — for a high-conviction call on a Chinese-source rumor, verify manually.
- **Historical news archive.** klsescreener typically surfaces the most recent ~weeks-to-months; deep history would need a different source.
