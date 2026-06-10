# Learned — gotchas + system quirks

Append-only log of things worth knowing. Newest at top. The agent reads this at session start.

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
