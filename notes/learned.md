# Learned — gotchas + system quirks

Append-only log of things worth knowing. Newest at top. The agent reads this at session start.

---

### 2026-06-12 — Dashboard "refresh does nothing" cluster: three structural root causes

**Symptom:** Operator clicks ⚡ Quick or 🔄 Full — stale warnings persist, or nothing visible happens.

**Root cause #1: sources with no refresh path in any button.** `klse_announcements` and `klse_fundamentals` appear in the Data Health panel as stale but are refreshed only by standalone CLIs (`.claude/skills/klse-announcements/klse_announcements.py`, `.claude/skills/klse-refresh/klse_refresh.py`) — no dashboard button ever ran those. `crypto_unlocks` is agent/WebFetch only; no subprocess can refresh it. The Data Health chip was counting all of these in "N sources need refresh," implying a button click would fix them.

**Root cause #2: TTL disagreements so a refresh never cleared the stale flag.** `health.py` marks screener stale after 12h, but `dashboard.py --with-discovery` had a gate that skipped the screener unless the cache was `> 18h`. Between 12h and 18h: chip says stale, button runs, gate says "cache still fresh (< 18h)" → screener NOT re-run → rebuild uses old data → chip still says stale. Same for polymarket (health TTL=12h, auto-refresh threshold=18h).

**Root cause #3: taRefresh silently discarded ok:false.** `server.py`'s `taRefresh` did `await fetch(...)` and threw away the response. When a job was already running (e.g. the auto-quick that fires on page load), the server replied `{ok:false, output:"a job is already running"}` — and the UI showed nothing. Operator clicks into void repeatedly.

**Fix (v2.2.0):**
- `health.py` `REFRESH_VIA` maps every source to `("flag", "--flag")` / `("cli", "path.py")` / `("agent",)`.
- `health.py` `summarize()` splits stale counts into `n_actionable_server` / `n_actionable_agent`. DATA chip uses `n_actionable_server` — no longer lies about what a button can fix.
- `dashboard.py --refresh-stale`: reads health state, enables exactly the needed flags, runs CLIs.
- TTL gates fixed: screener gate → `health.TTL_HOURS['screener']` (12h), polymarket → `health.TTL_HOURS['polymarket']` (12h).
- `taRefresh` reads response; on `ok:false`, shows "⏳ busy" immediately. Per-source ↻ buttons added. Progress banner at page top. Post-reload outcome toast diffs pre/post counts.

**Implication for new data sources:** Register in both `TTL_HOURS` AND `REFRESH_VIA`. A source in TTL_HOURS but not REFRESH_VIA would appear stale with no refresh path — invisible to `--refresh-stale`.

---

### 2026-06-11 — Polymarket crypto events expire daily; macro/geo don't — cache needed an age-based auto-refresh

**Symptom:** Dashboard's Event Probabilities panel rendered "no events" under the Crypto · Price column. Macro, Econ, and Geopolitics columns all populated normally. Data Health panel showed `polymarket ✓ 1` (fresh) — the cache wasn't broken, just empty for that category.

**Root cause:** The polymarket cache was 9h old (fetched yesterday afternoon). The crypto queries (`"bitcoin price"`, `"ethereum price"`) hit Polymarket markets that are *daily* price-band events — e.g. "Bitcoin price on June 10?", "Ethereum price on June 10?". These resolve at midnight UTC and Polymarket flips them to `closed=true`. The fetcher's `if ev.get("closed") or not ev.get("active", True): continue` filter at `polymarket_events.py:236-237` correctly dropped them — leaving the crypto category empty. Meanwhile macro_rates ("Fed rate cuts in 2026"), macro_econ ("US recession by end of 2026"), and geopolitics ("China invade Taiwan by EOY") are all **long-dated events** that survive cache age comfortably.

So Polymarket has **categorically different cache half-lives by category** — and the dashboard's "Quick refresh" wasn't pulling polymarket (only the explicit Full refresh or `--refresh-polymarket` was), so an overnight-aged cache silently emptied the Crypto column on every morning rebuild.

**Fix (this commit):** Polymarket now auto-refreshes during `dashboard.py` when its cache is >18h old or missing. Code path lives in `dashboard.py` main() just before `build_dashboard()`, mirroring the existing `--refresh-polymarket` block. Validated: with a fresh cache no refresh fires; with mtime set 20h back, `[polymarket] auto-refresh: cache 20.0h old (>18h)` prints and the fetcher runs. The 18h threshold matches the project's existing "daily marker" pattern used by the screener — assumes one rebuild per day catches the day's crypto events shortly after they're published.

**What I considered but didn't do:** tightening to 12h (would catch same-day flips earlier but doubles fetcher load with no real-world payoff — operator builds in the morning either way). Adding a per-query staleness signal to the fetcher (over-engineered for a 2-line problem).

**Audit recipe:** if Crypto column ever shows "no events" again, check cache age (`stat .claude/cache/polymarket/events.json`) and run `python3 .claude/skills/polymarket-events/polymarket_events.py` to confirm the API has active events today. The auto-refresh should make this a non-issue going forward, but if Polymarket changes the way they resolve daily events, this is the failure mode that surfaces first.

---

### 2026-06-11 — Data Health surface (v2.1.0) — what to expect on bootstrap

The dashboard now carries a sticky **DATA slot in the Action Rail** (R:R / Entries / Setups / DATA) plus a collapsed **Data Health panel** right below the rail. Each per-source row shows chip counts (✓ fresh, ⏰ stale, ⚠ transient-error, 🛑 permanent-error, — no-coverage, ? missing). Clicking a row expands a per-ticker detail list with the exact error or staleness reason.

When investigating a "why is X showing no data" question:
1. Glance the rail's DATA chip first — yellow `⚠ N sources need refresh` vs red `🛑 permanent errors` vs green `✓ N% healthy` is the one-second answer.
2. Open `📊 Data Health` and look at the source you care about (sentiment.stocktwits, us_news, etc).
3. Per-row detail will say e.g. `STALE — 165h old (TTL 48h)` or `ERROR_TRANSIENT — LLM scoring failed: HTTP 429: …`.
4. Transient errors → run a refresh (it'll go through the v2.0.6 fallback path now). Permanent errors → code/config issue. Stale → just old, refresh if you want fresh.

The health classifier (`.claude/skills/dashboard/health.py`) is pure-logic and tested (`tests/test_health.py` — 41 tests). The TTL defaults are in `health.TTL_HOURS`; if you change a fetcher's expected freshness, update there too.

**What this catches that nothing else does:** v2.0.x found four bugs where degraded data rendered identically to good data. The Data Health surface makes the difference visible. The first deployment immediately surfaced **6 sentiment sources still cached in the pre-v2.0.6 HTTP 429 state** for MRVL/RYDE/RKLB/ETH — the operator had no way to know those tickers' sentiment was broken until the panel showed it.

---

### 2026-06-10 — Sentiment classifier had no LLM fallback — a single Gemma 429 killed the whole source

**Symptom:** RGLD dashboard row showed "RETAIL SENTIMENT — UNKNOWN (no source data)". But `.claude/cache/stocktwits_sentiment/RGLD.json` clearly had 30 messages. Reading `.claude/cache/sentiment/RGLD.json` revealed the bug: the StockTwits source's `present: false` had `error: "HTTP 429: gemma-4-31b-it:free is temporarily rate-limited upstream"`. Reddit and HN were legitimately absent (no posts/stories for Royal Gold), so the composite went UNKNOWN.

**Root cause:** `sentiment_cache.classify_messages` made ONE LLM call. On any failure (including transient 429s), it gave up. The `FALLBACK_MODEL = "openai/gpt-oss-120b:free"` constant was defined at module-top but **never referenced anywhere**. By contrast, `news_glyph._llm_score_batch` HAS the retry-with-fallback loop. The two scorers had divergent reliability.

**Fix (this commit):** Extracted the single-attempt body into `_classify_one_attempt`; `classify_messages` now calls it once with the primary model, and on a transient error (429, 5xx, network) retries with `FALLBACK_MODEL`. Permanent errors (4xx other than 429, JSON parse failure) don't trigger fallback — the fallback would just fail the same way. Added a `_is_transient_error` helper with explicit codes so future tweaks can't accidentally widen "transient" to include programming errors.

**Validated end-to-end:** Re-scoring RGLD with the fix surfaced 🔥 **EXTREME_BULL (bull 84% / conviction 77%) — FADE flag**. That actionable contrarian read was being silently hidden whenever Gemma 429'd.

**Tests:** `tests/test_classifier_fallback.py` — 21 new tests cover the transient classifier (parametrized over codes), fallback trigger on 429, no-retry on permanent errors, no-loop when caller already specifies the fallback, both-fail error reporting.

**Operational gotcha (still):** Gemma 429s are common during batched scoring runs. The fallback now handles each call individually, so a single 429 no longer kills a source — but if BOTH models are rate-limited at the same time, the source still fails. `--model openai/gpt-oss-120b:free` to start on the fallback directly is still the way to do a large batch re-score session.

**This is the kind of bug the data-health surface (logged in notes/ideas.md) would also make visible** — `present: false + error: "HTTP 429"` should be operator-visible as "transient failure, will retry next refresh" not silently identical to `present: false + error: null` (legitimate no-coverage). Worth pairing the two fixes when the data-health work happens.

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
