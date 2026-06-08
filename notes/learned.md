# Learned — gotchas + system quirks

Append-only log of things worth knowing. Newest at top. The agent reads this at session start.

---

### 2026-06-07 — macOS XProtect now blocks per-ticker yfinance too (not just bulk)

**Symptom:** "Malicious Script Blocked" popup during `dashboard.py --with-discovery` runs. The screener subprocess gets killed silently; dashboard.html still renders using cached candidates.

**Root cause:** Apple has tightened XProtect signatures over 2026. Our original mitigation ("don't use yf.download bulk, per-ticker is safe") is no longer fully accurate. The screener's fundamentals fallback path (`screener.py:420`, `yf.Ticker(t).info` in a loop for ~130 non-megacap symbols) now matches an XProtect signature too.

**Status (as of 2026-06-07):** Investigation pending. See CHANGELOG.md `[Unreleased] → In flight` for current state. Likely fix is Option B (migrate fundamentals to FMP-only, accept tech-only screening for non-megacap symbols).

**Don't:** add new code paths that loop `yf.Ticker(...)` over 50+ symbols.

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
