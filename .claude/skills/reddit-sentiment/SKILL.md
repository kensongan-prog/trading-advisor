---
name: reddit-sentiment
description: Manually refresh retail sentiment for watchlist tickers from Reddit (r/wallstreetbets, r/stocks, r/investing, r/CryptoCurrency, r/Bursa_Malaysia, per-coin subs, etc.) into a local JSON cache that the dashboard reads. Returns mention count, velocity vs 7d baseline, and the top posts per ticker. Raw-fetch leg of the retail-sentiment build — sibling of `stocktwits-sentiment`; both feed the LLM scorer in `sentiment-cache`. Manual by design — no automatic refresh, no cron. REQUIRED before any §4 retail-sentiment contrarian read.
---

# Reddit Sentiment Skill

## When to use

Trigger this skill when the user says:
- "Refresh Reddit sentiment" / "Pull retail chatter"
- "How loud is WSB on AUPH right now?" / "What's r/CryptoCurrency saying about ETH?"
- "Refresh sentiment for the watchlist"
- "Show me the Reddit cache"

Do NOT trigger for:
- Single-shot agent-side lookups during analysis (use WebFetch directly on the post URL — faster for one post mid-conversation)
- Professional news (use `us-news`, `klse-news` instead — different signal category)
- StockTwits or other retail sources (separate skills)

## Why this exists

The doctrine's §4 confluence has technicals + fundamentals + news (professional) + positioning. Retail forum sentiment is a **distinct signal category** — most useful as a **contrarian filter**, not an additive bull signal. Extreme retail bullishness alongside extended technicals is a fade signal; extreme retail bearishness with a constructive P1 setup is a capitulation-buy signal. Mid-range sentiment is no-op (most names land here, which is correct).

This skill uses Reddit's OAuth API when `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` are configured (real per-post/per-comment `score` values, full engagement weighting) and falls back to Reddit's public RSS feed (`search.rss`) when they aren't. RSS carries no scores — posts/comments come back with `score=None`, so the RSS leg's engagement weighting is flat (mention count + velocity only, no upvote-based ranking).

This is the **raw fetcher**. It captures posts + metadata but does NOT score sentiment yet. LLM scoring is a separate layer (`lib/sentiment/llm_score.py`, built next) that consumes this cache and produces the bull/bear/neutral classifications. Splitting the layers means we can re-score without re-fetching.

## Source

Reddit OAuth API: `https://oauth.reddit.com/r/{sub}/search?q={query}&restrict_sr=1&t=week&sort=new&limit=25` with a Bearer token from `client_credentials` grant.

**Why OAuth, not public JSON:** As of 2023, Reddit returns HTTP 403 to all unauthenticated requests to `www.reddit.com/*.json`, regardless of User-Agent. OAuth (application-only, no user login required) is now the only path. Free tier is 100 QPM — far more than we need at ~20-30 tickers per refresh.

**Re-verified 2026-07-06** (live probes from this machine, prompted by 2026-era blog posts claiming the `.json`-suffix trick still works): every `.json` shape tested returned HTTP 403 under both a descriptive UA (`trading-advisor:reddit-sentiment:0.2.0 (by /u/anonymous)`) and a Chrome 126 browser UA, on both `www.reddit.com` and `old.reddit.com` — search (`/r/stocks/search.json`), plain subreddit listing (`/r/stocks/new.json`), and a direct comment thread (`/comments/{id}.json`). PullPush.io (`api.pullpush.io/reddit/search/submission/`), sometimes cited as a scrape-friendly mirror, returned HTTP 429 on the first call and again after a 20s backoff retry — too throttled to serve as a pipeline leg. `search.rss` (the skill's current fallback path) returned HTTP 200 in the same session, confirming it as the only viable no-auth route. Before re-investigating scraping routes, re-run a single `curl -A '<UA>' https://www.reddit.com/r/stocks/new.json` — if that's still 403, nothing downstream will work.

## One-time setup (5 minutes)

1. Go to https://www.reddit.com/prefs/apps (sign in if needed)
2. Click **"are you a developer? create an app..."** at the bottom
3. Fill in:
   - **name:** `trading-advisor-sentiment` (or anything)
   - **type:** select **`script`** (this is critical — script-type apps work with `client_credentials` grant)
   - **description:** (optional, leave blank)
   - **about url:** (optional, leave blank)
   - **redirect uri:** `http://localhost:8080` (required field but unused for our flow)
4. Click **"create app"**
5. On the resulting page, copy:
   - The **client ID** (the short string under the app name, e.g. `abc123XYZ_def`)
   - The **secret** (labeled "secret", longer string)
6. Copy `.env.example` to `.env` in this skill folder and fill in:
   ```
   REDDIT_CLIENT_ID=abc123XYZ_def
   REDDIT_CLIENT_SECRET=longer_secret_string_here
   REDDIT_USERNAME=your_reddit_username
   ```
7. Verify with `python3 .claude/skills/reddit-sentiment/reddit_sentiment.py --check-auth`. You should see `AUTH OK — token acquired`.

Tokens are cached to `.claude/cache/reddit_sentiment/.oauth_token.json` (gitignored via the existing `.claude/cache/` rule) and auto-refreshed before expiry (~1h TTL).

Subreddit routing by asset class:
- **US equity** → `wallstreetbets`, `stocks`, `investing`, `StockMarket`
- **KLSE (.KL)** → `Bursa_Malaysia`, `MalaysianPF`, `malaysia` *(coverage is thin — most KLSE names will return 0 mentions; that's expected and stored gracefully so signals surface if they appear in the future)*
- **Crypto** → `CryptoCurrency`, `CryptoMarkets` + per-coin sub (`Bitcoin`, `ethereum`, `solana`, `binance`, `Ripple`, `Hedera`, `HyperliquidX`, `ethena_labs`)

Crypto queries search both the ticker (BTC) and the name (Bitcoin) to catch both naming conventions.

## Usage

```bash
# Refresh all tickers from watchlist.md
python3 .claude/skills/reddit-sentiment/reddit_sentiment.py

# Refresh specific tickers
python3 .claude/skills/reddit-sentiment/reddit_sentiment.py AUPH BTC 7241.KL

# Show cached values without re-fetching
python3 .claude/skills/reddit-sentiment/reddit_sentiment.py --show

# Show just one ticker's cached data in detail
python3 .claude/skills/reddit-sentiment/reddit_sentiment.py --show AUPH

# Clear the cache
python3 .claude/skills/reddit-sentiment/reddit_sentiment.py --clear
```

## Output

Per-ticker JSON at `.claude/cache/reddit_sentiment/{ticker}.json`:

```json
{
  "ticker": "AUPH",
  "asset_class": "us_equity",
  "fetched_at": "2026-06-08T12:34:56Z",
  "lookback_days": 7,
  "mention_count": 12,
  "posts": [
    {
      "id": "1abcd2e",
      "subreddit": "wallstreetbets",
      "title": "AUPH FDA decision Friday — anyone holding?",
      "score": 145,
      "num_comments": 23,
      "created_utc": 1717891234,
      "url": "https://reddit.com/r/wallstreetbets/comments/...",
      "selftext_excerpt": "First 500 chars of post body..."
    }
  ],
  "error": null
}
```

`mention_count` is the total post count across all subs searched. `posts` is the deduplicated top-N (by score) for downstream LLM scoring. Empty result = `mention_count: 0`, `posts: []`, `error: null` (not an error — just no chatter, which is itself information).

## What this skill is NOT

- Not a sentiment classifier — that's the next layer
- Not a real-time stream — manual refresh only, JSON cache
- Not a comment scraper — step 1 captures posts; comments come in step 2 alongside LLM scoring
- Not a substitute for `us-news` / `klse-news` — those are professional sources; this is retail noise (signal in the noise is the whole point)
