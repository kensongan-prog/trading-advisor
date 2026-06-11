# Learned — gotchas + system quirks

Append-only log of things worth knowing. Newest at top. The agent reads this at session start.

---

### 2026-06-10 — Sentiment classifier had no relevance gate — off-topic items polluted bull/bear%

**Symptom (already noted in v2.0.2):** the HN coverage fix admitted "Microsoft Project Solara" stories into the SOL HN signal. The downstream classifier (`sentiment_cache.classify_messages`) scored every body as bull/bear/neutral with no way to flag "this isn't actually about the ticker." Off-topic content silently diluted the on-topic read.

**Fix (this commit):** Added `relevance` to the classifier output schema. The prompt now asks for `{relevance: primary|mention|none, sentiment, conviction}`; bodies marked `none` get zero weight in `llm_pcts`, `mention` get half weight, `primary` get full weight. The company-name label (`TICKER (Company Name)`) is passed in the prompt — same pattern as the v2.0.1 news-glyph fix — so the LLM can correctly distinguish "Solana" from "Microsoft Project Solara" or "Federal" from "Hedera".

Validated end-to-end:
- **SOL HN**: 4 bodies (Microsoft Project Solara stories + comments) → 4 off-topic, 0 primary. HN signal correctly reads as no-on-topic-data instead of polluted-neutral.
- **BTC HN**: 27 bodies → 14 primary, 3 mention, 10 off-topic. Pre-fix bull/bear/neutral was diluted by the 10 off-topic items; now reflects only the on-topic 17 (14 primary + 3 mention at half-weight).
- **SOL StockTwits**: 30 messages → 15 primary, 14 mention, 1 off-topic. Multi-ticker posts ("$SOL.X + $MA = cool") correctly recognized as mention not primary — half-weighted so they contribute but don't dominate.
- **BTC StockTwits**: 30 messages → 25 primary, 5 mention, 0 off-topic. Almost entirely clean signal as expected.

**Architecture note:** the company-label resolution is `sentiment_cache._company_label() → news_glyph._company_label()` via lazy import. Single source-of-truth map in `news_glyph.COMPANY_LABELS`; both the per-headline scorer and the per-body classifier read it.

**Asset-class plumbing fix:** HN raw caches were missing the `asset_class` field that StockTwits/Reddit raw caches carry. `score_ticker` now infers it (via ticker-pattern fallback when no source has it) and injects into all three raw payloads before per-source processing — so the lazy import + label lookup work for HN even on older cache files.

**Operational gotcha:** OpenRouter free-tier `gemma-4-31b-it:free` 429s easily on consecutive scores. The `gpt-oss-120b:free` fallback handles overflow cleanly; specify `--model openai/gpt-oss-120b:free` for batch re-scoring sessions.

---

### 2026-06-10 — BTFD/STR panel: naïve zip() pairing crypto rows by index silently dropped candidates

**Symptom:** The Action Rail showed `2 BTFD` (counted from watchlist iteration) but the BTFD/STR panel rendered only 1 candidate (MRVL). ENA was qualifying (chg=-10.21%, vol=1.59x — passes crypto LIGHT_DIP gate of chg≤-4% AND vol≥1.5×) but never appeared.

**Root cause:** The BTFD panel iterated `zip(ctx["watchlist"]["crypto"], ctx["crypto_rows"])`. `crypto_rows` comes back from CoinGecko in **market-cap order**, not watchlist order. ENA sat at watchlist position 7 (BTC, ETH, SOL, BNB, XRP, HBAR, HYPE, ENA), but at a different position in `crypto_rows` — so the zip paired ENA's watchlist entry with whatever sat at index 7 in the rows list. The classifier got the wrong chg/vol data and missed the candidate.

This is the *same bug pattern* as the crypto grid (which was already fixed with a `_rows_by_sym = {(r.get("symbol") or "").upper(): r for r in ...}` lookup at line ~4853, with a "BUGFIX:" comment). The BTFD panel had a copy-paste of the original buggy code that nobody noticed because it failed silently — no error, just under-counted.

**Fix:** Same lookup-by-symbol pattern applied to the BTFD panel's crypto loop. Action Rail now uses the IDENTICAL classifier (`classify_btfd_str_shared`) hoisted to render_html scope, so rail counts and panel rows can never drift apart on threshold tweaks.

**Audit recipe:** Any time you see "rail count = X but panel shows Y" for crypto-derived signals, suspect a zip-by-index. Manual reconstruction (iterate watchlist + look up data by symbol explicitly) will reveal which tickers got mis-paired.

---

### 2026-06-10 — Mobile expanded-row dropdown was rendering 1543px wide in a 390px viewport

**Symptom:** Clicking a US/KLSE row to expand its dropdown details panel made the content scroll horizontally — the gates, thesis, sentiment, and news content were essentially off-screen unless you swiped right.

**Root cause:** The mobile CSS made `.panel table { overflow-x: auto; }` with `tbody { min-width: 1100px }` so the body fits all 16 columns horizontally. The expanded row is a separate `<tr.exp-details><td colspan="15">` inside that same tbody. So the `<td>` inherited the 1100px+ min-width and rendered ~1543px wide on a 390px viewport.

**Fix:** Made `.exp-details-content` use `position: sticky; left: 0; max-width: calc(100vw - 24px)`. The content visually clamps to the viewport regardless of the table's horizontal scroll position — and remains visible even if you've scrolled the table sideways to look at distant columns. Also collapsed `.exp-gates-grid` to single-column on mobile so the gates/sentiment/news sections stack instead of competing for narrow space.

**Test recipe:** Inspect computed widths after clicking an expand chevron at mobile width: `pg.evaluate(...)` to read `.exp-details-content` bounding-box width vs viewport width. If they're close, fix is in.

---

### 2026-06-10 — HN sentiment: `num_comments>=3` filter silently dropped niche-ticker coverage

**Symptom:** Inspecting `.claude/cache/hn_sentiment/` showed `story_count=0` for ETH, SOL, HYPE despite these being heavily HN-relevant. RYDE had 5 "stories" of pure junk (e.g. "Show HN: Freenet, a peer-to-peer platform for decentralized apps" — has nothing to do with Ryde Group).

**What was happening:** The Algolia search used `numericFilters: created_at_i>cutoff,num_comments>=3`. Direct API testing showed e.g. "Ethereum" returned 7 stories in the last 30 days *with the time filter alone*, but **0** when adding `num_comments>=3`. Niche-ticker HN posts often sit at 1-2 comments; the `>=3` floor (chosen as "not worth the round-trip") was eliminating every real signal for any non-mainstream name. Meanwhile RYDE's bare-ticker query `"Ryde"` produced false-positive substring matches across the HN corpus.

**Fix (this commit):** Lowered `MIN_COMMENTS_FILTER` from 3 → 1 in `hn_sentiment.py`. After force-rescoring, ETH 0→2, SOL 0→2, HYPE 0→1 (CIFR/CLSK genuinely have no HN coverage — they remain 0, which is correct degraded behavior). Marked `RYDE: None` in `TICKER_NAMES` to skip the noisy query entirely. Each refresh produces a clean cache (`status=no_coverage` with reason) instead of 5 junk stories.

**Tradeoff:** Relaxing the comment filter admits some noise (e.g. SOL now picks up "Microsoft Project Solara" stories which aren't about Solana). That's tolerable because the downstream classifier in `sentiment-cache.classify_messages` already classifies bodies as bull/bear/neutral — irrelevant content scores as `neutral`, diluting but not misleading the composite.

**Next-level improvement (not in this PATCH):** `sentiment-cache.classify_messages` for HN doesn't have a relevance gate (the news-glyph LLM call does — `relevance: primary|mention|none`). Adding a relevance pass to the HN classifier would let real bull/bear signal through cleanly while explicitly dropping noise instead of relying on neutral-dilution. That's a separate calibration project.

**Audit recipe:** `python3 .claude/skills/hn-sentiment/hn_sentiment.py --show` lists per-ticker queries + cache freshness. To verify Algolia behavior directly, hit `https://hn.algolia.com/api/v1/search?query=X&tags=story&numericFilters=created_at_i>{cutoff},num_comments>=N` — N=1 vs N=3 vs N=0 makes a huge difference for niche names.

---

### 2026-06-10 — News-glyph LLM scoring: KLSE non-English headlines need a company-label in the prompt

**Symptom:** Auditing 2110 cached LLM-scored items across 25 tickers (`audit_glyph.py`), the spot-checks looked clean on US/crypto but the four KLSE codes showed a striking pattern: 80%+ of Chinese-press headlines (e.g. `盛艺机构发股收购…`, `亚泛控股…`) scored `relevance=none / score=0.0` and silently dropped from the news signal. Latin-name headlines for the same companies scored fine.

**What was happening:** The scorer's prompt sent `TICKER: 9431` — a 4-digit Bursa code with zero semantic content. The model had no way to know `9431 = Seni Jaya = 盛艺机构`. It pattern-matched recurring proper nouns in English headlines but couldn't bridge to Chinese-only ones. The system prompt already said "TICKER or commonly-known company name" — the language was right, the data wasn't there.

**Fix (shipped in this commit):** Added a `COMPANY_LABELS` map per asset class in `news_glyph.py`. KLSE entries carry both Latin and Chinese forms (`"9431": "Seni Jaya Corporation Berhad / SJC (also written 盛艺机构)"`). The prompt now sends `TICKER: 9431 (Seni Jaya Corporation Berhad / SJC (also written 盛艺机构))`. Threaded `asset_class` through `llm_score_items_for_ticker → _llm_score_batch`. After force-rescoring the 4 KLSE codes, all Chinese-only relevant headlines correctly resolve to `primary` with non-zero scores; unrelated Chinese headlines (世界杯魔咒, 越南黄金) still correctly score `none`. US/crypto unchanged.

**Operational gotcha while validating:** OpenRouter free-tier rate-limit (429) kicked in after re-scoring 1 batch. The GPT-OSS-120B fallback handled the next batch cleanly (verifiable in cache: `models: {'gemma-4-31b-it:free', 'gpt-oss-120b:free'}`). For multi-ticker re-scoring, expect to space requests by ~60s to avoid the 429 → fallback → 429 → empty cache result.

**What NOT to do:** don't auto-add COMPANY_LABELS entries via watchlist parsing. The KLSE entries especially need Chinese forms which can't be auto-derived from the watchlist's English-only thesis line. Manual map entry on watchlist add is correct (~20 KLSE-relevant rows total across all foreseeable watchlist sizes).

**Audit tool:** `python3 .claude/skills/us-news/audit_glyph.py [--ticker X --asset-class Y] [--flagged-only]` joins every cached score to its headline, flags FALSE-NONE/FALSE-PRIMARY/ROUNDUP/NON-ASCII/DIR-MISMATCH. Treat the FALSE-PRIMARY flag as a *suggestion* — it has false positives on analyst-rating items (already filtered) and on legitimate primary headlines where the company name appears in a non-canonical form ("Cipher Unit" vs "Cipher Mining").

---

### 2026-06-10 — Finnhub free tier: `/stock/candle` returns HTTP 403 (premium-gated)

**Symptom:** `finnhub_client.candle_closes()` / `stock_candle()` return `HTTP 403`. Quotes (`/quote`) still work fine.

**Implication:** Finnhub free no longer serves historical candles — only real-time quotes, metrics, news, and upgrade/downgrade. Any code needing OHLCV history (returns, RSI-from-closes, relative strength) cannot use Finnhub on the free tier.

**Workaround:** Use yfinance for history. `rel_strength.py` and `retired_scan.py` both do a single **batched** `yf.download([...], period=...)` (not per-ticker `.info`, per the XProtect note below) to compute returns/indicators. Finnhub stays the source for live intraday quotes (the watcher, per-row 🔄 quote button).

---

### 2026-06-07 — macOS XProtect popup on dashboard build — investigated, unreproducible at real load

**Symptom:** Occasional "Malicious Script Blocked" popup during `dashboard.py --with-discovery`. Screener subprocess may exit early; dashboard.html still renders from cached `candidates.json`.

**What we initially thought:** XProtect tightened signatures to block per-ticker yfinance loops; ~130 sequential `yf.Ticker(t).info` calls in `screener.py:420` were matching a new signature.

**What the data actually showed (diagnostic 2026-06-07):**
- 2 / 10 / 50 / 130 sequential `yf.Ticker(t).info` calls all completed clean — no XProtect kill, no errors, RC=0.
- `fetch_fundamentals` is only called for **P1-passing candidates**, not the full 188-name universe. Real load is typically **1-2 yfinance.info calls per screener run**, not 130. Today's cache showed exactly 2 P1 passers (CMI, SPY) → 1 yfinance fallback.
- So the "130 rapid calls trip XProtect" hypothesis was based on an upper-bound that never actually happens.

**Plausible actual cause of the popup:**
- A one-off XProtect signature push from Apple that fired transiently then got revised
- A different process on the operator's Mac, not the screener
- An intermittent borderline match

**What's in place now:** Defensive `print(f"  [fund] [{i+1}/{len(to_fetch)}] {t} ...")` line at the top of the fundamentals loop (`screener.py` ~line 453). If XProtect fires again, the last-printed line tells us exactly which ticker, which call number, and elapsed time — actionable diagnostic data instead of guessing.

**What NOT to do:** don't ship a fundamentals-path migration to FMP-only "as a precaution." The real load is ~1-2 yfinance calls; the fix would solve a phantom and lose Q+V tagging for non-megacaps.

**If it happens again:** capture the terminal output (the new defensive log), check whether the popup names a specific script path, and revisit. Update this entry, don't preemptively rewrite code.

**Verified end-to-end (2026-06-08):** the defensive trace was exercised via a targeted `fetch_fundamentals(['CMI', 'SPY'], force=True)` invocation. Output was exactly as designed — `[fund] [1/2] CMI (yf_used=0, elapsed 0.0s)` and `[fund] [2/2] SPY (yf_used=1, elapsed 3.5s)` — clean lines, actionable post-mortem data. Cache repopulated correctly, dashboard.py end-to-end rebuild produced a clean 205KB dashboard.html with all panels (Risk Sim, watchlist, discovery) intact. No XProtect popup across the entire verification (130-call diagnostic + 2 forced fundamentals fetches + 2 full dashboard builds).

---

### 2026-06-05 — FMP free tier only covers ~30-50 megacap US symbols

**Symptom:** HTTP 402 (Payment Required) on most non-megacap symbol fetches from FMP `/stable/` endpoints.

**Implication:** Any fundamentals path that relies on FMP for the full screener universe (176 names) will hit paywalls for ~130 of them. The current code falls back to yfinance, but see XProtect note above.

**Workaround:** Either pay for FMP Starter ($14/mo, covers all US equities), or accept tech-only screening for non-megacaps.

---

### 2026-06-05 — Tokenomist.ai is a Next.js SPA — direct urllib scraping returns no data

**Symptom:** `urllib.request.urlopen("https://tokenomist.ai/<slug>")` returns near-empty HTML. All token-unlock data is fetched client-side via JS.

**Workaround:** The `crypto-unlocks` skill is agent-only — uses WebFetch (or whatever the agent's web tool is) to render the SPA. Then results get piped into `crypto-unlocks-cache` Python CLI for persistence. See `.claude/skills/crypto-unlocks-cache/SKILL.md`.

---

### 2026-06-04 — yfinance occasionally returns rows with NaN Close

**Symptom:** Some `yf.Ticker(t).history()` results have a final-row Close=NaN, especially for thinly-traded names or right after a session boundary.

**Fix:** Always `.dropna(subset=["Close"])` before reading the last row. Fall back to Twelve Data if the dropna leaves an empty DataFrame. Pattern used in `dashboard.py` and `screener.py`.
