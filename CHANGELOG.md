# Changelog

All notable changes to this project are recorded here.

---

## Versioning policy

This project uses **semantic versioning**: `MAJOR.MINOR.PATCH`.

| Bump | When | Real examples |
|---|---|---|
| **PATCH** (e.g. v1.4 → v1.4.1) | Bug fix, doc typo, defensive logging, dependency bump, investigation outcome, README clarity, link rot, refactor with no behavior change, doctrine rephrasing that doesn't change rules | v1.2 (README clone URL fix); a future "Investigated, no action" audit entry; defensive trace logging |
| **MINOR** (e.g. v1.4 → v1.5) | New capability appears (skill, panel, field, command, convention); the mental model an operator holds about the system shifts; new data source for existing functionality; meaningful optimization | v1.1 (Risk Sim size field); v1.3 (AGENTS.md cross-agent rename); v1.4 (auto-bootstrap + notes/ folder); adding a dashboard panel |
| **MAJOR** (e.g. v1.x → v2.0.0) | Doctrine §1-10 change that re-classifies past recommendations; breaking change to a CLI signature, data file format, or SKILL.md contract; existing operator setup would silently break or behave differently | A future §5 risk cap change from 2% to 1%; renaming `wl.py add` to `wl.py register`; flipping `--with-discovery` default behavior |

### Decision rules

**Pick PATCH when ALL of these are true:**
- The change is backward-compatible AND
- No new user-facing capability is added AND
- The mental model an operator holds about the system doesn't change

**Pick MINOR when EITHER:**
- A new capability appears (skill, panel, field, command, convention), OR
- The mental model shifts (operators now think about the system differently)

**Pick MAJOR when EITHER:**
- A past recommendation would be re-classified under the new rules, OR
- An existing operator's setup would silently break or behave differently

### Edge cases (resolved upfront so we don't argue at release time)

| Situation | Bump |
|---|---|
| Defensive logging added, no user-facing change | PATCH |
| "Investigated, no action" audit entry | No release needed alone; ride with whatever's next |
| Doc-only typo / clarification / link fix | PATCH |
| Doc-only addition that teaches operators something new | MINOR |
| Multiple small fixes batched in one release | Single PATCH (e.g. 3 fixes → v1.4.1, not v1.4.3) |
| Doctrine rule change | MINOR (or MAJOR if past recommendations get re-classified) |
| Doctrine rephrasing that doesn't change rules | PATCH |
| Optimization with no behavior change | PATCH |
| Optimization that meaningfully changes runtime characteristics | MINOR |

### Release-cut threshold (when to publish at all)

Cut a release when **EITHER**:
- `[Unreleased]` contains a real fix users need (any PATCH), OR
- `[Unreleased]` accumulates enough to be worth reading (typically 1-3 MINOR items or 3-5 PATCH items), OR
- You're taking a break and want a clean checkpoint.

**Don't** cut a release when:
- You haven't shipped functional changes (only in-flight notes or non-user-facing `notes/` updates)
- You're mid-experiment

### Historical note

Versions **v1.0 through v1.4** used the older two-level `MAJOR.MINOR` scheme. v1.2 (README clone URL fix) would have been v1.1.1 under the current rules. We adopted full semver from **v1.4.1 / v1.5** onward. Historical tags are not renumbered — `v1.2` stays as it shipped to preserve link integrity.

Versions are tagged in git as `vX.Y.Z` (e.g. `v1.4.1`, `v1.5.0`, `v2.0.0`) and mirrored as GitHub releases. The `.0` PATCH suffix is explicit (write `v1.5.0`, not `v1.5`) so versions sort lexically the way humans read them.

---

## Procedure for adding a changelog entry

This file is a manually-maintained log. **The workflow applies whether or not you use git/GitHub.** Maintaining the changelog is good practice for traceability; whether you back up to a public repo, a private repo, a local-only git folder, or no version control at all is entirely your choice. The project ships with **no automatic git or GitHub operations** — nothing in this repository will push anywhere on your behalf.

### Steps

1. **Whenever you make a meaningful change**, add an entry under `## [Unreleased]` at the top of this file (below the policy section).
2. **Categorize each change** under one of: `### Added`, `### Changed`, `### Fixed`, `### Removed`, `### Deprecated`, `### Security`.
3. **Write entries in the past tense, from the user's perspective**, not the developer's. Example:
   - ✓ Good: `Status badges now show a hover tooltip explaining what the state means and what action it implies.`
   - ✗ Bad: `Added tooltip rendering logic to badge HTML in render_us_grid().`
4. When you decide a batch of changes constitutes a release, **rename `[Unreleased]` to the new version + ISO date**, then create a fresh empty `[Unreleased]` section above it.

### Optional: tag + publish (only if you use git/GitHub)

If you maintain a git repository for this project and want to mark the release with a tag (and optionally a GitHub release), the workflow is:

```bash
git add CHANGELOG.md
git commit -m "Release vX.Y"
git tag -a vX.Y -m "Short release summary"
git push                # only if you have a remote configured
git push origin vX.Y    # only if you have a remote configured
gh release create vX.Y --title "vX.Y — <theme>" --notes "<excerpt from changelog>"  # only if you use gh
```

**None of these steps are required to use the project.** They're conveniences for operators who want a public or backed-up release history.

**Doctrinal rule:** if you are not sure whether a change is MAJOR, MINOR, or PATCH, ask the operator (or, if you are the operator, sit with the question for a moment). **Never silently break a published interface or doctrine.**

---

## [Unreleased]

**Carry-over watch-threads (still in flight after v2.0.0):**
- **Reddit OAuth upgrade pending.** Same status since v1.5.0 — RSS workaround running fine; OAuth path now ACTUALLY functions (v1.10.0 fixed the stub) so when `REDDIT_CLIENT_ID`/`SECRET` land in `.claude/skills/reddit-sentiment/.env` after Reddit's developer-app review (2-4 weeks total), per-comment upvote weighting auto-activates. Will cut as a PATCH once verified. **2026-07-06 update:** no-auth `.json` and PullPush routes were probed live and are dead (403/429 across every shape/UA tested), so RSS stays the fallback until OAuth creds land.
- **Reddit-comment scoring calibration watch.** Sub-point (c) the LLM relevance filter on comment off-topicness — addressed in v2.0.4 by adding a relevance gate to the classifier (works for HN, Reddit comments, and StockTwits). Sub-points (a) and (b) still require trade-outcome data to calibrate — deferred.
- **Threshold calibration watch.** A few weeks of operator use across changing market regimes to confirm sentiment 0.80/0.70 + alignment thresholds, plus BTFD/STR equity/crypto tiers.
- **HN coverage + 1.2× source weight calibration watch.** Coverage half addressed in v2.0.2 (filter floor relaxed, RYDE skip). Source-weight (1.2×) tuning still requires trade-outcome data; deferred.
- **News-glyph LLM scoring quality watch.** Tracking the Gemma 4 31B / GPT-OSS 120B free-tier models on edge cases (non-English KLSE headlines, sector roundups). Tracking 429s / fallback frequency. *(KLSE non-English handling addressed in v2.0.1 — watch downgraded to: monitor for any new edge cases as watchlist evolves.)*

### Added

### Changed

### Fixed

### Removed

### Deprecated

### Security

---

## [v2.10.0] — 2026-07-15

**Theme: the broker bridge lands, the guardrails close, and paper trading comes home to TA.** Ships the full TA ↔ MooMoo bridge (Phases 0–4), the structural-quality guardrails (A+B), the analysis-certainty track (C1–C4), and Perf D — then re-scopes the architecture: MooMoo becomes a read-only broker monitor, paper trading is manual inside TA, and the $20,000 is now explicitly an isolated strategy sleeve.

### Added
- **Dashboard status now separates HTTP liveness from data readiness.** `/api/status` reports `ready`, `degraded`, or `blocked` based on the generated dashboard's presence, age, and data-health issues, allowing GG-8 to keep the process alive while honestly surfacing stale research inputs.
- **Memory protocol (cross-agent retention/decay/promotion rules) added to AGENTS.md; learned.md gains a Hot/archive split.** See the vault's `Memory Protocol.md` and `Lessons — Cross-Project.md`.
- **TA ↔ MooMoo bridge contract pinned (Phase 0 of the broker-bridge plan).** The MooMoo broker adapter (`Projects/Codex/MooMoo`) reads this repo's `watchlist.md` + `journal/*.md` to build trade intents — but nothing on this side guaranteed those formats stay parseable. New `tests/test_bridge_contract.py` (7 tests) mirrors MooMoo's parser regexes and pins the TA-side contract: every watchlist ticker bullet matches the bridge row pattern, the `j.py new` prospectus template carries every field MooMoo keys on (Action/structure, Entry-trigger/Stop-loss/TP1 table, Reference entry/Stop sizing lines, Max loss), a fresh stub is NOT detected as closed (empty Realized-R line), and the full `live → close` status-flip round-trip matches MooMoo's closed-detection. The cross-agent contract doc lives in the vault: "Bridge Contract — Trading Advisor ↔ MooMoo" (formats, gates, known gaps incl. the KLSE `_KL`-stem market-inference bug, and the Phase 0–4 bridge plan).
- **Structural-quality risk flags (Guardrails Phase A).** A $0.17 penny stock with ~50% of its float sold short, beta 2.59, and zero analyst coverage (GPUS) went through the entire pipeline in a prior session with zero warnings anywhere — `wl.py add` validates existence only, and the Risk Simulator's gates are all technical/event/sentiment with no structural-quality check. New `quality_flags.py` module (dashboard skill dir) classifies every watchlist row against 6 equity flags (PENNY, LOW_MC, ILLIQUID, HIGH_SHORT, HIGH_BETA, NO_COVERAGE) and 2 crypto flags (LOW_MC_RANK, THIN_VOLUME), plus a 4-signal pump-and-dump composite (price spike + volume spike + EXTREME_BULL/FADE sentiment + thin structural quality — all four already ingested elsewhere). Every threshold field was already being fetched in the same API calls (yfinance `.info`, CoinGecko markets) — zero extra cost. Flags render as compact chips beside the ticker in all three watchlist tables (US/KLSE/crypto), with full explanations in the expanded-row detail. Warn-loudly-never-block: this is pure classification, nothing here blocks a trade. Live-verified: GPUS now shows 🪙🐜🎯🎢👻 (5 flags); SPY (a context gauge, never a trade candidate) correctly shows none — the analyst-coverage check would otherwise fire on every ETF, since none carry sell-side coverage; caught and fixed during verification, mirroring the existing `EARNINGS_SKIP_TICKERS` precedent. Regression tests `tests/test_quality_flags.py` (24 tests, incl. the real GPUS/AAPL numbers as fixtures).
- **Structural-quality gates in the Risk Simulator + add-time warnings + prospectus recording (Guardrails Phase B).** Wires Phase A's flags into the three points where a risky name should actually surface: (1) the Risk Simulator's client-side gate list now shows a "Structural quality" row per ticker, sourced from the SAME flags (`t.quality_flags`, threaded through `sim_tickers`/`sim_json`, zero extra fetch); (2) `wl.py add` prints every flag before the confirm prompt and adapts its wording ("N structural-quality flag(s) above — add anyway?") when any are present; (3) the "Create prospectus" command now passes `--quality-flags` through to `j.py new`, which renders a new `### Structural risk flags` section into the journal — a permanent record of what was known at entry. **Design call, deviating from the original plan:** the plan proposed the pump-and-dump composite as a hard `'bad'` gate ("verdict downgrade to NO-by-default"), but the sim's `hardBads` list directly disables the Create Prospectus button with no override affordance in the UI today — that would be the project's first hard block, conflicting with doctrine §1 (the operator decides) and the "warn-loudly-never-block" principle this whole guardrails effort is built on. Shipped as `'warn'` instead (visually distinct — 🚩 prefix — but never disables anything); a real override-able hard-block UI is a candidate for a future pass if wanted. Live-verified in a real browser (Playwright): GPUS renders `warn` (not `bad`) on Structural quality even while other pre-existing gates correctly fail it to NO-TRADE; MRVL renders clean `ok`; a real `wl.py add GME` dry-run shows the flag + adapted prompt with no file mutation on abort; a real generated GPUS-style prospectus carries the full flags section. Regression tests across `tests/test_prospectus_quality_flags.py` (5) and `tests/test_watchlist_quality_flags.py` (9, 2 pandas-gated).
- **`broker-sync` skill — TA-side Phase 2 of the MooMoo bridge.** MooMoo's Phase 1 (paper-order lifecycle) is complete and already aggregates per-intent fill state in `data/moomoo/staged_orders.json` (`filled_qty`, `filled_avg_price`, `approval_state`, `journal_path`). New skill reads that read-only via `MOOMOO_ROOT` and attributes fills into the correct journal entry: first BUY fill flips PROSPECTUS → LIVE (`j.py live --paper`), further fill growth posts an Updates note (never re-flips), a journal already CLOSED/DEAD is never touched even if the broker shows a later fill, and — deliberately — **SELL fills are never auto-processed**; closing needs win/loss/scratch/timeout classification (doctrine §9), a human judgment call `j.py close --result` already requires explicitly, so every SELL fill lands in a review artifact instead. Journal resolution matches by the exact basename stem of `journal_path` (not the raw absolute path, which can encode a different machine's checkout) — exact traceability, journal filenames are unique in this project's convention. Idempotent via a TA-owned `sync_state.json`: a re-run with nothing new performs zero journal writes. `review.json` is regenerated fresh each run for anything ambiguous/unresolvable (unmatched journal_path, a SELL fill, a filled_qty regression, a non-integer share count, an unrecognized journal status) — nothing is ever silently dropped. Live-verified end to end: real journal fixtures through flip→partial-growth→full-fill→idempotent-rerun (4 sequential syncs), a real CLOSED-journal never touched, a real SELL fill routed to review not executed, and a real dry-run against MooMoo's actual on-disk `staged_orders.json`. One real bug caught by that live run and fixed before shipping: a staged-but-unfilled order (the common case — no fill yet, often no `journal_path` yet either) was being flagged for review with nothing to review; the no-fill-yet check now runs before journal resolution is even attempted. Regression tests `tests/test_broker_sync.py` (31 tests). MooMoo Phase 2 fix list, incl. KLSE `_KL`→`.KL` normalization, was already complete on the MooMoo side per the bridge contract note.
- **Read-only "Broker (MooMoo)" dashboard panel — Bridge Phase 3.** New `moomoo_status.py` (dashboard skill dir) reads `broker-sync`'s own `sync_state.json`/`review.json` plus MooMoo's `positions.json`/`trade_ledger.json` (read-only via the same `MOOMOO_ROOT` `broker-sync` already resolves — no duplicated config) and a new panel renders it: a table of SIMULATE-tracked intents (ticker, last action, filled qty, broker status, synced-when), any `broker-sync` review items in the same visual language as the Data Health panel's problem rows, and a collapsed **"Real broker account — NOT paper trading, informational only"** section (real positions, realized P&L, fees, open lots) — kept clearly, visually separate from the paper-trading picture Phase 1 doctrine actually cares about, since MooMoo's own realized-P&L ledger intentionally excludes SIMULATE rows and reflects the operator's actual live brokerage account instead. A cross-link opens the MooMoo dashboard (`localhost:8788`) in a new tab. **No order controls anywhere in this panel, by design** — execution stays in MooMoo only (see the vault Bridge Contract note); pinned by a dedicated test asserting none of MooMoo's mutation function names ever appear in the rendered fragment. Degrades gracefully when `MOOMOO_ROOT` isn't configured (a normal, expected state, not an error). Live-verified against real on-disk MooMoo data (9 real positions, $468 realized P&L, 4 ledger issues, all rendered correctly) — caught and fixed one real display bug: an observed-but-never-submitted staged order (no `journal_path` yet) was showing the raw, path-laden `intent_id` string instead of a clean ticker in the intents table; now parses the ticker out of `intent_id`'s own `source:TICKER:path` format. Regression tests `tests/test_broker_panel.py` (12 tests).
- **`calibration-report` skill — outcome engine (Analysis C1).** Aggregate expectancy (`portfolio.py expectancy`) answers "am I net positive"; this answers "why" — buckets every CLOSED journal entry's realized R by the gate state captured at entry (RSI band, sentiment flag, RS-vs-SPY leader/laggard, sector, structural-quality flags) so the 20-trade Phase-2 calibration gate means more than a raw count. Required first extending capture: the journal's `### Data snapshot` table recorded RSI/regime at entry but never sector, sentiment flag, or RS-vs-SPY — so a closed trade's entry-time context couldn't be reconstructed. Added `--sector`/`--sentiment-flag`/`--rs-1m` to `j.py new` (mirrors the `--quality-flags` precedent from Guardrails Phase B), threaded from the Risk Simulator's "Create prospectus" command builder using values already computed for the sim's own gates (US sim rows now carry `t.sector` from yfinance `.info` and `t.rs_vs_spy_1m` from the existing `rel_strength.json` cache; `t.sentiment_flag` was already there) — zero extra fetches. New `.claude/skills/calibration-report/calibration_report.py` reads `portfolio.closed_trades()` + re-parses each journal's Data snapshot table, buckets win-rate/avg-R/sum-R per dimension, and flags any bucket with `n<3` as low-confidence rather than hiding it (same warn-loudly-never-block spirit as `quality_flags.py`). Live-verified against the real journal: the one real CLOSED trade (CLSK, +2.70R) correctly buckets into RSI 50-70 / clean structural flags, and correctly shows "unknown" for sector/sentiment/RS since it predates the 2026-07-02 capture fields — older trades still count toward win-rate/expectancy, they just can't be bucketed by the newer dimensions. Regression tests `tests/test_prospectus_calibration_fields.py` (2) + `tests/test_calibration_report.py` (12).
- **Analysis C2–C4: relative strength, sector rotation, and earnings-surprise history promoted from display-only to decision context.** Three data sources were already computed and rendered somewhere on the dashboard but never fed the Risk Simulator or Discovery panel — the utilization-ladder gap this closes. **C2 (RS gate):** the watchlist's own thesis is "buy P1 pullbacks in leaders," but nothing enforced it; the sim now reads the same `rs_vs_spy_1m` already added for C1 and warns (US only) when a ticker's 1m RS vs SPY is negative — "lagging the market." **C3 (sector-rotation caveat):** a new `YF_SECTOR_TO_SPDR_NAME` map translates yfinance's GICS sector string to sector-rotation.py's SPDR-ETF naming so a ticker's sector can be checked against the sector-rotation cache's bottom-3 composite; the sim warns (US only) when a ticker's sector is currently lagging. Both C2 and C3 render `warn`, never `bad` — same warn-loudly-never-block posture as every other guardrail this session, per doctrine §1 (operator decides). **C4 (earnings-surprise history):** new `_parse_earnings_surprise_history()` turns yfinance's `Ticker.earnings_dates` into a compact most-recent-first surprise history + consecutive-beat streak; watchlist tickers get it free (reuses the already-open `Ticker` object `fetch_yfinance_ticker` already pays for — one more attribute access, zero extra network round-trip) and surface it in the expanded-row detail ("Earnings history: 🔥 3 beats in a row"); Discovery-panel candidates get a new cached `fetch_earnings_beat_streak()` (24h TTL) scoped to only the ≤20 rows actually rendered (`DISCOVERY_CAP`), not the full ~200-name scanned universe, so it doesn't become a new per-scan cost — a 🔥N badge appears on the row itself above a 2-quarter streak, full history in the expanded detail. Context only, never a gate, never blocks. Live-verified against the real dashboard build: MRVL shows "🔥 3 beats in a row (last +0.6%)" in its watchlist detail; MS shows a real 8-quarter streak badge in Discovery; RS-vs-SPY and sector-bottom-3 fields confirmed present and correct in the sim payload for every real US ticker (SPY correctly excluded — a context gauge, never a trade candidate). Regression tests `tests/test_earnings_beat_streak.py` (10 tests, 2 pandas-gated).
- **`risk_params.json` export — Bridge Phase 4, TA side.** MooMoo staging currently validates position sizing against whatever account/risk numbers were baked into a prospectus's prose at draft time — stale the moment the operator's account size or caps change. New `portfolio.risk_params()`/`write_risk_params()` exports account equity, the 2%/6% caps, live heat usage, and the 20-trade calibration gate's pass/fail state (`live_trading_unlock_eligible`) to `risk_params.json` at repo root — gitignored, regenerated by `portfolio.py sync` and every `j.py live`/`update`/`close` (same trigger cadence as `portfolio.md`), read by MooMoo directly off the local filesystem via its existing `TRADING_ADVISOR_ROOT` (same bridge pattern as `watchlist.md`/`journal/*.md`, no new MooMoo-side config). Doctrine alignment — "`MOOMOO_LIVE_TRADING_ENABLED=true` requires the same 20-trade paper gate as TA's own Phase 2, one unified ramp" — now lives in `AGENTS.md` itself, not just the vault. **Scope: TA side only.** MooMoo's own reader + staging validation + live-trading gate enforcement is a separate, Codex-owned follow-up; nothing on the MooMoo side changed this session. Live-verified against the real journal (1 closed trade, +2.70R, correctly `passed: false`) via both the CLI and a real `j.py`-triggered sync. Regression tests `tests/test_portfolio.py::TestRiskParams` (6 tests).

### Changed

- **Paper trading is now managed entirely inside Trading Advisor, by hand.** MooMoo no longer executes paper orders (its paper endpoints return `paper_trading_disabled` as of 2026-07-09), so a paper setup is now run with `j.py live --paper` → `update` → `close`, exactly as before but without any broker in the loop — portfolio heat and the 20-trade Phase-2 calibration still auto-derive from the journal. A true simulator is deliberately deferred until manual tracking proves insufficient. This keeps the founding doctrine intact: TA still never places a broker order.
- The USD20,000 risk base is now explicitly an isolated Trading Advisor strategy sleeve. `risk_params.json` exports `equity_scope`, `strategy_sleeve_equity_usd`, and `heat_scope` while retaining `account_equity_usd` as a backward-compatible alias.
- The read-only MooMoo dashboard panel now shows real broker positions and ledger context only; legacy SIMULATE intent and broker-sync review content is no longer part of the operator surface.

### Fixed

### Removed
- **Dead `finnhub_client.upgrade_downgrade()` (Perf D2).** Verified live 2026-07-01: Finnhub's `/stock/upgrade-downgrade` returns HTTP 403 on the free tier (premium-gated). The function had zero call sites anywhere in the codebase — `news_glyph.py` already migrated to yfinance's `Ticker.upgrades_downgrades` (same output shape, so the rest of the pipeline stayed source-agnostic) in an earlier pass, but the dead Finnhub function and stale doc references (`finnhub/SKILL.md`, `news_glyph.py`'s header comment) were never cleaned up. Removed the function; corrected the docs to point at the actual yfinance-backed path. No behavior change — this was pure orphaned-code + doc-drift cleanup. **D1 (batching sentiment-LLM calls across tickers) evaluated and deliberately skipped:** the current classifier already batches multiple *messages* per ticker per call; batching multiple *tickers* into one call would require reworking the prompt into per-ticker segments, the response schema, and all 4 source processors (stocktwits/reddit/hn/klse) plus their orchestration — a real refactor for a payoff (fewer free-tier 429s) the existing dual-model fallback already mostly absorbs. The task's own stated alternative (lean on the manual `sentiment-inline` skill when automated scoring hits rate limits) covers the remaining gap without the refactor.

### Deprecated

- The `broker-sync` skill is now historical compatibility code for the retired MooMoo SIMULATE flow. It is no longer part of the current paper workflow.

### Security

---

## [v2.9.0] — 2026-07-01

### Added
- **KLSE retail-sentiment leg (`klse-sentiment`).** Bursa Malaysia names had essentially no retail-sentiment read — StockTwits 404s on KLSE codes and Reddit's `r/Bursa_Malaysia` is thin, so they scored `UNKNOWN`. New skill scrapes klsescreener's per-stock community comment thread (`/v2/comments/all/stock/{code}` — real, multilingual, no login wall), windows to a recent 180 days, and feeds a new `process_klse` source into the `sentiment-cache` composite (weight 1.0, additive — it fills a near-empty slot rather than re-weighting). For an active Bursa name like Seni Jaya (9431) that's ~20 recent comments → a real BULL/BEAR/NEUTRAL composite where before there was nothing. Coverage is uneven by design (quiet names store `no_coverage`; the composite's coverage-haircut keeps thin samples from firing high-conviction flags). Registered in Data Health (TTL 24h, refreshable). Regression tests `tests/test_klse_sentiment.py`. *(KLSE **news** was investigated too but NOT rebuilt — `news_glyph.refresh_klse` already scrapes it; see `notes/learned.md`.)*

### Changed
- **KLSE news is now windowed to 180 days + headlines decode HTML entities.** `news_glyph.refresh_klse` (the existing KLSE news scraper) now filters to the last 180 days — a ceiling for firehose names, a floor that trims quiet names' years-old stale tail — and the headline cleaner runs `html.unescape`, so `&#039;`/`&amp;` no longer leak into the glyph (a pre-existing bug). Regression test `tests/test_news_glyph_klse.py`.
- **End-of-session ritual is now cross-agent (in `AGENTS.md`).** The ritual — final test run + `[Unreleased]` in-flight note + **knowledge-vault sync** — previously lived only in `CLAUDE.md`, which Codex doesn't auto-load (Codex reads `AGENTS.md`). So Codex had no instruction to sync the vault, risking repo↔vault drift on Codex sessions. `AGENTS.md`'s minimal end-of-session note (in-flight only) was expanded to the full three-step ritual, and the vault-sync step in both files now reads "for every meaningful change — don't ask, just do it" (skip only when nothing material shipped). Makes "all updates get written to the vault" true for both agents.

---

## [v2.8.0] — 2026-07-01

### Added
- **🌏 Asian-ADR tag in Discovery.** Liquid Asian ADRs (25 names across Taiwan, China, India, Japan, Singapore, South Korea — e.g. TSM, BABA, PDD, INFY, SONY, SE) now screen alongside US names, and any that pass P1 and earn a Buffett tier tag (💎/🏆/💰) carry an additional **🌏 region badge**. The badge composes *with* the tier — ADRs are scored on the exact same Quality+Value gates as US names, the globe just flags the foreign listing. Expanding an ADR row shows its extra risks (FX drift, overnight home-market gap, ADR custody fee, and — China only — the PCAOB/HFCAA delisting overhang). Banks were deliberately excluded (no gross-margin / EV-EBITDA → they'd never tag, same as US financials). Source of truth is a new `adrs` region-map in `universe.json`; universe grew 176 → 200 names. Coverage was verified first: 29-name draft, all resolved in yfinance, and the names that don't score are the ones that shouldn't (banks, loss-making EV startups). Regression test `tests/test_adr_tag.py`.

### Fixed
- **SPY no longer spams a yfinance 404 on every build.** SPY is the index/regime gauge — an ETF with no company earnings — so yfinance's `.calendar` (calendarEvents quoteSummary) call 404'd for it ("No fundamentals data found for symbol: SPY") and logged the HTTP error as noise on every dashboard rebuild. The earnings fetch now skips tickers in a new `EARNINGS_SKIP_TICKERS` set (`{SPY}`); `.info` and price history were always fine and SPY has no earnings, so nothing is lost. Surfaced while adding GPUS — the 404 was SPY's, unrelated to the new ticker. Regression test `tests/test_earnings_skip.py`.

---

## [v2.7.0] — 2026-06-25

### Added
- **Live dashboard — Phase 5: refresh the Data Health panel in place (no rebuild, no reload).** A **↻ now** button on the Data Health header re-reads current cache freshness and swaps just that panel's contents — reflecting out-of-band changes (e.g. a refresh CLI run in a terminal) instantly, with an "updated HH:MM" stamp. `render_health_panel` was extracted from the monolithic `render_html` into a standalone `render_health_panel_html(...)` so the server can render the fragment via a new `/api/panel/health` endpoint without a full dashboard build (health only reads cache states — no data fetch). The panel's collapse toggle is now **event-delegated**, so it (and any future swapped panel) keeps working after an in-place content swap. Regression tests `tests/test_panel_fragments.py`. (Scoped to the Data Health panel — the highest-value, lowest-coupling target; other panels can follow the same pattern later.)
- **Live dashboard — Phase 3: whole-watchlist live quotes.** A **⚡ Live quotes** toggle (next to the filter) streams live prices for every US + crypto row on a staggered interval — Finnhub for US, Binance/CoinGecko for crypto, all browser-direct and free. Live values render beside each row's baked daily close with an "as of HH:MM" stamp and a ticking "● live" indicator, so live vs baked is unmistakable; the per-row 🔄 button shares the exact same fetch path. KLSE rows are skipped (no free CORS-friendly live quote). The staggering keeps a full sweep well under Finnhub's 60/min. Authoritative cells (RSI, vs-SMA, BTFD tier, sim verdict) are never overwritten from a live tick — those need history the client doesn't have (§1/§4). Regression test `tests/test_live_quotes.py` pins the toggle/sweep wiring and the shared fetch path.
- **Live dashboard — Phase 2: updates no longer throw away your place.** Previously every server-driven update (refresh, watchlist add/remove, journal edit) ended in a full `location.reload()` that reset scroll position, collapsed every expanded row, dropped the sort order, and cleared the filter. Now the control server snapshots that view state just before reloading and the rebuilt page restores it — scroll, expanded rows (keyed by **ticker**, so they survive re-sorting and add/remove), active column sort, and the filter text all persist across an update. (The fully flash-free in-place morph remains a future polish; it needs a larger re-init refactor of the Risk Simulator / prospectus forms, and matters less once Phase 4 lets cheap signals update without a rebuild at all.) Regression test `tests/test_ui_state_preservation.py` pins the capture/restore wiring across `server.py` and `dashboard.py`.
- **Live dashboard — Phase 1: watchlist filter + per-row sparklines.** A 🔎 filter box above the watchlist grids hides non-matching rows by ticker/name as you type (with an "N of M shown" count); pure client-side, instant. Each US / KLSE / crypto row now carries an inline SVG **sparkline** of its recent price trend (green if the window closes up, red if down), baked from a new downsampled `spark` close-series captured in the ticker fetchers. Sparklines populate on the next data refresh (`--force` or natural TTL). First of a phased upgrade making the dashboard a live, server-backed surface rather than a static page. Regression test `tests/test_sparkline.py` pins the series downsample/round and the SVG draw contract.
- **`sentiment-inline` skill** — re-score retail sentiment using the *current Claude Code session* as the classifier instead of OpenRouter's free models: no metered API, no spend, and a stronger model than the free Gemma/GPT-OSS pair. A manual, session-driven alternative to the slow `sentiment-cache` LLM leg (free-tier 429 backoffs). `score_inline.py dump --stale` captures the body batches the real scorer would send; the session fills a `scores` array; `score_inline.py ingest` replays `score_ticker` with those classifications — monkeypatching *only* `classify_messages` so all real aggregation, engagement weighting, the v2.6.0 coverage haircut, composite math, and cache format are reused (zero format drift). Re-scores existing raw social caches in place; not headless (automated builds still use `sentiment-cache`). Regression test `tests/test_sentiment_inline.py` pins the content key, the dump→ingest round-trip, and no global-state leak. First run cleared 13 stale watchlist names (KTOS 91% bull but no FADE — coverage haircut held conviction at 43%).
- **launchd agent for the control server** — `.claude/skills/dashboard/com.trading-advisor.dashboard.plist` (KeepAlive + RunAtLoad) for running the dashboard server as a boot-persistent daemon. NOTE: loading it requires granting Full Disk Access to `/usr/bin/python3` because the project lives under `~/Documents` (macOS TCC blocks launchd file access there → `EX_CONFIG`/78 flapping otherwise). Until that one-time manual grant, run the server detached via `nohup … & disown`.

### Changed
- **One watchlist-add path instead of two.** The dashboard previously had two ways to add a ticker that both shipped on the served page: a static **"Watchlist Manager"** that only *generated a `wl.py` command to copy-paste* (with no rebuild, so a successful add stayed invisible), and the live **control-panel** form that runs `wl.py` and auto-rebuilds. The copy-paste manager is removed; the live control-panel form is now the single add/remove/update UI. To preserve everything the old form could do, the control-panel add form gained a **section override** (auto / us / klse / crypto / options) and a **force-add** (`--allow-unresolved`) checkbox. Net effect: adding a ticker through the dashboard now takes effect and shows up without any manual rebuild step. Regression test `tests/test_watchlist_add_consolidation.py` pins the section/force passthrough, the post-add rebuild, and the removal of the static manager.

### Fixed
- **Live dashboard — Phase 4 (hardening).** Cache writes are now **atomic** (`cache_set` writes a temp file then `os.replace()`s it into place), so a concurrent reader — the parallel-fetch ThreadPool, or a second process — can never observe a half-written JSON cache. Regression tests in `tests/test_cache_atomic.py`. (Note: the plan's "poll server caches every 2s and patch them live" was intentionally dropped — without the background daemon the operator declined, those caches only change during a full rebuild, so live-polling them would be churn for no benefit; the genuinely live data, prices, is already handled client-side in Phase 3.)
- **Job-semantics tests no longer clobber the live `last_job.log`.** `TestJobSemantics` now redirects `LAST_JOB_LOG` to a temp path via an autouse fixture (clears the in-flight cleanup note from a prior session).
- **KLSE 📊 quote button no longer 404s.** Clicking a Bursa name's quote link (e.g. KJTS / 0293) opened `klsescreener.com/v2/stocks/quote/{code}`, which returns "Not Found" — the path never existed. The button now uses `/v2/stocks/view/{code}`, the exact path the `klse-quote` and `klse-refresh` skills already use to fetch the same page, so the link and the data-fetch path can't drift. Regression test `tests/test_klse_quote_link.py` pins the `/view/` path and bans the 404'ing `/quote/`.
- **Data Health no longer shows a permanent "9 source(s) refreshable" that no refresh clears.** Two health *lookup* mismatches (not real data gaps): (a) `crypto_news` caches are keyed by CoinGecko slug (`bitcoin.json`), but `health._crypto_key` lowercased the ticker (`btc.json`) → all 8 crypto names read as missing forever; fixed with a `_crypto_news_key` slug map mirroring `dashboard.SYMBOL_MAP`. (b) SPY is intentionally never `us_news`-fetched (it's the index gauge — `news_cache.priority_for_ticker` returns `None`), but health expected `SPY.json`; now skipped via `US_NEWS_SKIP`. Result: missing 9 → 0, refreshable 9 → 0 (crypto_news now 5 fresh + 3 honest no_coverage). Regression test `tests/test_health_crypto_news.py` pins the slug lookup and the SPY skip.
- **Control server now binds dual-stack (IPv6 + IPv4) in `--lan` mode.** It was IPv4-only (`0.0.0.0`), so clients reaching it over IPv6 — `localhost` → `::1` on macOS, or a Tailscale MagicDNS/IPv6 address — got connection-refused and the dashboard looked "down." New `DualStackHTTPServer` binds `::` with `IPV6_V6ONLY=0`, serving `127.0.0.1`, LAN IPv4, Tailscale IPv4, `::1`, IPv6, and MagicDNS from one socket. Local (non-`--lan`) mode stays IPv4 loopback. Regression test `tests/test_server_dualstack.py` binds `::` on an ephemeral port and asserts both `127.0.0.1` and `::1` reach `/api/status`. (Also diagnosed/recovered a wedged long-lived server instance — large HTML responses hung while `/api/status` still answered; a restart clears it.)

### Removed
- **Static "Watchlist Manager" copy-paste panel** (and its `TA_WL` payload / tab CSS) — superseded by the live control-panel watchlist form. Removed ~200 lines of redundant in-page command-generation JS/HTML.

### Deprecated

### Security

---

## [v2.6.1] — 2026-06-15

### Fixed
- **US news now actually refreshes the names the Data Health panel flags stale.** TTL mismatch: health flagged `us_news` stale at 48h, but the news refresh's `P3_context` priority (plain watchlist names) only refreshed after 168h — so `--refresh-stale` silently skipped them while the panel showed them "stale & refreshable" (only journal names, on 6/12h TTLs, ever refreshed). Reconciled `news_cache.PRIORITY_TTL_HOURS["P3_context"]` 168h → 48h to match `health.TTL_HOURS["us_news"]`; AV's daily-budget reserve still protects the 25/day cap. Verified: a refresh took US news 2 → 12 of 13 fresh (SPY correctly skipped). Regression test (`tests/test_news_ttl_reconciliation.py`) pins the invariant: the loosest news priority TTL must stay ≤ health's us_news TTL.

---

## [v2.6.0] — 2026-06-15

**Risk ⊕ sentiment ⊕ positioning fusion — closing three gaps from a data-utilization audit so the Risk Simulator's verdict actually uses the data we ingest.**

### Added
- **§4 retail-sentiment confluence in the Risk Simulator.** Every simulated long is now checked against the retail contrarian flag — 🔥 FADE (euphoric) → `warn` ("a long here chases a crowded name"), 🧊 BUY (capitulation) → `ok` ("aligns with the contrarian read"). Gated on conviction so thin reads stay quiet; degrades to a neutral `ℹ` "not assessed" when the sentiment cache is stale/missing (new `info` gate severity — never a false caveat, no verdict weight). Previously sentiment lived only in a separate panel and never touched the GO/CAUTION verdict.
- **OI trend + top-trader long/short ingested.** `fetch_binance_funding` now also pulls 7-day open-interest trend (USD) and the top-trader long/short ratio, folded with funding into **one** synthesized "Perp positioning" sim factor (they all measure crowding and are correlated — a single read, not three). Rising OI + one-sided top traders amplify the flush-risk wording when crowding aligns.

### Changed
- **Retail sentiment is now volume-aware.** The composite conviction is multiplied by a log-scaled coverage factor — `min(1, log1p(n_total)/log1p(25))` over the on-topic scored sample — so a read off 2 messages can no longer carry the same weight (or fire the same FADE/BUY flag) as one off 50. Flows through every consumer: the contrarian flag, the Contrarian Setups panel, and the sim's §4 factor. Exposes `conviction_raw` / `coverage` / `n_total`. Takes effect on the next sentiment re-score.

### Notes
- **hyperliquid-flow whale tracking deliberately not wired into the build.** It needs a target address you supply, so it's an interactive agent tool ("what's address X holding"), not a per-coin auto-build signal — the data-utilization audit confirmed it belongs at rung 0 *for the dashboard*, which is correct, not a gap.

---

## [v2.5.0] — 2026-06-15

**Editorial-dark restyle + a refresh-UX overhaul (live progress banner, completion notifications, graceful degradation) + a critical control-bar fix.**

### Added
- **Dashboard restyle — "editorial dark".** New typographic hierarchy (Archivo grotesque for headers/labels, IBM Plex Mono for all data so numbers stay aligned), deeper layered surfaces with hairline borders + subtle depth, the Action Rail as four distinct inset cards, and refined tables / panel headers with accent chevrons. Same dense, functional layout — just intentionally designed rather than generic-dark. Fonts are **self-hosted and embedded** as base64 `@font-face` at build time (`.claude/skills/dashboard/fonts/*.woff2`, ~95 KB), so the dashboard is fully self-contained: fonts render offline / over `file://` / over Tailscale with zero external requests.
- **Completion notifications for refresh.** When a refresh finishes, you get a prominent toast *and* — if you've granted permission — a browser/OS notification, on both success ("✓ Dashboard refresh complete — N source(s) cleared") and failure ("✗ Dashboard refresh failed — open the Control log"). The OS notification pings you even if you've switched to another tab during the (often multi-minute) refresh. Permission is requested on your first refresh click; if denied or unsupported (e.g. http over Tailscale, which isn't a secure context), the in-page toast still shows. Failures previously surfaced only as a small line in the Control widget — now they get an explicit toast + notification.

### Changed
- **Refresh progress is now obvious.** Clicking any refresh button (Quick / Full / ↻ refresh-all-stale / per-source ↻) instantly shows a prominent top banner with a spinner, the current build phase (pulled live from the job log, e.g. "[5/8] Fetching US ticker data…"), and a **live elapsed-time counter**. The ticking timer makes it unmistakable that the system is working rather than frozen — previously the only feedback was a thin delayed line pointing at the bottom-right widget. Network failures now surface a clear "couldn't reach server" message instead of leaving a stuck spinner.

### Fixed
- **A transient API failure in one enrichment layer no longer fails the whole refresh.** The per-ticker price fetches were already isolated, but the news, sentiment, and news-glyph refresh steps in `build_dashboard` were not — so a single OpenRouter 429, Finnhub blip, or network drop mid-refresh would crash the entire build (exit 1) and surface as an opaque "refresh failed." Each enrichment step is now wrapped: on failure it logs which layer broke, renders the dashboard from cached data for that layer, and the build still completes. A "⚠ Completed with N degraded layer(s): …" summary is printed, and the Data Health panel honestly shows those sources still stale. (This was the likely cause of intermittent "refresh failed" reports.)
- Job output is now persisted to `.claude/cache/dashboard/last_job.log` (server-run refreshes), so a failure stays diagnosable after a server restart — previously the job log was in-memory only and lost. The failure toast/notification now point at this file.
- **Critical: server-side refresh buttons were completely broken since v2.2.0.** A quote-nesting syntax error in the post-refresh toast (`onclick="…style.display='none'"` inside a single-quoted JS string) was a parse error that killed the *entire* injected control-bar script — so `taRefresh` and every refresh button silently did nothing whenever the dashboard was served (the dashboard build's own `node --check` never saw it because the control bar is injected by `server.py` at serve time). Fixed the handler and added a regression test (`test_server_routes.py::TestControlBarJS`) that `node --check`s the control-bar JS so this class of bug can't ship again.

---

## [v2.4.1] — 2026-06-14

**Refresh-button cleanup: real per-source refresh + no more silently-dead buttons on static pages.**

### Added
- `dashboard.py --refresh-source NAME` — refresh a single health source via its `REFRESH_VIA` path, then rebuild. Rejects unknown / agent-only names.

### Changed
- **Per-source ↻ refresh buttons now actually refresh just that source.** Previously the Data Health panel's per-row ↻ (and the `/api/refresh-source` endpoint) ran the full `--refresh-stale` batch regardless of which source you clicked — so the per-source granularity was an illusion (flagged in the v2.2.0 review). Now clicking ↻ on, say, `polymarket` enables only `--refresh-polymarket`; the Control panel's ⚡ Quick (and "↻ refresh all stale") remain the all-stale batch. Routing is shared via a single `_route_refresh()` helper used by both `--refresh-stale` and `--refresh-source`. Net effect: the four refresh affordances no longer overlap — ⚡ Quick / ↻ refresh-all-stale = batch, ↻ per-source = one source, 🔄 Full = force-rebuild everything.

### Fixed
- Static-snapshot (`file://`) dashboards no longer have silently-dead refresh buttons. When the page is opened as a file rather than served by `server.py`, the refresh control bar isn't injected, so the in-page "↻ refresh" / "refresh all stale" buttons had no handler and clicks did nothing. Now a sticky banner ("⚠ Static snapshot — open http://localhost:8787 …") appears and the buttons show clear guidance on starting the server, instead of failing silently. Served mode is unchanged. (Note: editing the journal/watchlist via the terminal CLIs does not rebuild the static `dashboard.html` — use the server, or re-run `dashboard.py`.)

---

## [v2.4.0] — 2026-06-14

**Collapsible dashboard sections + a CLI help-crash fix.**

### Added
- **Collapsible dashboard sections.** Click any panel's heading to fold/unfold that section; the chevron (▾/▸) shows state. Fold state persists per-panel in `localStorage` (keyed by panel title, stable across rebuilds) and works in static `file://` mode. Clicking a control inside a header (e.g. Data Health's "refresh all stale" button) doesn't toggle the fold. The Regime panel keeps its existing native `<details>` collapse.

### Fixed
- `j.py new --help` no longer crashes with `TypeError: must be real number, not dict`. The `--atr-pct` help string had a literal `%` ("ATR% …") that argparse tried to %-format; escaped to `%%`. The command itself was unaffected — only `--help` output. Found during the v2.3.0 end-to-end sweep; regression test (`tests/test_journal_cli.py`) now asserts every j.py subcommand's `--help` exits cleanly.

---

## [v2.3.0] — 2026-06-13

**Optimization pass: regression coverage for the safety rails, faster builds, less duplication.** Internal-quality release — no user-facing behavior change. Scoped down from a larger plan after measurement (see notes below).

### Added
- **51 regression tests** over logic that enforces AGENTS.md §5 guardrails but had zero coverage: `portfolio.heat()` (the 6%/$1,200 heat ceiling) + expectancy aggregation; MAE/MFE R-math; the Phase-1 entry gate + level sizing; watcher journal-level parsing (currency-only) + market-hours gate + dedupe; and the server Job "one-at-a-time" busy semantics (the v2.2.0 silent-no-op fix). Suite: 177 → 228 tests.
- `_cli_lib.py` (dashboard skill dir) — shared operator-CLI helpers (`watchlist_us`, `batch_closes`, `load_json_cache`), replacing copy-pasted versions in `rel_strength.py`, `retired_scan.py`, `setup_queue.py`.
- `--green-rgb` / `--yellow-rgb` / `--red-rgb` `:root` CSS variables — single source for the brand colors used as rgba() tints at many alphas across the dashboard.

### Changed
- Dashboard build parallelizes the FRED macro-regime and crypto-regime fetches (independent network calls, run concurrently) and the per-coin Binance funding loop (same `ThreadPoolExecutor` fan-out already used for yfinance). Faster cold builds; identical output.
- Two pure helpers extracted for testability with no behavior change: `mae_mfe.excursion_r()` and `setup_queue.passes_p1_gate()`.
- 37 hardcoded brand-color RGB triples in the CSS now reference the new `:root` vars.

### Notes (deliberate scope reductions, measurement-backed)
- **Shared `.env`/HTTP modules across skills — not done.** Each skill dir is intentionally self-contained (zero cross-skill imports; documented as a replication feature). Sharing trivial, stable env-loader code would couple every skill to a `_shared/` package and break copy-one-folder portability. Only the same-dir operator-CLI helpers (a real bug-source) were consolidated.
- **Shared cache class — not done.** dashboard.py's `cache_get`/`cache_set`/`_read_cache` are already centralized in one file; other cache variants live in the self-contained skill dirs above. A shared class would abstract already-single-source code.
- **Sim-data lazy-load + inline-style/media-query sweep — not done.** The sim blob is 16.6KB of a 454KB page (3.7%); the lazy-load endpoint + `file://` fallback wasn't worth the complexity. Most of the 1091 rendered `style=` attributes are dynamically generated per-row, not static.

---

## [v2.2.0] — 2026-06-12

**Dashboard refresh UX overhaul — stale-driven refresh, per-source buttons, honest chip counts, visible progress.**

Root causes addressed: (1) stale sources with no refresh path in any button, (2) TTL disagreements so refreshing never cleared the stale flag, (3) `taRefresh` silently discarded `{ok:false}` responses when a job was busy, (4) refresh progress invisible outside the collapsed Control widget, (5) no post-refresh outcome report so "still shows stale" read as "button broken."

### Added
- `health.py` — `REFRESH_VIA` registry: maps every source in `TTL_HOURS` to its refresh method (`flag` / `cli` / `agent`). Covers all 14 sources including KLSE CLIs (klse_announcements, klse_fundamentals) and the agent-only `crypto_unlocks`.
- `health.py` — `source_refresh_via()`: resolves source names including `sentiment.*` composite sub-sources to their REFRESH_VIA entry.
- `health.py` — `validate_refresh_source()`: pure function factored out of the server handler; rejects unknown and agent-only sources with a clear message. Used by tests and `/api/refresh-source`.
- `health.py` `summarize()` — two new output fields: `n_actionable_server` (stale/transient/missing records fixable by a server job) and `n_actionable_agent` (need an agent session). Computed by mapping each record through `REFRESH_VIA`.
- `dashboard.py` — `--refresh-stale` flag: reads the current Data Health state at build time, maps each stale/transient/missing source to its refresh path, enables the appropriate `--refresh-*` flags, runs CLI tools (klse_announcements.py, klse_refresh.py) via subprocess, then rebuilds. Agent-only sources print a skip notice rather than silently failing. Prints a plan line upfront: `[stale-refresh] N sources → flags: X · CLIs: Y · agent-only (skipped): Z`.
- `server.py` — `POST /api/refresh-source {source}`: validates the source name via `health.validate_refresh_source`, rejects agent-only sources, starts a `--refresh-stale` job labelled `"refresh <source>"`. Used by the per-source ↻ buttons in the Data Health panel.
- Data Health panel — per-source ↻ refresh buttons on every server-refreshable row with non-fresh records. Agent-only sources show an "agent" badge instead. "↻ refresh all stale" button in the panel header (calls Quick = `--refresh-stale`).
- Progress banner (`#ta-banner`): fixed position at top of page, appears within one poll cycle (2s) when any job starts — visible regardless of whether the Control widget is open.
- Post-refresh outcome toast (`#ta-toast`): `captureHealthState()` stashes health counts in `sessionStorage` before any refresh; after `location.reload()`, diffs pre/post and shows: cleared count, still-stale count, agent-only note, and honest "still flagged — check log" when nothing improved.
- 23 new tests in `tests/test_health.py`: `TestRefreshVia` (every TTL_HOURS key covered, no orphan extras, flag/cli/agent tuple shapes), `TestValidateRefreshSource`, `TestSummarize.test_server_vs_agent_split`.

### Changed
- `QUICK_FLAGS` → `["--refresh-stale"]`. Quick now means "refresh exactly what Data Health flags stale, honoring TTLs" — not a hardcoded layer list. Polymarket auto-refresh, screener, KLSE CLIs are all handled by `--refresh-stale` based on current health state.
- DATA chip text now uses `n_actionable_server` (not `n_transient`) so it counts only what a button click can actually fix. Agent-only stale sources are shown separately as "N agent-only" and not counted in the "refreshable" total.
- Panel explainer text updated: no longer promises "transient errors will be fixed by a refresh" for all sources; now says "use ↻ per-row or refresh all stale" and notes agent-only sources separately.
- `taRefresh` reads the POST response: on `ok:false` (job busy), immediately shows "⏳ busy — wait for current job to finish" in `#tactl-msg` instead of silently doing nothing.
- `taRefresh` and `taRefreshSource` disable both Quick/Full buttons synchronously on click (before the fetch resolves), so there's no lag before visual feedback.
- Age text in Control header (`data X.Xh old`) now updates live on every 2s poll tick instead of only on page load.
- Server header comment updated to reflect new Quick semantics.

### Fixed
- Screener TTL gate mismatch: `--with-discovery` was skipping the screener if cache was `< 18h` old, but `health.py` flags it stale at 12h. Fixed: gate now uses `health.TTL_HOURS['screener']` (12h), so a refresh actually clears the stale flag.
- Polymarket auto-refresh threshold was 18h but health.py's TTL is 12h. Fixed: now uses `health.TTL_HOURS['polymarket']` (12h).

---

## [v2.1.1] — 2026-06-11

Three operator-visible PATCH fixes that surfaced from a single fresh dashboard load and cluster around the same theme: the dashboard's freshness contracts (TTLs, auto-refresh, button behavior) need to be consistent and visible, not hidden behind `--force` flags or stale-cache silent renders.

### Changed

- **Data Health panel: source-name layout.** The per-source rows used `justify-content: space-between` on a flex container, which (combined with the chevron `▸` rendered as a `::before` pseudo-element) treated chevron + name + chips as three flex items spread across the full row width. The source name ended up dead-centered with hundreds of px of empty space on either side — looked like a layout bug because it was one. Now: chevron + name sit flush left together, chips are right-aligned via `margin-left: auto`. No content change; pure visual.

- **Server control bar's ⚡ Quick refresh now honors source TTLs instead of force-refetching every cache.** `QUICK_FLAGS` previously included `--force`, which busts every TTL system-wide — meaning the screener (18h TTL), sector rotation (4h), rel-strength (4h), macro-rates, yfinance ticker data, and crypto markets all refetched on every Quick click, even if cached and fresh. That contradicted the v2.0.0 documented behavior ("Rebuilds from caches; only fetches what's expired") and worked against the same TTL-honoring philosophy the new Polymarket auto-refresh establishes. Now: Quick = `--refresh-polymarket` only. Stale and missing caches are still refetched (TTLs do that work); fresh caches are skipped. Polymarket stays explicit because clicking Quick signals operator intent ("I want fresh now") — plus the >18h auto-refresh handles overnight-aged caches regardless. Full refresh keeps `--force` because that button explicitly means "nuke and rebuild." Measured Quick path: ~10.6s on warm caches, matching the v2.0.0 doc claim of "~10-15s."

### Fixed

- **Polymarket cache auto-refreshes on dashboard build when >18h old or missing.** Previously polymarket only refreshed on explicit `--refresh-polymarket` (or via the Quick/Full refresh buttons). That worked fine for the macro/geo categories — those events are long-dated (Fed cuts in 2026, recession-by-EOY, Taiwan-by-EOY). But the crypto category queries hit *daily* price-band events ("Bitcoin price on June 10?") which Polymarket flips to `closed=true` at midnight UTC. An overnight-stale cache silently rendered the Crypto column empty on every morning build, even though the API had fresh "today" events available. Auto-refresh closes that gap. See `notes/learned.md` (2026-06-11) for the full diagnosis.

---

## [v2.1.0] — 2026-06-11

Data Health surface — MINOR. v2.0.x found four bugs where degraded data looked identical to good data on the dashboard (crypto-zip × 2 panels, KLSE Chinese headlines silently scoring to none, HN comment-filter dropping coverage, sentiment 429s hiding behind `present:false`). Pytest catches code regressions before they ship; the Data Health surface catches data degradation *after* it ships. v2.1.0 closes that gap.

### Added

- **`📊 Data Health` panel and Action Rail slot.** A 4th rail slot (R:R / Entries / Setups / DATA) shows a one-glance summary: `✓ N% healthy` (green), `⚠ N sources need refresh · M stale · N% healthy` (yellow, transient errors present), or `🛑 N permanent error(s)` (red, pulsing). Clicking jumps to the full Data Health panel rendered right below the rail. Each per-source row shows chip counts (✓ fresh, ⏰ stale, ⚠ transient-error, 🛑 permanent-error, — no-coverage, ? missing); expanding the row lists exactly which tickers are in non-healthy states and why ("LLM scoring failed: HTTP 429: …", "165h old (TTL 48h)", "no cache file"). Mobile-aware layout: stacks to single-column on phones with full-width row detail.
- **`.claude/skills/dashboard/health.py` — health classification module.** Pure-logic functions covering the state taxonomy (`fresh` / `stale` / `error_transient` / `error_permanent` / `no_coverage` / `missing`), per-source TTL defaults, the `is_transient_error()` helper (mirrors `sentiment_cache._is_transient_error`), the sentiment-composite per-source classifier (`classify_sentiment_sources()`), the cache walker (`collect_health()`), and the global summarizer.
- **`tests/test_health.py` — 41 new tests.** Covers the transient-error classifier across known transient codes (429, 5xx, URLError, timeout) and permanent ones (401-404, parse failures), the file-state classifier across every state including TTL boundaries, all five timestamp-key variants the different caches use (`fetched_at`, `_fetched_at`, `scored_at`, `_generated_at`, `_last_full_pass_at`), the sentiment-composite classifier (including the exact RGLD failure mode), the summarizer counts, and the state-priority ordering. Suite now at **153 tests, ~3s**.

### Validation

First deployment of the surface immediately uncovered:
- **6 sentiment sources still cached in the pre-v2.0.6 HTTP 429 state** for MRVL / RYDE / RKLB / ETH (the v2.0.6 fix is in, but the cached results from before still need re-scoring — the operator now sees this).
- 8 crypto news files **missing** entirely.
- 4 KLSE announcement caches **stale** at 154h.
- 7 us_news entries **stale** at 131-165h (one full week without refresh).

None of these were operator-visible before. All four categories produced clean-looking dashboard renders that silently hid degraded inputs.

---

## [v2.0.6] — 2026-06-11

Silent-failure PATCH. The operator noticed RGLD's dashboard row showed "RETAIL SENTIMENT — UNKNOWN (no source data)" despite having 30 StockTwits messages cached. Investigation revealed `sentiment_cache.classify_messages` made a single LLM call and gave up on any failure — the `FALLBACK_MODEL` constant defined at module-top was never actually used. A transient Gemma 429 was silently nuking the entire StockTwits source for any ticker scored during the rate-limit window.

### Fixed

- **`classify_messages` now falls back to `gpt-oss-120b:free` on transient errors from the primary model.** Extracted the single-attempt logic into `_classify_one_attempt`; the wrapper tries primary, then retries with `FALLBACK_MODEL` on 429/5xx/network errors. Permanent errors (401/403/404, JSON parse failure) skip the fallback because it'd produce the same result. The fallback path mirrors what `news_glyph._llm_score_batch` already did — `sentiment_cache` was missing it.
- **Re-validation:** RGLD after re-scoring surfaces 🔥 EXTREME_BULL (84% bull / 77% conviction) — a FADE flag that was being silently hidden whenever the Gemma rate limit was active. This is a real, actionable contrarian signal that the operator was being denied because of an unimplemented fallback.

### Added

- **`tests/test_classifier_fallback.py` — 21 new tests** locking the fallback contract:
  - `_is_transient_error` parametrized over 7 transient codes (429, 500, 502, 503, 504, URLError, timeout) and 6 permanent ones (401, 403, 404, JSON parse, expected-list, key-missing). Future tweaks can't accidentally widen or narrow what counts as transient.
  - `classify_messages` retries fallback exactly once on 429, doesn't retry on 401, doesn't retry when caller already explicitly specified the fallback model (no infinite loop), reports both errors when both fail, skips fallback on success.
  - Suite now sits at **112 tests, ~3s**.

---

## [v2.0.5] — 2026-06-10

Test-suite PATCH. Every silent bug the v2.0.x series surfaced (the two zip-by-index recurrences, the KLSE Chinese-headlines miss, the HN comment-filter floor) shared a failure mode: degraded data produced no operator-visible error. The dashboard rendered cleanly; the numbers were just quietly wrong. This release adds a pytest suite so the pure-logic core has a safety net under it.

### Added

- **pytest suite at `tests/`.** 91 tests covering the six functions where silent regressions would actually corrupt trading decisions:
  - `test_r_math.py` — `j.compute_r` single-leg + partial fills + the entry-must-be-above-stop invariant. Drives every calibration metric the Phase-2 gate depends on.
  - `test_btfd_str.py` — full tier table for `_classify_btfd_str_shared` (equity + crypto, all three tiers each direction, edge cases). Pins the thresholds that the Action Rail and BTFD panel both reference, so they can never drift apart again.
  - `test_us_status.py` — Phase 1 status gating across P1_READY, blocked tiers, warnings, edge cases (missing SMA200, macro halt windows).
  - `test_llm_pcts.py` — relevance-weighted aggregation. Pins the weight constants (primary 1.0, mention 0.5, none 0.0), engagement-weighting interactions, all-off-topic fallback, backward compat for legacy classifications without the relevance field.
  - `test_company_label.py` — TICKER→company-name resolution across asset classes. Includes parametrized coverage over every watchlist ticker so no future watchlist add can land without a label.
  - `test_data_join.py` — symbol-keyed join regression test that documents both the correct pattern AND the bug pattern. The naïve-zip bug was found twice in production; the test will fail the moment anyone re-introduces it.
- **Test runner config (`pytest.ini`)** so `python3 -m pytest` works from the project root with concise output.
- **`tests/README.md`** documenting what's covered, what's intentionally out of scope (network calls, HTML rendering, LLM responses), and the contract for adding regression tests after future bugs.

### Changed

- **Hoisted `_classify_btfd_str_shared` + tier tables to module scope in `dashboard.py`** so they can be imported and tested. Previously the function was a closure inside `render_html`; now both the render closure and the test suite reference the same module-level definition. Aliases inside `render_html` keep the call sites identical.

### Fixed

- **`llm_pcts` backward-compat with pre-v2.0.4 classifications without `relevance`.** Previously the relevance counter (`n_primary`) reported 0 for legacy items even though they were correctly weighted at 1.0. Now normalizes missing/invalid relevance to "primary" at the start of `llm_pcts` so the weight and the count agree. Caught by `test_llm_pcts.py::test_missing_relevance_field_defaults_primary`.

---

## [v2.0.4] — 2026-06-10

Relevance-gate PATCH for the retail-sentiment classifier. v2.0.2 noted a tradeoff: relaxing the HN comment filter let real Solana coverage through, but also admitted noise like "Microsoft Project Solara" stories. The downstream classifier had no way to flag off-topic items — it scored every body as bull/bear/neutral, silently diluting the on-topic read. v2.0.4 closes that gap.

### Changed

- **Sentiment classifier (`sentiment_cache.classify_messages`) now returns a `relevance` field.** Schema is now `{relevance: "primary"|"mention"|"none", sentiment, conviction}` (same trichotomy as the news-glyph scorer). `llm_pcts` weights `primary` at 1.0, `mention` at 0.5, `none` at 0.0 — so off-topic items drop out instead of polluting the bull/bear/neutral percentages. Multi-ticker peer-mention posts ("$SOL.X + $MA = cool") count at half-weight instead of full. The aggregator now exposes `n_primary` / `n_mention` / `n_off_topic` per source so downstream UI can show how much real signal underlies a reading.
- **Classifier prompt now carries the company name, not just the ticker.** Same pattern as the v2.0.1 news-glyph fix. The LLM resolves `SOL → Solana (the L1 blockchain, NOT 'Solara' which is a Microsoft product)` and uses that to decide relevance. The lookup imports the existing `news_glyph.COMPANY_LABELS` map lazily — single source of truth for both scorers, no duplication.
- **`score_ticker` injects `asset_class` into all raw caches before processing.** StockTwits and Reddit fetchers already store `asset_class`; the HN fetcher didn't. Older HN caches now get the asset class inferred from ticker patterns (`.KL` → klse, BTC/ETH/SOL etc. → crypto, otherwise us) and injected at score time, so the company-label lookup works without requiring an HN cache rebuild.

### Fixed

- **Off-topic items no longer pollute the sentiment composite.** Before this fix, the SOL HN cache had 4 Microsoft Project Solara items that scored as neutral or low-confidence bull, diluting the genuine on-topic read. Validated end-to-end: SOL HN now reports 0 primary / 0 mention / 4 off-topic — correctly identifying "no real HN signal for SOL today" instead of falsely smoothing toward neutral. BTC HN shows 14 primary / 3 mention / 10 off-topic — bull/bear% now computed from the actual on-topic subset. SOL StockTwits shows 15 primary / 14 mention / 1 off-topic — multi-ticker chatter recognized and half-weighted.

---

## [v2.0.3] — 2026-06-10

Three correctness PATCHes the operator caught on their mobile review.

### Fixed

- **Action Rail BTFD/STR counts now match the actual panel.** Previously the rail used a simplified inline counter (`chg<=-2 + vol>=1.3` for equities; `chg<=-4` for crypto with no vol filter) that didn't match the panel's tiered classifier. Hoisted the BTFD/STR threshold tables and the `classify_btfd_str_shared()` function to `render_html` scope; both the rail and the panel now reference identical data so they can never drift on threshold tweaks. Likewise, FADE/BUY rail counts now require **technical alignment** (the same gate the Contrarian Setups panel enforces) instead of counting every contrarian-flagged ticker. Validated: rail and panel both report `2 BTFD / 2 STR / 0 FADE-aligned / 0 BUY-aligned` on the current cache.
- **BTFD/STR panel was silently dropping crypto candidates.** The panel iterated `zip(watchlist.crypto, crypto_rows)` — but `crypto_rows` comes back from CoinGecko in market-cap order, not watchlist order, so each crypto ticker got paired with the wrong row's chg/vol data. ENA (which qualified as crypto LIGHT_DIP at chg=-10.2%, vol=1.59×) was invisible because its watchlist entry got mismatched data. Same `_rows_by_sym` lookup pattern the crypto grid already used is now applied. ENA now correctly surfaces.
- **Mobile: expanded-row dropdowns no longer overflow horizontally.** Clicking a US/KLSE row to expand its thesis/gates/sentiment/news details was producing a 1543px-wide content panel on a 390px viewport (you had to swipe right to see anything). Root cause: the expanded `<tr>` lives inside the same `<tbody>` we gave `min-width: 1100px` for column legibility — so the expanded `<td>` inherited 1100px+. Fix: `.exp-details-content` now uses `position: sticky; left: 0; max-width: calc(100vw - 24px)` on mobile, so the content visually clamps to the viewport regardless of horizontal scroll position. The gates grid also collapses to single column so sections stack readably.

---

## [v2.0.2] — 2026-06-10

Mobile polish PATCH plus an HN-coverage audit fix. Two threads were addressed in this release.

### Fixed

- **Mobile layout: BTFD/STR rows reflowed.** The `bs-row` was a 5-column desktop grid (`130px 60px 50px 1fr auto`); on a 390px viewport the stats column was being squeezed into a ~40px right strip while tech context spanned full width — making rows nearly unreadable. Now on `≤780px` the row collapses to a wrapping flex layout: tier·ticker·class·name on line 1, then stats / tech / cross-signal on subsequent lines. Each value gets its own readable line instead of competing for ~40px.
- **Mobile layout: Contrarian Setup rows reflowed.** Was a 7-column grid (`30px 60px 70px 60px 1fr auto auto`) — worse than BTFD on mobile. Same fix pattern: wrapping flex, badge·flag·ticker·sim·class on line 1, stats and tech-note on their own lines, action and rationale span full width below.
- **Mobile layout: Risk Simulator form stacks vertically.** Was a 6-column grid (`1.4fr 1fr 1fr 1fr 1fr auto`) — labels and inputs were crammed into ~40px columns. Now flex-column on mobile: each label gets its own row, inputs are full-width with 14px font for tap accuracy, "🟣 Suggest" button is a full-width thumb target.
- **Action Zone label truncates cleanly on small phones.** The long form ("⚡ Today's Candidates — names that might warrant action right now") shows on desktop/tablet; on phones (`≤480px`) it shows just "⚡ Today's Candidates" rather than ellipsis-truncating mid-word.
- **HN sentiment cache: `num_comments>=3` filter was eliminating real coverage on niche tickers.** Audit found ETH/SOL/HYPE silently scored 0 stories despite being heavily HN-relevant — direct Algolia testing showed "Ethereum" returned 7 stories in the last 30 days *without* the comment filter, but 0 with `>=3`. Niche-ticker HN posts often sit at 1-2 comments. Lowered `MIN_COMMENTS_FILTER` from 3 → 1 (still drops zero-comment spam). After re-fetch: ETH 0→2 real stories, SOL 0→2, HYPE 0→1. Confirmed-empty names (CIFR, CLSK, KTOS — small-caps with no HN attention) correctly remain 0 instead of producing junk.
- **HN sentiment: RYDE marked skip to stop bare-ticker substring noise.** "Ryde" alone partial-matched across HN ("rideshare", URLs containing "ryde" segments) — Ryde Group is a Singapore micro-cap rideshare and the full company name gets no HN coverage. Mapped to `None` like SPY and EONR; cache now records `no_coverage=true` instead of 5 junk stories.

---

## [v2.0.1] — 2026-06-10

Quality PATCH addressing a silent miss the v2.0 news-glyph audit surfaced: ~80% of Chinese-language Bursa headlines were scoring `relevance=none / score=0.0` because the LLM scorer's prompt sent only the 4-digit Bursa code (e.g. `TICKER: 9431`) — semantically opaque, with no way to connect 9431 → Seni Jaya → 盛艺机构. The system prompt already invited "TICKER or commonly-known company name"; v2.0.1 actually delivers the company name in the prompt.

### Added

- **News-glyph LLM audit tool (`audit_glyph.py`).** Joins every cached LLM score to its source headline and auto-flags five failure modes: FALSE-NONE (ticker/name in headline but scored none), FALSE-PRIMARY? (scored primary with no apparent ticker/name reference), ROUNDUP? (sector-roundup headlines that should usually be 'mention'), NON-ASCII (likely non-English — verify model handled it), DIR-MISMATCH (crude keyword polarity vs LLM score sign disagreement). Excludes analyst-rating items (which legitimately omit the company name). Surface area: `python3 .claude/skills/us-news/audit_glyph.py [--ticker X --asset-class Y] [--flagged-only]`. Used to find and validate the KLSE fix; first pass scanned 2110 items across 25 tickers.

### Fixed

- **News-glyph scorer now passes company name to the LLM (not just the ticker code).** Added a `COMPANY_LABELS` map (`us`/`klse`/`crypto`) and threaded `asset_class` through `llm_score_items_for_ticker → _llm_score_batch`. KLSE entries carry both Latin and Chinese forms — e.g. `"9431": "Seni Jaya Corporation Berhad / SJC (also written 盛艺机构)"`. Before the fix: Chinese-press headlines for KLSE names silently scored `none/0.0`, dropping ~80% of the news signal for any Bursa name with substantial Chinese-press coverage. After the fix: validated on all 4 watchlist KLSE codes — Chinese-only relevant headlines now correctly score `primary` with non-zero values; unrelated Chinese headlines still correctly score `none`. US and crypto scoring unchanged (the model already knew AAPL=Apple, BTC=Bitcoin etc. from pre-training). The watch-thread "news-glyph LLM scoring quality" is downgraded from "tracking" to "monitor as watchlist evolves."

---

## [v2.0.0] — 2026-06-10

The action-first dashboard. v1.x was a research artifact — beautifully sourced, layered with confluence reads, but laid out in narrative reading order. You had to scroll past static context to find conclusions. v2.0 inverts that: the first screen now answers the only questions a trader needs to make a call — *what's my R:R floor right now*, *can I even trade*, *what setups are live today* — and the simulator that sizes the trade sits one eye-movement below them, not three scrolls away. Beyond the visual rework, v2.0 also closes the gap between *signal* and *logged trade*: a Finnhub-powered level watcher fires macOS notifications when prospectus triggers / stops / TPs print; a one-click Setup Queue turns any P1-ready name into a decision-ready prospectus draft with stop / TP / size math pre-computed; portfolio heat and calibration metrics now auto-derive from the journal instead of a hand-maintained file; and the whole thing renders cleanly on a phone via Tailscale.

Why **MAJOR** (per the project's semver policy): (1) the mental model an operator holds about the dashboard fundamentally changed — knowledge of "where is panel X" gets reclassified; (2) setup now spans new CLIs (`watcher.py`, `setup_queue.py`, `portfolio.py`, `mae_mfe.py`, `rel_strength.py`, `retired_scan.py`) and a new control server, so the "what to run" surface area is genuinely different; (3) decisions a v1.x dashboard would have framed (e.g. "should I trade right now?") would be reframed under v2.0 (Action Rail makes the answer immediate). v2.0 is backward-compatible — every v1.x CLI and the static `dashboard.html` build still work — but the everyday operator experience is materially different.

### Added — Visual layout (action-first)

- **Action Rail — sticky band at the very top of the dashboard.** Three slots answering the only questions a trader needs in two seconds: **R:R floor** (regime-derived: 1.5R / 2.0R / 2.5R), **Can I trade right now?** (next macro halt window with a red-pulsing 🛑 NO NEW ENTRIES badge when active, yellow when approaching, green when clear), and **Live setups today** (count chips for 🟢 P1_READY, 🔥 FADE, 🧊 BUY, 🩸 BTFD, 🚀 STR). `position: sticky` keeps it visible while you scroll. All numbers come from already-computed `ctx` — zero extra fetches.
- **Halt-window spotlight.** Replaced the 10-row uniform halt timeline with a 2-event spotlight panel: the imminent event renders large with countdown in hours/days, urgency colour (red+pulse inside halt window, yellow within 24h, neutral beyond), and an explicit `🛑 HALT WINDOW ACTIVE — NO NEW ENTRIES` pill that's impossible to miss. The full upcoming calendar collapses behind a `<details>` expander.
- **One-click `→Sim` from any setup or grid row.** Every US/KLSE grid row, every Contrarian Setup row, gets a small purple `→Sim` button next to the ticker. Click it and the Risk Simulator loads the ticker, prefills entry / 1.5×ATR stop / 2R TP1 / doctrine-max size, runs the full §5 gate, scrolls itself into view, and flashes purple. Crypto rows omit the button (sim is US+KLSE only this phase).
- **Tradability left-border on grid rows.** Status-coloured 3px inset border on the first cell of every US/Crypto row — green = P1_READY, yellow = WATCH tiers, red = blocked (DOWNTREND / NEAR_CPI / OVERBOUGHT), dim = CONTEXT (SPY) / DATA-missing. The sort by tradability is now self-explanatory: you can see *why* a row sits where it does without scanning to the 16th column.
- **Mobile layout.** Dashboard now renders cleanly on phones (≤780px) and very small phones (≤420px) via a viewport meta + a two-tier `@media` block. Above-the-fold on an iPhone-sized screen: Action Rail (three slots stacked vertically, still sticky) → Halt Spotlight (CPI card full-width with the 🛑 HALT pill on one line, FOMC compact secondary below) → Action Zone with Contrarian Setups starting at the fold. Big grids horizontally scroll inside their panel rather than collapsing into cards (preserves column relationships). Forms become single-column with larger touch targets. Sector strip horizontally scrolls. The floating control bar shrinks to a one-thumb width. `theme-color` meta is set so iOS Safari paints the title bar the dashboard background colour. Validated at 1440×900 / 768×1024 / 390×844 via Playwright. (For phone access on the same network: use Tailscale, or pass `--lan` to `server.py` to bind to 0.0.0.0.)

### Added — Execution loop (signal → logged trade)

- **Local control server for terminal-free operation (`server.py`).** Dashboard skill, stdlib-only, no new dependencies. Serves `dashboard.html` at `http://localhost:8787` with a control bar injected at serve time: ⚡ Quick refresh (prices/macro/Polymarket, background job with live log tail, page auto-reloads on completion), 🔄 Full refresh (adds LLM sentiment + news + news-glyph + discovery — always a manual press), a Watchlist form (wraps `wl.py add/remove/update`), and a Journal form (wraps `j.py live/update/close` + entry list). Launch by double-clicking **`Trading Dashboard.command`** in the project root. Hybrid auto-refresh policy: when the dashboard is >12h old, a quick refresh fires automatically once per browser session; LLM-scored sentiment never auto-runs. Binds to localhost only by default; `--lan` flag binds to 0.0.0.0 and prints the LAN IP for phone access (intended for trusted networks / Tailscale).
- **Level/alert watcher (`watcher.py`).** Polls Finnhub during US market hours and fires a macOS notification when a level prints that you'd otherwise have to be watching for: a PROSPECTUS entry-trigger break, a LIVE position's stop hit or TP1/TP2 touch, or a watchlist name entering the Phase-1 entry band (RSI 35-50 with trend intact, read from the dashboard cache). Each distinct alert fires once per day (deduped in a state file). Read-only and doctrine-clean — it never trades, never writes the journal; it just makes sure you're at the tape when the level hits. Start/Stop/Scan-now controls live in the server's control bar. `--once`, `--no-notify`, `--ignore-hours` flags for testing.
- **Setup Queue (`setup_queue.py`).** Finds watchlist names sitting in the Phase-1 band and turns each into a decision-ready prospectus draft with one click — ATR-based stop (1.5× ATR), 2R TP1, the §5 size math `(20000 × 2%) ÷ (entry − stop)` already computed, current portfolio heat passed in, written into `journal/` via `j.py new`. Surfaced as a panel in the server control bar ("Load candidates → Draft"). Cuts the friction from "P1-ready name" to "logged paper trade" so the 20-trade Phase-2 gate fills faster.
- **Auto-maintained portfolio heat + calibration (`portfolio.py`).** Derives live state from the journal (the source of truth) instead of a hand-maintained file that drifts stale: open-position heat (sum of $-at-risk across LIVE entries) vs the 6% ceiling, a sector-correlation grouping ("3 tech longs = 1 bet"), and closed-trade calibration (count, win rate, average R, cumulative R, R-distribution). `j.py live`/`close` now auto-regenerate `portfolio.md` on every status change. The dashboard's Portfolio Heat and Phase-2 gate cells read these live numbers, and a new **Portfolio & Calibration** panel shows open positions, the correlation warning, and the expectancy line.
- **MAE/MFE excursion tracking (`mae_mfe.py`).** A daily snapshot (run automatically on every dashboard build; no-op when flat) records how far each open position has run against you (max adverse excursion) and in your favour (max favourable excursion), in R. After 15-20 closes this is what tells you whether stops are too tight or targets too small. Surfaced as MAE/MFE columns in the Portfolio & Calibration panel.
- **Relative-strength column on the US grid (`rel_strength.py`).** Each US watchlist row shows its 1-month return vs SPY (green = leading, red = lagging), with 3-month and vs-sector-ETF spreads in the tooltip (e.g. "leading its sector"). Buying P1 pullbacks in leaders is one of the few robust retail edges. Computed via a single batched yfinance download (avoids the sequential-call pattern flagged in notes/learned.md), 4h TTL, refreshed alongside discovery.
- **Retired-name passive re-entry scan (`retired_scan.py`).** Names you moved to "Removed / retired" are still scanned for a *forming* constructive re-entry (RSI 35-55 AND within −5%..+10% of SMA50 — the technical half of the §4 🧊 BUY gate; a retail-capitulation extreme upgrades it to a full 🧊 BUY-aligned tag). They re-surface in a small **♻️ Retired — re-entry forming** panel only when the condition is met — no row clutter otherwise. Catches exactly the capitulation-reversal that names are often retired right before.

### Added — Development tooling

- **Playwright screenshot harness (`snap.py`).** Captures dashboard at three breakpoints (desktop/tablet/mobile) + per-component closeups in one command. Installed Playwright + Chromium into `.venv-playwright/` (project-local, isolated). Run with `.venv-playwright/bin/python3 .claude/skills/dashboard/snap.py` — produces `snaps/desktop_fold.png`, `desktop_full.png`, `mobile_fold.png` etc. Used during v2.0 layout iteration to catch issues a code-only review would miss (the watchlist autofocus scroll-jack was caught this way).

### Changed

- **Dashboard panel order is now action-first, not narrative-first.** New top-to-bottom flow: Action Rail → Halt spotlight → **Action Zone** (Contrarian Setups · BTFD/STR · Retired re-entry · Risk Simulator, all clustered inside a green-bordered region so see→size is one eye movement) → Active Prospectuses → US/KLSE/Crypto grids → Polymarket → Regime → compact account strip → Portfolio → Watchlist Manager → Discovery → News → Journal. Static reference data (KPI cards, regime factor breakdown, full event calendar) is demoted below the fold or behind expanders. The first screen is now setups + sim, not account totals.
- **Account KPI strip compacted from a 5-card grid into a single-line collapsible row.** `$20k · Phase 1 · Heat $0/$1,200 · P2 gate · AV news` all visible at a glance; click to expand for sub-text. The full-height KPI cards were "check-occasionally" data wearing "every-glance" weight. Reclaims the entire first screen for action.
- **Regime Read collapsed behind a headline summary.** The panel shows `US Macro: CAUTIOUS (-1.00) · Crypto: CONSTRUCTIVE (+1.30)` as the headline; the full signal-by-signal factor breakdown is one click away. Same `<details>` pattern, no information lost — but the everyday glance is now two scores instead of two lists.
- **US Equities and Crypto grids now sort by tradability, not watchlist order.** 🟢 P1_READY rows float to the top, WATCH/EXTENDED/OVERSOLD/NEW tier next, 🔴 DOWNTREND/BELOW50/NEAR_CPI/OVERBOUGHT rejections sink to the bottom, ⚪ CONTEXT (SPY) and ❓ DATA last.

### Fixed

- **Page no longer auto-scrolls past the Action Zone on load.** The Watchlist Manager's add-form ticker input was auto-focused on initial render, which caused Chrome to scroll-jack the viewport into the middle of the page (skipping the entire action-first layout above). Auto-focus now only fires when the user actually clicks a watchlist tab — not on first paint. Invisible to code review; caught only when Playwright took a fresh-load fold screenshot.

---

## [v1.10.1] — 2026-06-09

UX polish PATCH for the v1.10.0 release. Three small fixes that caught operator-attention immediately after shipping:

### Changed

- **Polymarket inline section: one row per event, not per market.** Each Polymarket event (e.g. "What will BTC price be on June 9?") contains multiple markets corresponding to outcome bands. v1.10.0 ranked markets globally by 24h volume, which often surfaced 3 different price bands of the *same* event as 3 separate rows — clutter without information. Now: one row per event using its `headline_question` (highest-probability outcome) with aggregate volume summed across all markets in that event. A multi-band BTC event collapses from 3 noisy rows to one clear modal read like `🟡 60% · Will BTC be between $62K-$64K on June 9? [$48K 24h vol]`.
- **Polymarket strict ticker matching, no junk fallback.** v1.10.0 had a "if no ticker-specific markets exist, fall back to any crypto-category market" rule, which produced nonsense like XRP's row showing BTC and ETH price-band markets. Now: crypto tickers without specific Polymarket coverage display an honest empty-state message — *"no XRP-specific Polymarket markets in cache. Generic BTC/ETH price-band markets exist but aren't useful confluence for this ticker."* No more cross-coin noise.
- **Retail Sentiment dropdown column is now scrollable**, matching the News column pattern shipped earlier in the day. With 4 sub-sections (StockTwits + Reddit + Hacker News + Polymarket) plus per-item lists, the column was running tall enough to crop bottom items when the parent grid forced height equality across columns. Now `max-height: 400px; overflow-y: auto` keeps it bounded, identical treatment to the News column.

### Fixed

- **`.gitignore` excludes `.agents/` auto-mirror.** Some agent-tooling auto-copies `.claude/skills/` into a parallel `.agents/skills/` tree (71 files, ~20K LOC). Identical content, includes `.env` files with real API keys, not source-of-truth. Now ignored so the harness's pending-changes badge stays clean and no accidental commit can leak the duplicates.

---

## [v1.10.0] — 2026-06-09

Sentiment-substance MINOR. Reddit comments — the meaty signal that lives below the OP — finally feed the LLM scorer; Polymarket "real money, not opinions" odds surface inline per ticker in the row dropdown; the `reddit_search_oauth` stub that's been silently broken since v1.5.0 is finally completed; one LLM-robustness fix that was making us silently drop entire sources when free-tier models miscounted batch size.

### Added

- **Reddit top comments now feed the sentiment scorer.** Previously each Reddit post was scored only on `title + first 200 chars of selftext`. Comment threads — often where the real opinion lives — were invisible. The fetcher now pulls up to 5 top-level comments per ranked post (OAuth path uses sorted-by-score for ranking; RSS path uses sorted-by-recency since RSS doesn't expose scores). For each post + comment, the LLM classifies sentiment; engagement-weighting applies normally on OAuth-sourced data and uses a uniform low floor for RSS-sourced comments (so they still get scored, just not boosted by upvote counts that we can't see without OAuth). Real-world validation on NVDA: scoring 10 posts + 50 comments shifted the Reddit signal from what would've been title-only-bullish to **26% bull / 40% bear / 34% neutral** — comments revealed a bearish undercurrent that titles alone missed.
- **Polymarket inline section in the row dropdown.** Every watchlist row's expand-panel now carries a `🪙 Money-backed (Polymarket)` line surfacing the top 3 real-money markets relevant to that ticker, ranked by 24h volume. Color-coded glyphs flag conviction direction (🟢 strong-yes ≥80%, 🟡 lean-yes ≥60%, ⚪ uncertain 40-60%, 🟠 lean-no ≤40%, 🔴 strong-no ≤20%). Crypto tickers get coin-specific markets (BTC price-target bands, ETH targets, etc.); US equities get macro context (Fed cuts, US recession); BTC-proxy equities (CLSK, CIFR, MARA, MSTR, etc.) get BTC markets first then macro. KLSE shows "no coverage" cleanly. Volume printed in `$NK` / `$N.NM` format so the operator can weight reliability — a 90% market on $1M volume is much more trustworthy than 90% on $5K.
- **Polymarket signals are intentionally NOT folded into the bull/bear% composite** — AGENTS.md §4 keeps Polymarket categorically distinct from forum/retail sentiment (additive macro confluence vs contrarian filter). Operator sees the money-backed read alongside the forum/HN reads and judges. Auto-folding would muddy the signal attribution.

### Changed

- **Reddit dropdown line now shows comment count + data-source caveat.** Reads `10 posts + 50 comments (of 25 total mentions, 60 scored)` with a hover-tip explaining whether engagement-weighting is active (OAuth) or uniform (RSS). Today's status on a fresh deployment: `[RSS — uniform comment weight]` — to unlock real upvote weighting, Reddit OAuth credentials need to land per the long-running carry-over thread.
- **`MAX_MESSAGES_PER_TICKER` bumped 25 → 60** in `sentiment-cache` to accommodate Reddit comment-tree scoring (10 posts × ~6 items each).

### Fixed

- **`reddit_search_oauth` was a stub.** The function fetched the JSON response from `oauth.reddit.com` but never parsed it or returned anything — it just fell off the end. That meant every Reddit fetch since v1.5.0 has silently fallen through to the RSS path, even when OAuth credentials would have been available. The engagement-weighting introduced in v1.9.0 was therefore a no-op on Reddit data (every post had `score=None` → `engagement=0` → weight=1 uniformly). Now the function parses `data["data"]["children"]` properly and returns posts with real `score` + `num_comments` fields. When you set up OAuth credentials, the dashboard will switch from "RSS — uniform comment weight" to "OAuth — per-comment scores live" automatically.
- **Reddit RSS post-ID parsing was failing on the current feed format.** The regex looked for `comments/POSTID/` in the entry id (the old `tag:reddit.com,2008:/...` URI format); today's feed returns `t3_POSTID` (Reddit "fullname" format). The parser now tries both regexes in order so it works across format changes.
- **LLM scoring no longer drops the entire source on batch-size drift.** Free-tier models (Gemma 4 31B) occasionally return more or fewer classification items than requested on larger batches (e.g. returned 64 for a 60-item input). The old code treated this as a hard error and returned `None` for the source, losing all the data. Now: over-production is truncated to the request length; under-production is padded with neutral classifications and a warning logged.
- **News dropdown now distinguishes "operator skipped this build" from "cache is genuinely missing".** Previously, running `dashboard.py --no-news-glyph` made every watchlist row's News dropdown say *"No news cache. Run `python3 .claude/skills/us-news/news_glyph.py refresh-us --...` to populate."* even when the per-ticker caches existed and were fresh. The message was misleading — the cache wasn't missing, the operator had explicitly opted out of loading it for this build. Now: when `--no-news-glyph` is in effect the dropdown clearly reads *"News glyph disabled for this build (`--no-news-glyph` flag was passed). Re-run the dashboard without that flag to load the cache."* The genuine-missing-cache message also got refreshed to point at the dashboard's 📰 News refresh button as the easier alternative to a manual CLI invocation.

### Removed

### Deprecated

### Security

---

## [v1.9.1] — 2026-06-09

Discovery tightening + silent-stale-cache bug fix PATCH. Four qualification thresholds on the screener tightened in one pass to make the Discovery panel show only genuine investment-grade candidates instead of noisy P1-technical-only names; one real bug fix to surface and prevent the cooldown lockout that was silently freezing the Discovery cache for up to 45 minutes after a single transient data-fetch blip. Validated end-to-end: 9 P1-passers under the old rules collapsed to 1 high-quality fresh name (NVDA, 5/5 quality with a textbook 38-48 RSI pullback on a rising trend) under the new ones.

### Changed

- **Discovery panel: tighter qualification, less noise.** Four screener thresholds tightened in one pass to reduce the number of marginal "discoveries" cluttering the panel and to push out names that don't earn an investment thesis:
  - **A. ⚡ TECH tier no longer emitted as a Discovery candidate.** Names that pass the P1 technical setup but have neither Buffett quality (≥4/5 gates) nor value (≥2/3 gates) support are now counted in `p1_passers` for diagnostics but excluded from the Discovery panel. The ⚡ TECH tag still exists for `--tech-only` runs where fundamentals aren't fetched; in regular runs it's gone.
  - **B. 💰 VALUE tier requires Q≥3/5 minimum.** A "cheap" name with quality 0-2/5 was previously eligible for the VALUE tag — that's a classic value-trap risk. Now VALUE candidates must also clear a minimum quality floor (3/5) on top of the value bar (2/3).
  - **C. P1 RSI band tightened 35-50 → 38-48.** The old loose band let names sitting at the neutral-50 edge through (often weak setups still chopping sideways). 38-48 = a clearer pullback into the buy zone without buying tops.
  - **D. SMA50 slope must be ≥ 1%/5d (was `> -0.5%`).** Previously a near-flat or slightly-falling SMA50 still passed the "trend OK" check. Now requires actual upward momentum in the medium-term — structure alone isn't enough.
  Combined effect: Discovery shows fewer but better-qualified candidates. Today's run produced 9 P1-passers under the old rules; under the new rules the count drops sharply (verified post-rebuild).
  Also added a **defensive render-time filter** in the dashboard: even if a `candidates.json` cached under the old criteria still sits on disk, the panel applies all four current rules at read time, so stale-cache entries that no longer qualify never leak through. The cache itself gets rewritten cleanly on the next screener run.

### Fixed

- **Discovery silently-stale-cache bug.** Two changes that fix the failure mode where Discovery appeared to be updating but was actually serving a 30+ hour old `candidates.json`:
  - **Screener cooldown is now post-failure-only, not preemptive.** The old logic set the cooldown file BEFORE the bulk technicals fetch ("proactive — if the process is killed mid-fetch, future runs see it") and cleared it only if at least one ticker fetched successfully. Failure mode that bit us: every per-ticker call errored individually (transient Twelve Data blip). `fetched` stayed 0, cooldown stuck for 45 min, every subsequent dashboard refresh silently served the stale cache. Now: cooldown only sets on actual fatal errors (rate-cap, auth) or on `KeyboardInterrupt` / `SystemExit`. Per-ticker errors are logged but don't trigger lockout. Cooldown duration also reduced from 45 min → 10 min so transient blips don't camp on the cache for the better part of an hour.
  - **Dashboard surfaces silent-staleness now.** The Discovery panel previously trusted the cache without checking age. If `_last_full_pass_at` is older than the 18h TTL, the panel header now shows `⚠ STALE — last full pass Xh ago` with a hint that a recent run errored. If the cooldown file is active, it shows `🥶 screener cooldown active (N min remaining)` so you can see *why* refreshes are being suppressed and override with `--force`.

**Other carry-over threads (unchanged from v1.7.0):**
- **Reddit OAuth upgrade pending.** Same status since v1.5.0 — RSS workaround running fine; OAuth path auto-activates when `REDDIT_CLIENT_ID`/`SECRET` land in `.claude/skills/reddit-sentiment/.env` after Reddit's developer-app review (2-4 weeks total). Will cut as a PATCH once verified.
- **Threshold calibration watch.** v1.5.0 fired 4 FADE flags; v1.6.0's Contrarian Setups panel narrowed to 2 actionable setups (CIFR, PURR); v1.7.0 BTFD detector fired 4 LIGHT DIP candidates on first run. Want a few weeks of operator use across changing market regimes to confirm thresholds (sentiment 0.80/0.70 + alignment, BTFD/STR equity/crypto tiers) are calibrated correctly.
- **News-glyph LLM scoring quality watch.** v1.8.0's LLM-attributed news sentiment fixed the KTOS-style cross-attribution problem in spot tests (Axon-headline false positive cleared, Kratos-name primary subject correctly detected). Want a few weeks of varied news flow to confirm the Gemma 4 31B / GPT-OSS 120B free-tier models hold up on edge cases (non-English KLSE headlines, sector roundups, ambiguous bank-of-companies headlines). Tracking 429s / fallback frequency in the score logs.
- **HN coverage + 1.2× source weight calibration watch.** v1.9.0's HN-as-third-leg validated cleanly on RDDT (substantive HN comments pulled composite from BULL → NEUTRAL where Reddit + StockTwits diverged from technical reality). Want a few weeks across the watchlist to confirm: (a) the 1.2× HN source weight is right (not over- or under-correcting vs forum signal), (b) tech tickers consistently get coverage and non-tech ones cleanly degrade to "absent", (c) the curated `TICKER → company name` map doesn't need tuning for new watchlist adds. Treat any composite swing > 20% bull% caused purely by HN as a calibration data point.

### Added

### Changed

### Fixed

### Removed

### Deprecated

### Security

---

## [v1.9.0] — 2026-06-09

Sentiment quality MINOR. Two changes that compound: a third retail-sentiment source (Hacker News, via free Algolia API) joins Reddit + StockTwits as the **less-gameable leg** of the §4 composite, and **all three sources** now weight individual posts/comments/messages by engagement (`1 + log1p(upvotes_or_likes)`) instead of treating every item equally. Hot signal travels with the message's audience; gameable low-engagement noise fades. Real-world validation on RDDT this session: the addition of HN's substantive technical comments pulled a composite that Reddit + StockTwits would have called BULL back to a correct NEUTRAL — exactly the contrarian-filter use case.

### Added

- **Hacker News as a third retail-sentiment source.** New `hn-sentiment` skill (`.claude/skills/hn-sentiment/hn_sentiment.py`) pulls per-ticker stories and top comments from the free Algolia HN API (no auth) into `.claude/cache/hn_sentiment/{TICKER}.json`. HN is typically more substantive than Reddit/StockTwits chatter — fewer participants, much higher per-comment information density — so it earns a **1.2× source weight** in the composite as the less-gameable leg. A curated `TICKER → company name` map handles HN's company-name addressing (HN talks about "Reddit", "Nvidia", "Bitcoin", not "RDDT", "NVDA", "BTC"); unknown tickers fall back to the symbol. KLSE codes are auto-skipped (zero HN coverage on Bursa names). Real-world validation on RDDT this session: Reddit + StockTwits skewed bullish (~63% bull average) while HN substantive comments scored 75% neutral / 24% bearish, pulling the composite back to a clean NEUTRAL — exactly the contrarian-filter case the third leg was added for.
- **Engagement-weighted sentiment scoring** across all three retail sources. Previously each Reddit post / StockTwits message / HN comment counted equally in the LLM-conviction-weighted aggregate. After: each item's contribution is multiplied by `1 + log1p(engagement)` where engagement is upvotes + 2× comment count (Reddit), likes + 2× reshares (StockTwits), or comment points (HN). A 1000-upvote WSB thesis post now contributes ~8× more than a 0-upvote one; gameable low-engagement spam fades. Curve is logarithmic so a single viral 50k-upvote post can't drown out the rest of the sample. The new `engagement_weighted` flag on each source summary signals the change in stored caches.
- **HN line in the Retail Sentiment dropdown.** Every watchlist row's expand-panel now shows a third "Hacker News" sub-line alongside StockTwits and Reddit, with story count, bodies scored, total engagement, and per-source LLM bull/bear/neutral breakdown. The "Retail Sentiment" column header in the dropdown carries an "(engagement-weighted)" hint.

### Changed

- **`sentiment-cache` is now a 3-source aggregator.** The orchestrator (`score_ticker`) reads Reddit + StockTwits + Hacker News raw caches and composes a single composite. Source weights: ST 1.0, Reddit 1.0, HN 1.2. Stored cache schema gains `sources.hackernews` and `composite.engagement_weighted=true`. The dashboard's `_refresh_sentiment_for` chain runs `hn-sentiment` as a new step between `stocktwits-sentiment` and the LLM scorer.

### Fixed

### Removed

### Deprecated

### Security

---

## [v1.8.0] — 2026-06-09

News-as-confluence MINOR. The §4 professional-news leg moves from "fetch on demand via a skill" to a **per-row glyph on every watchlist row** with full headline drilldown — and that glyph is now driven by LLM-attributed sentiment, not keyword regex, so cross-attribution false positives (a peer-company headline mentioning your ticker in the body) finally clear cleanly. Hourly source-fetch TTL; per-item LLM-score cache is immutable (headlines don't change) so OpenRouter spend is essentially zero after warmup. Header refresh button becomes a 3-option dropdown (Quick / News / Full) to make the refresh contract explicit.

### Added

- **Per-row news glyph (Retail / News column).** Every watchlist row now shows a 72h news-direction indicator — 🟢 net bullish, 🔴 net bearish, ⚪ neutral / mixed / no fresh news — with an ❗ modifier when a fresh analyst rating action (upgrade / downgrade / initiate / reiterate) lands inside the 72h window. The full headline list (72h items + older context) renders in the row's expanded dropdown. The ❗ items carry an inline caveat reminding that analyst calls are ~50% accurate at the 12-month horizon and don't substitute for confluence (AGENTS.md §4).
- **LLM-scored news sentiment with per-item permanent cache.** News items are immutable — once a headline is published its sentiment doesn't change. The news glyph now LLM-scores every Finnhub / klsescreener / RSS headline via OpenRouter free models (Gemma 4 31B IT primary, GPT-OSS 120B fallback — same key as `sentiment-cache`) and banks the result keyed by `hash(headline)`. Re-fetches only re-score the truly new items (usually 1-5), so the OpenRouter spend is essentially zero after the first warmup. The LLM also returns a `relevance` field (`primary` / `mention` / `none`) which solves the cross-attribution problem keyword scoring couldn't — e.g. an "Axon Rises 23.3%" headline that lists KTOS in the body is correctly tagged `relevance=none, score=0.0` for KTOS, while "AeroVironment and Kratos Stocks Trade Down" is tagged `relevance=primary, score=-0.50` because the LLM recognizes the company name. Alpha Vantage items keep their pre-attributed `ticker_sentiment_score` — AV already solves attribution properly.
- **Hourly source-fetch TTL.** The dashboard's auto-fetch for news glyph data defaults to 1 hour (was 12h), matching how fast news flow changes. The expensive part — LLM scoring — is amortized over the immutable per-item cache, so the hourly cadence is cheap. New CLI `python3 .claude/skills/us-news/news_glyph.py score --tickers ... --asset-class us` lets the operator manually re-score without re-fetching (and `--force` busts the per-item cache for targeted re-scoring).
- **News sources, all asset classes:**
  - US: yfinance `.upgrades_downgrades` for structured analyst actions (Finnhub's structured upgrade-downgrade endpoint is paywalled — pivoted) + Finnhub `/company-news` for recent headlines + the existing Alpha Vantage `us-news` cache for pre-scored sentiment.
  - KLSE: scraper for klsescreener.com/v2/news/stock/{code} parses the per-stock news page (urllib + regex, no WebFetch).
  - Crypto: aggregate-feed RSS from CoinDesk, Cointelegraph, and Decrypt — filtered by per-coin keyword (BTC/ETH/SOL/BNB/XRP/HYPE and other watchlist names). Long-tail alts with no RSS mention render ⚪ no-news-in-72h, which is accurate degraded behavior, not a bug.
- **New `finnhub` skill.** The existing `finnhub_client.py` (bare client, no SKILL.md) gained `company_news()` and `upgrade_downgrade()` methods plus its first SKILL.md documenting current usage (sector rotation, screener, live-quote button, news glyph).
- **CLI flags on `dashboard.py`:** `--refresh-news-glyph` pulls fresh per-row news data across all asset classes (free, ~60s for a typical watchlist); `--no-news-glyph` skips the glyph column entirely if a source is misbehaving.

### Changed

- **Header ↻ Refresh button is now a 3-option dropdown** — the old single button silently did a *minimal* refresh (cache-only for news + glyph + sentiment), which was confusing once those layers got expensive. New dropdown choices:
  - **↻ Quick refresh** — current minimal behavior. Rebuilds from caches; only fetches what's expired. ~10-15s. Use for mid-day re-looks.
  - **📰 News refresh** — Quick + pulls fresh AV news, Finnhub headlines, klsescreener KLSE news, crypto RSS, and LLM-scores any new items. ~30-60s. Use after a news catalyst.
  - **⟳ Full refresh** — News refresh + retail sentiment + Polymarket + `--force` re-fetch on every cached source. Several minutes on cold caches. Use at the start of a session or after a major event.
  Each option copies its command to the clipboard with a "Copied — paste in terminal" toast. Per-row 🔄 buttons (live-quote fetches) stay separate as before.
- **Retail column header is now "Retail / News"** on US, KLSE, and crypto panels. Tooltip explains both signals — the existing retail sentiment composite (Reddit + StockTwits, LLM-scored) and the new news-direction glyph.

### Fixed

### Removed

### Deprecated

### Security

---

## [v1.7.1] — 2026-06-08

Audit + cleanup PATCH. Spun up four parallel review agents (visual/CSS, formatting/TZ, doctrine/text, code health) and fixed everything actionable they found, plus dead code from the v1.5.0 Reddit OAuth refactor that the code-health agent caught.

The headline operator-impacting fix: every absolute UTC timestamp on the dashboard now reformats into the viewer's browser timezone (continuing the v1.7.0 "Built at" pattern across `fmt_fetched()` chips, macro halt-window event times, and the row-level fetched-at stamps).

### Changed

- **Doctrine RSI band internal consistency.** AGENTS.md §4 narrative prose said BUY-aligned sentiment requires `RSI 35-50` (the P1 entry band) while the same section's threshold table said `RSI 35-55` (the sentiment-aligned band). Clarified the prose to match the table and explicitly distinguish the two bands.
- **Phase A/B/C/D naming retired from active skill descriptions.** Renamed "Phase A" / "Phase B" references in `reddit-sentiment`, `stocktwits-sentiment`, `sentiment-cache`, `polymarket-events`, and `dashboard` SKILL.md files to descriptive prose ("retail-sentiment build", "macro-confluence leg", etc.). The build phases were transitional labels during the v1.5-v1.6 buildout and collided cognitively with AGENTS.md §7's operational ramp "Phase 1 / 2 / 3" naming. Historical CHANGELOG entries left intact as a record.
- **BTFD/STR LIGHT-tier emoji.** Renamed `📉 LIGHT DIP` → `⬇️ LIGHT DIP` and `📈 LIGHT RIP` → `⬆️ LIGHT RIP`. The old emojis collided with the retail-sentiment column's `📈 BULL` / `📉 BEAR` badges; same row could show both with opposite meanings. Arrows are unambiguous.
- **Sentiment contrarian-cell tint.** `.sent-fade` and `.sent-buy` background opacity bumped from 0.08 (near-invisible against dark theme) to 0.16, plus a 0.6-opacity left border to match `.b-red` / `.b-green` visual weight.

### Fixed

- **Contrarian Setups grid misalignment.** `.cs-row` CSS declared 6 grid columns but each row HTML had 7 children — the 7th (`.cs-tech`) was wrapping to a second grid row, breaking visual alignment of stats and tech-context cells. Grid template fixed to 7 columns.
- **Viewer-timezone reformat now covers every absolute UTC timestamp, not just "Built at".** Macro halt-window event times (rendered as `Jun 8 (Wed) 14:00 ET` server-side) and every `fmt_fetched()` chip across the dashboard now embed a `data-utc` attribute and get rewritten in the viewer's local timezone via `Intl.DateTimeFormat` on page load. ET / UTC source-of-truth strings preserved as tooltips so the original numbers are still discoverable.
- **Earnings-date column tooltip clarifies timezone semantics.** Adds a `title` explaining the date is the company's local calendar date (typically NY for US listings), not a UTC instant. The `(Xd)` countdown is days from today UTC.
- **Reddit-sentiment dead code removed.** ~20 lines of unreachable code in `reddit_search()` left over from the v1.5.0 OAuth/RSS refactor that I forgot to delete (caught by the code-health audit agent).
- **Polymarket `_apply_deltas` defensive `.get()`.** The delta-calc loop was using direct dict-indexing on `current["categories"]["events"]["markets"]` — would `KeyError` mid-pass if the Polymarket schema shifts or a prior snapshot is malformed, even though the current fetch succeeded. Now uses `.get(..., {})` / `.get(..., [])` defaults.
- **Subprocess error handling.** `subprocess.run(["open", str(OUTPUT_HTML)])` at end of dashboard build now wrapped in try/except so a failed `open` doesn't crash the post-render cleanup. Sentiment auto-fill subprocess gets `subprocess.TimeoutExpired` handled separately from generic exceptions so the operator sees an actionable message when the OpenRouter call exceeds the 300s budget.

---

## [v1.7.0] — 2026-06-08

Price-volume event detection + viewer-timezone dashboard. The dashboard gains a new top-of-page "🩸 BTFD / 🚀 STR" panel that surfaces watchlist names showing large 24h moves on outsized volume — Buy The F***ing Dip candidates for entry review and Sell The Rip candidates for profit-take/trim review. Asset-class-aware thresholds (crypto wider since it moves 2-3× bigger normally). Cross-signals from the existing sentiment, halt-window, and earnings infrastructure layer in inline as boosts/warnings without overriding the tier classification.

Two operator-reported bugs fixed in the same release. The crypto grid's live-quote button was returning the wrong coin's quote — a `zip(watchlist, crypto_rows)` pairing bug where CoinGecko market-cap order didn't match watchlist declaration order. The dashboard's "Built at" timestamp was anchored to UTC instead of the viewer's local timezone — now reformatted in-browser via `Intl.DateTimeFormat`, future-proof for when the dashboard is built on one host and viewed from another.

### Added

- **🩸 BTFD / 🚀 STR — Price × Volume Setups panel.** New dashboard panel between Contrarian Setups and the US grid. Surfaces watchlist names showing large 24h moves on outsized volume (≥30-day average), with three severity tiers per direction. Asset-class-aware thresholds — crypto wider since it moves 2-3× bigger normally.
  - **BTFD candidates** (potential dip-buy entry review): 🩸 CAPITULATION (equity -7%/2.5×vol/RSI≤30; crypto -12%/3×/RSI≤25), 💧 REAL DIP (equity -4%/1.8×/RSI≤40; crypto -7%/2×/RSI≤35), 📉 LIGHT DIP (equity -2%/1.3×; crypto -4%/1.5×).
  - **STR candidates** (potential profit-take / trim review on existing longs): symmetric thresholds — 🚀 BLOW-OFF, 💸 REAL RIP, 📈 LIGHT RIP.
  - Each row shows: tier badge, ticker, asset class, actual %/vol/RSI/ATR-multiple, technical context (vs SMA50/SMA200), and inline cross-signal boosts/warnings — 🧊 BUY sentiment on a BTFD-flagged name, 🔥 FADE sentiment on a STR-flagged name, halt-window proximity (FOMC/CPI/NFP within 24h), earnings within 24h.
  - First run on the watchlist: 4 LIGHT DIP candidates (MRVL -16.7%, PURR -10.1%, RYDE -9.8%, 7241.KL -2.5%). Notable: PURR's dip arrives on a name that already had a 🔥 FADE sentiment flag — the price action is confirming the contrarian read.
- **AGENTS.md §4 Technical subsection** gains a brief mention of the BTFD/STR detector — frames it as a "where to look" tool that generates candidates for review, with confluence still required before any entry.

### Changed

- **Crypto grid now displays in watchlist declaration order** (BTC, ETH, SOL, BNB, XRP, HBAR, HYPE, ENA) instead of CoinGecko's market-cap order. The previous order was a side-effect of the underlying API response and was the root cause of the live-quote-mismatch bug below.
- **Dashboard "Built at" timestamp now reformats in the viewer's browser timezone** via `Intl.DateTimeFormat`. Static-HTML-compatible: the UTC ISO is embedded as a data attribute, JS replaces the text on page load. Future-proof for when the dashboard is built on one host (e.g. UTC server) and viewed from another (e.g. GMT+8). Server-local fallback preserved as small dim text in parentheses.

### Fixed

- **Crypto live-quote button returned the wrong coin's quote.** Bug: the grid did `zip(watchlist["crypto"], crypto_rows)` but `crypto_rows` came back from CoinGecko in market-cap order, not watchlist order — so the row labeled "BTC" was paired with ETH's indicator data, "ETH" got SOL's, etc. The 🔄 button's `data-crypto-symbol` carried the wrong symbol and the fetched quote came back for the wrong coin. Fix: build a symbol→row index from `crypto_rows` and look up each watchlist entry by ticker so every row's button reliably carries its own coin's symbol. (Reported by operator.)

Phase D — sentiment × technical alignment. The doctrine's §4 contrarian filter is now operationalized as a top-of-page dashboard panel that surfaces only the watchlist names where retail sentiment flags coincide with the underlying technical state. Pure sentiment flags without technical alignment stay informational (per-ticker Retail column); they're no longer presented as setups. The §4 doctrine gains an explicit three-leg framing — professional news (additive), retail forums (contrarian filter), prediction markets (additive macro confluence) — making clear that the three sentiment layers answer categorically different questions and must not be collapsed into a single number.

Phase C (Google Trends via pytrends) was dropped after honest reassessment: pytrends is brittle (frequent Google-side breakage), adds a pip dependency against the project's urllib-only norm, and the signal it would provide is largely redundant with what StockTwits watcher counts + Reddit mention velocity already give us. The Phase C slot remains open for a future durable attention-velocity source.

### Added

- **"⚠ Contrarian Setups" dashboard panel.** Placed between Risk Simulator and the US grid for visibility. Surfaces only watchlist names where a retail-sentiment contrarian flag (🔥 FADE / 🧊 BUY) *aligns with the underlying technical state*:
  - 🔥 FADE-aligned = `bull_score ≥ 0.80` + `conv ≥ 0.70` AND (RSI > 70 OR > 8% above SMA50). Action: downgrade conviction one tier on existing long setups.
  - 🧊 BUY-aligned = `bear_score ≥ 0.80` + `conv ≥ 0.70` AND (RSI 35-55 AND -5% ≤ vs SMA50 ≤ +10%). Action: upgrade conviction one tier on existing P1 long setups.
  
  Each row shows badge, ticker, asset class, sentiment stats, the specific technical condition that triggered alignment, the recommended action, and the full LLM rationale. First run on the production watchlist fired 2 setups (🔥 CIFR at +18% vs SMA50, 🔥 PURR at +25% vs SMA50). The other 2 v1.5.0-era FADE flags (KTOS, RGLD) correctly filtered out — KTOS is in a downtrend (not extended), RGLD's RSI/vs-SMA50 didn't clear the threshold. This is the filter doing its job: surfacing actionable setups, not every flag.
- **AGENTS.md §4 three-leg sentiment aggregation framing.** Explicitly tabulates the three sentiment layers (professional news → additive; retail forums → contrarian filter; prediction markets → additive macro confluence) and codifies the operational rule: **sentiment modifies conviction on existing setups; it does not generate setups by itself.** The Contrarian Setups panel is the operational expression of this rule. KLSE coverage caveat documented (most KLSE entries will show `— UNKNOWN` because forum coverage is sparse — degraded behavior, not a bug).

### Investigated, no action

- **Dead-subreddit audit (carried over from v1.5.0 in-flight).** Probed all 17 subreddits in the `reddit-sentiment` routing table against both `/new.rss` and `/search.rss` with our actual query terms. All responded with 200 OK. The earlier 404s on `binance`, `Ripple`, `ethena_labs` during v1.5.0's first refresh were transient (Reddit edge-cache hiccups). No code or config changes needed.

### Deferred

- **Phase C — Google Trends / attention-velocity signal.** Dropped during planning after honest reassessment. The Phase C slot remains open for a future durable source if one emerges (Wikipedia Pageviews was considered as a non-scraping alternative; tabled for now).

---

## [v1.5.0] — 2026-06-08

Sentiment + prediction-market confluence layer. The doctrine's §4 sentiment leg gained two new primitives:

1. **Retail forum sentiment as a contrarian filter** (Phase A) — Reddit + StockTwits raw fetchers, LLM-scored via free OpenRouter models, composited into per-ticker 🔥 FADE / 🧊 BUY flags when retail is uniformly crowded one-sided. First scored refresh fired 4 FADE flags (PURR, KTOS, RGLD, CIFR) — concrete evidence the contrarian gate has bite.
2. **Polymarket implied probabilities as macro confluence** (Phase B) — money-weighted speculator consensus on Fed cuts, recession, inflation, BTC/ETH price ranges, geopolitics. Different from forum sentiment because participants put cash on outcomes — less gameable, treated as additive macro confluence rather than contrarian fade.

The dashboard surfaces all of this: a new "Retail" column on the US, KLSE, and crypto grids, a per-row sentiment block in the expand-on-click dropdown, and a top-of-page "Event Probabilities" panel with the Polymarket reads grouped by category.

### Added

- **Retail-sentiment layer (Phase A).** New `reddit-sentiment`, `stocktwits-sentiment`, and `sentiment-cache` skills bring retail-forum sentiment into the doctrine as a **contrarian filter** (per §4). Raw fetchers collect posts/messages; the cache layer LLM-scores them via OpenRouter free models (Gemma 4 31B IT primary, GPT-OSS 120B fallback — no metered API spend) and produces a composite per-ticker read with two flags: **🔥 FADE** (`bull_score ≥ 0.80` + `conviction ≥ 0.70`, retail crowded long → downgrade conviction on extended technicals) and **🧊 BUY** (mirror for capitulation + constructive P1). KLSE entries gracefully render `— UNKNOWN` (sparse forum coverage is expected, not a bug).
- **Reddit access via RSS workaround.** Reddit blocked unauthenticated JSON in 2023 but left Atom/RSS open. The skill defaults to RSS (no credentials needed) and transparently upgrades to OAuth when `REDDIT_CLIENT_ID`/`SECRET` are present in `.env`. Score and comment-count fields are unavailable via RSS but title + body excerpts are sufficient for downstream LLM scoring.
- **"Retail" column in the dashboard.** New sortable column on the US, KLSE, and crypto grids showing the composite badge + bull%. Pink-tinted cells flag FADE; green-tinted flag BUY. Hover tooltip carries the full rationale (bull/bear/conviction breakdown + source attribution + flag explanation).
- **Sentiment block in dashboard row dropdowns.** Each row's expand-on-click details panel now includes a third "Retail Sentiment" column alongside the existing P1-gates and Status-decision columns, showing per-source (Reddit + StockTwits) message counts, user-tagged-vs-LLM bull/bear/neutral percentages, LLM conviction, and the contrarian-flag explanation.
- **AGENTS.md §4 retail-sentiment subsection** codifies the contrarian-filter doctrine, including the conviction-gate rationale — the LLM safeguard against gameable self-reported badges. Concrete example preserved: AUPH 100% user-tagged bull on StockTwits but 64% LLM conviction → no FADE flag, because the message bodies were hedgier than the badges suggested.
- **Dashboard auto-fills sentiment for newly-added watchlist tickers.** Add a ticker via `wl.py add` (or by editing `watchlist.md`), run `dashboard.py`, and the new name's retail-sentiment column populates automatically — the dashboard detects missing-from-sentiment-cache tickers and subprocesses the reddit/stocktwits/scorer chain just for those names. New flags: `--refresh-sentiment` force-refreshes ALL watchlist tickers; `--no-sentiment` skips the auto-fill (e.g. if Reddit RSS or OpenRouter is down).
- **Polymarket prediction-market layer (Phase B).** New `polymarket-events` skill fetches implied probabilities from Polymarket's Gamma public-search API (no auth, free). Curated queries across 4 categories (macro_rates, macro_econ, crypto, geopolitics) pull event probabilities like "How many Fed rate cuts in 2026?" (80% no cuts), "US recession by end of 2026?" (18%), "Fed Decision in June?" (99% no change), and BTC/ETH price ranges. Stores historical snapshots for Δ7d computation. Noise filter drops occasional meme-market pollution (`GTA VI` / `Jesus return` / etc.) that sneaks through serious queries.
- **"Event Probabilities" panel on the dashboard.** New 4-column panel near the top (alongside macro regime + halt-window timeline) showing tracked Polymarket events grouped by category. Each row shows probability (color-coded: green ≥75%, yellow 25-75%, red ≤25%), title (clickable through to Polymarket), and Δ7d arrow when historical snapshot is available. Sorted within category by extremity (decisive markets first).
- **`--refresh-polymarket` flag on dashboard.py** for one-command refresh of the macro confluence layer (~5s, no auth).
- **AGENTS.md §4 prediction-market subsection** documents how Polymarket signals slot into the doctrine — additive macro confluence (not contrarian fade), with explicit treatment of aligned-vs-diverged-vs-uncertain cases, plus the §5 halt-window framing connection.
- **🗑️ Remove button on each watchlist row.** Each US/KLSE/crypto row gains a small trash icon next to the chevron. Click → browser prompts for a one-line removal reason (required by doctrine, surfaces in the watchlist's audit trail) → builds the `wl.py remove TICKER -r "REASON" --yes` command and copies to clipboard for terminal paste. Dashboard remains fully static HTML — this follows the same copy-then-paste pattern used by the Refresh button and prospectus actions. Falls back to a `prompt()` dialog showing the command if clipboard write is blocked.

### Changed

- **`dashboard.py` row-detail layout** moved from a fixed 2-column grid to `repeat(auto-fit, minmax(280px, 1fr))` so the new Retail Sentiment column flows alongside P1 gates + Status on wide screens and wraps gracefully on narrow viewports. Colspans bumped from 13→14 (US) and 14→15 (KLSE + crypto).

### Fixed

- **Watchlist parser** in both `reddit-sentiment` and `stocktwits-sentiment` was treating the literal placeholder ``\`TICKER\``` from the watchlist's `Format:` example line as a real ticker. Now explicitly skipped alongside italicized section markers.

---

## [v1.4.1] — 2026-06-08

Versioning policy update. The project now uses full semver (`MAJOR.MINOR.PATCH`) instead of two-level `MAJOR.MINOR`. Pure docs change — no behavior, no code.

### Changed

- **Versioning policy** in `CHANGELOG.md` rewritten as `MAJOR.MINOR.PATCH` (semver). Decision rules, edge cases, and release-cut threshold codified upfront so future release calls don't depend on judgment-in-the-moment. PATCH releases (e.g. v1.4.1) are now distinct from MINOR releases (v1.5.0) — small fixes no longer burn MINOR slots. Historical tags v1.0 through v1.4 are not renumbered; v1.2 (README clone URL fix) would have been v1.1.1 under the new rules but stays as it shipped to preserve link integrity.
- `README.md` Changelog section gains a one-line mention of semver.
- `notes/decisions.md` records why we adopted semver mid-project (sharp operator question after v1.4 noticed several minor releases were really patches).

---

## [v1.4] — 2026-06-08

Session-continuity infrastructure. New agent sessions auto-orient before responding, so neither operator nor agent loses context across `/clear`s, fresh sessions, or returning days later. Plus a defensive trace in the screener so the next time a subprocess dies mid-loop we have actionable data instead of guessing.

### Added

- **Auto-bootstrap on session start** (`CLAUDE.md` + `AGENTS.md`). When Claude Code or Codex opens this project, the agent reads `notes/learned.md` + `CHANGELOG.md [Unreleased]` + `git log --oneline -10` *before responding to the operator's first message*, then orients in 3 short lines (current version / last shipped change / anything in flight). Cost: ~5 seconds; operator typing required: zero. Prefix the first message with `quick:` or `oneshot:` to skip for one-off unrelated questions. README's "Supported agents" section documents the behavior and the disable path.
- **New `notes/` folder convention**: `notes/learned.md` (gotchas + system quirks), `notes/decisions.md` (rationale for non-obvious choices), `notes/ideas.md` (future-feature parking lot). Read at session start (learned only) so known landmines don't need re-discovering. Seeded with the XProtect investigation, FMP free tier paywall, tokenomist SPA limitation, yfinance NaN edge cases, and decisions around AGENTS.md rename, CronCreate vs cron, and the public+backup repo split.
- **Defensive trace logging in `screener.py` fundamentals loop** — prints `[fund] [i/N] {ticker} (yf_used=N, elapsed Xs)` on every iteration. If the process dies mid-loop (XProtect, OOM, network, anything), the last-printed line tells us exactly which ticker and call number triggered it. Cost: ~one extra log line per P1-passing candidate (typically 1-5 per run). Verified end-to-end via targeted `fetch_fundamentals(['CMI', 'SPY'], force=True)` invocation.

### Changed

- `CLAUDE.md` expanded from a 7-line pointer to ~35 lines, now carrying the auto-bootstrap instructions. Still points at AGENTS.md for the actual doctrine; the doctrine still has zero duplication.
- `AGENTS.md` "Session continuity" section reframed as "Session bootstrap" with mirrored auto-bootstrap instructions, so Codex sessions get identical behavior to Claude Code sessions.
- `README.md` Supported agents section gains an "Auto-bootstrap on session start" subsection documenting the behavior, the `quick:` / `oneshot:` skip path, and how to disable entirely.

### Investigated, no action

- **XProtect popup during dashboard build (reported 2026-06-07)** — Diagnostic showed 130 sequential `yf.Ticker(t).info` calls complete cleanly with no XProtect interference. Further analysis revealed `fetch_fundamentals` is only called for P1-passing candidates (typically 1-5 per run), not the full 188-name universe — the "130 yfinance calls" estimate that drove the initial concern was an upper bound that never occurs in practice. Likely cause of the original popup: a transient XProtect signature update from Apple, a different process, or an intermittent match. No fix shipped; the defensive trace logging above captures actionable data if it recurs. See `notes/learned.md` for the full investigation writeup.

---

## [v1.3] — 2026-06-07

Cross-agent compatibility. The project now follows the `AGENTS.md` convention so Codex (and any other agent that adopts the same convention) can pick up the doctrine alongside Claude Code.

### Changed

- **Doctrine file renamed `CLAUDE.md` → `AGENTS.md`**, following the emerging cross-agent standard so Codex auto-loads it natively. `CLAUDE.md` remains as a one-line pointer file so Claude Code (which auto-loads `CLAUDE.md`) still finds the doctrine. All internal references (`§5`, `§6`, etc., across 22 files) updated to read "AGENTS.md".
- `README.md` "Built with" section replaced by a "Supported agents" table covering Claude Code, Codex, and other agents that read `AGENTS.md`.
- `AGENTS.md` opens with an agent-agnostic intro paragraph addressing whoever's reading (Claude Code, Codex, or similar) — instead of presuming a single platform.
- `PROJECT_LOG.md` TL;DR rewritten as "an AI-coding-agent project (Claude Code, Codex, or compatible)" instead of "a Claude Code agent."

### Added

- README's `## Supported agents` table documents what works on each platform: Claude Code (primary, built here) and Codex (compatible via native `AGENTS.md` auto-load). Python code, dashboard, data integrations, and CLIs are platform-agnostic; only the agent orchestration layer differs.

### Backward compatibility

- Anyone with existing references to `CLAUDE.md` (forks, external links, notes) is unaffected — `CLAUDE.md` still exists as a pointer file and Claude Code still finds it.
- The Python codebase has no naming changes — only docstring and comment references updated. No code paths break.

---

## [v1.2] — 2026-06-06

Install-experience polish. Anyone landing on the GitHub front page can now follow the README to a working dashboard without hitting a 404 on the clone command or wondering whether they need Claude Code.

### Added

- README Quick Start now opens with a "What you need" block — Python 3.9+, Claude Code (recommended), and ~15 minutes for free API key sign-ups. Sets expectations before the first command.
- A "Verify it worked" section right after the 8-step install lists the six panels you should see in the dashboard, with a fallback hint if anything's missing.
- Trailing link to PROJECT_LOG.md now anchors directly to `#replication-steps` so users land on the full walkthrough instead of the file's top.

### Fixed

- **README clone command was unusable.** The Quick Start said `git clone https://github.com/YOUR_USERNAME/trading-advisor.git` — a fresh user copy-pasting this got a 404. Corrected to the canonical repo path.

---

## [v1.1] — 2026-06-06

Operator-defined position sizing in the Risk Simulator, plus the bug fix that came with it.

### Added

- Risk Simulator now lets the operator define their own position size. Doctrine §5 says the formula derives the *maximum permitted* size, not the obligatory size — operators routinely want to size down (correlation tax, lower conviction, partial-fill caution). The new "Size" field is auto-prefilled to the doctrine maximum when you pick a ticker, then you edit it as you see fit.
- New "Per-trade risk cap (§5)" gate that explicitly verifies your chosen size doesn't exceed the doctrine ceiling. Sizing above the 2% per-trade risk cap hard-fails the gate (clearly explaining the doctrine max at the current entry/stop); sizing under it passes cleanly within the cap.
- Position-size display in the result block now shows the doctrine maximum as a quiet sub-line whenever your size differs from it — so the ceiling is always visible without needing to mentally re-derive the formula.

### Changed

- The simulator's role is now framed honestly: it tells you whether *your* proposed trade is doctrine-compliant and whether your portfolio is at risk, rather than dictating the size for you. The sim-blurb now reflects this.

### Fixed

- Crypto positions (BTC, ETH, SOL, etc.) were silently sizing to 0 in the Risk Simulator due to a JavaScript falsy-coercion bug: `lot_size = 0` (the fractional-size marker for crypto) was being treated as falsy and replaced with `1` via `|| 1` fallback in three places. Crypto fractional sizing now works end-to-end across prefill, compute, gate, and result display. The §5 gate message also formats fractional sizes correctly (was rounding to "0 units" in the prose).

---

## [v1.0] — 2026-06-06

First stable release. Snapshot of everything built across the initial Claude Code sessions, packaged for replication.

### Added

- **Doctrine** — `AGENTS.md` (10 sections) covering role/mission, hard rules, data sources, analytical framework, risk doctrine, asymmetric strategy construction, decision process, output format, calibration, and tone. Includes the PHASED RAMP from Phase 1 (paper + spot only) through Phase 3 (full doctrine).
- **Replication guide** — `PROJECT_LOG.md` with cross-platform setup instructions, all six API key sign-up URLs (FRED, Alpha Vantage, Finnhub, Twelve Data, FMP, optional CoinGecko Pro), and known caveats from real operational experience.
- **21 self-contained skills** under `.claude/skills/`:
  - **Data fetchers**: `macro-rates` (FRED), `macro-calendar` (curated FOMC/CPI/NFP/PCE), `us-news` (Alpha Vantage with budget queue), `us-fundamentals` (yfinance), `klse-quote` / `klse-history` / `klse-news` (Bursa Malaysia), `klse-refresh` / `klse-announcements` (Python-callable caches), `crypto-coingecko`, `crypto-derivatives` (Binance funding/OI), `crypto-unlocks` + `crypto-unlocks-cache` (§5 48h halt gate), `hyperliquid-flow`, `finnhub` (live US quotes), `twelve-data` (bulk historical), `fmp` (fundamentals).
  - **Analysis + lifecycle**: `sector-rotation` (11 SPDR ETFs vs SPY), `us-screener` (176-name P1 + Buffett Q+V), `dashboard` (HTML render), `watchlist` (CLI), `journal` (prospectus → live → closed lifecycle with auto-R).
- **Dashboard** (`dashboard.html`) with regime strip, Risk Simulator (12-gate doctrine check per market + prospectus generator), US/KLSE/crypto grids with click-to-expand thesis + 8-gate breakdown, 🔭 Discovery panel (sector rotation heat strip + ranked candidates), Watchlist Manager inline forms, prospectus cards with action forms, journal tail, status badge tooltips.
- **Live quote buttons** — 🔄 next to every US price (Finnhub real-time), 🔄 for crypto (Binance / CoinGecko), 📊 link for KLSE (klsescreener.com).
- **Discovery layer** — sector rotation + 176-name screener universe with Buffett quality+value tagging (💎 BUFFETT / 🏆 QUALITY / 💰 VALUE / ⚡ TECH).
- **Tier 1 optimizations** — extended cache TTLs across all sources, daily-only screener marker, skip-if-fresh subprocess spawn from `--with-discovery`.
- **Tier 2 optimizations** — Twelve Data fallback for yfinance NaN-Close bars; CoinGecko cooldown + stale fallback; FMP → yfinance fallback for paywalled symbols.
- **Tier 3 optimizations** — bulk-load resolution cache (single directory scan), parallel yfinance per-ticker fetches via `ThreadPoolExecutor`, color-coded budget bar in dashboard header (AV / TD / FMP usage), watchlist auto-inclusion in screener universe.

### Architectural patterns established

- Cache + cooldown + stale-fallback for every external data source.
- Budget tracking for capped APIs with soft + hard caps and on-demand reserves.
- Tiered cache TTLs for the screener (HOT 24h / WARM 72h / COLD 7d).
- Provider fallback chains across yfinance / Twelve Data / FMP / Finnhub / CoinGecko / Binance.
- Browser-side live quote endpoints separate from cached daily-close pipeline.

### Performance

- Refresh button on warm caches: **~0.15 seconds**.
- Daily API budget consumption: well under 30% of all free-tier limits during typical use.
- First-time setup screener scan: ~22 minutes; thereafter sub-second on tier rotation.

### Known caveats (documented in PROJECT_LOG.md)

- macOS XProtect blocks `yfinance.download(multi_tickers)` — sector rotation and screener migrated to Twelve Data; per-ticker yfinance still works.
- Yahoo Finance IP-bans bursts via the urllib chart endpoint — no longer used directly; we go through Twelve Data instead.
- FMP free tier only covers ~30-50 megacap symbols for `/stable/ratios-ttm` and `/stable/key-metrics-ttm` — automatic yfinance fallback for everything else.
- Finnhub dropped historical OHLCV from free tier in 2024 — we only use `/quote` (still free, real-time).
- Tokenomist.ai is a Next.js SPA — direct urllib returns no usable JSON; agent uses WebFetch then writes to local cache.
- No free CORS-friendly API covers KLSE real-time — 📊 button opens klsescreener.com in a new tab instead.

### Licensing

- MIT license with explicit trading disclaimer.

---

<!-- Link targets below point at the canonical public repo. If you maintain
     your own fork, update or delete these as appropriate for your setup. -->
[Unreleased]: https://github.com/kensongan-prog/trading-advisor/compare/v1.4.1...HEAD
[v1.4.1]: https://github.com/kensongan-prog/trading-advisor/releases/tag/v1.4.1
[v1.4]: https://github.com/kensongan-prog/trading-advisor/releases/tag/v1.4
[v1.3]: https://github.com/kensongan-prog/trading-advisor/releases/tag/v1.3
[v1.2]: https://github.com/kensongan-prog/trading-advisor/releases/tag/v1.2
[v1.1]: https://github.com/kensongan-prog/trading-advisor/releases/tag/v1.1
[v1.0]: https://github.com/kensongan-prog/trading-advisor/releases/tag/v1.0
