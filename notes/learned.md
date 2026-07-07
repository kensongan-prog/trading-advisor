# Learned — gotchas + system quirks

Newest at top. The agent reads only `## Hot` at session start (budget ≤150 lines). Older, superseded, reference-only, or test-enforced entries live in `notes/learned-archive.md` (grep target, never bootstrap-read). See the vault's `Memory Protocol.md` for the full capture/decay/promotion doctrine.

---

## Hot

### 2026-07-06 — Reddit no-auth `.json` endpoints verified still dead; PullPush too throttled; RSS remains the only no-auth path
tags: #tool:reddit-api #pattern:provider-verification #project:trading-advisor

While investigating whether the `reddit-sentiment` skill could restore real engagement scores without full OAuth setup (RSS-sourced posts/comments carry `score=None`, so the RSS leg's engagement weighting is flat), live-probed every no-auth route from this machine: `www.reddit.com/r/stocks/search.json` — HTTP 403 with both a descriptive UA (`trading-advisor:reddit-sentiment:0.2.0 (by /u/anonymous)`) and a Chrome 126 browser UA; `old.reddit.com/.../search.json` — 403 (both UAs); plain listing `www.reddit.com/r/stocks/new.json` — 403; comment thread `www.reddit.com/comments/1up4hpi.json` — 403. PullPush.io (`api.pullpush.io/reddit/search/submission/`) — HTTP 429 on first call AND on a retry after 20s backoff, too throttled to serve as a pipeline leg. RSS `search.rss` (the skill's current path, used as control) — HTTP 200. **Conclusion:** the widely-blogged "`.json` suffix" trick is dead from this machine/IP as of 2026, consistent with the 2023 blocking already noted in the skill's SKILL.md; PullPush is not dependable. Two standing takeaways: (a) the only route to real engagement scores is the already-built OAuth path (`reddit_search_oauth`/`fetch_comments_oauth` in `reddit_sentiment.py`, functional since v1.10.0) — a Reddit "script"-type app registration at reddit.com/prefs/apps is instant and free (the 2-4 week review only applies to the commercial tier), it auto-activates once `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` land in the skill's `.env`; (b) 2026-era blog posts claiming the `.json` trick still works do not hold from this machine/IP — always re-probe with one curl before building on such claims. Operator decision (Kenson, 2026-07-06): keep the RSS status quo; this entry records the findings so `.json` isn't re-investigated from scratch.
Enforced-by: — none yet (investigation-only, no code change)

### 2026-07-07 — SUPERSEDES the 2026-06-26 entry below: dashboard now runs under launchd, GG-8-owned
tags: #pattern:daemon-lifecycle #project:trading-advisor

**Decision (Kenson, 2026-07-07):** dashboards across the fleet (net-worth, Trading Advisor, MooMoo) were starting inconsistently — some launchd, some manual/ad-hoc from whichever project created them. Kenson asked for all three standardized under launchd and handed to GG-8 (Hermes finance-analyst profile) for start/restart/status control through a single agent. This directly supersedes the 2026-06-26 entry's "manual launch is the standing preference" / "do NOT install a LaunchAgent without checking with Kenson first" — that check happened, and the answer is now yes.
**What changed:** new service `ai.hermes.trading-advisor-dashboard` (`~/Library/LaunchAgents/`, RunAtLoad+KeepAlive+ThrottleInterval 10, hermes-agent venv python `-u` for unbuffered logs, `--lan`, logs on the internal drive at `~/Library/Logs/trading-advisor-dashboard.{log,error.log}`). Registry entry: `~/.hermes/shared/dashboards.json` (id `trading-advisor`). `Trading Dashboard.command` no longer starts its own server process — it ensures the launchd service is up (`launchctl kickstart`) and opens a browser tab; closing the window no longer stops the dashboard. `.claude/launch.json` port fixed 8787→8789 (was stale/wrong — collided with the net-worth dashboard's port). GG-8 controls it via `gg8_dashctl.py` (finance-analyst profile scripts): `status|start|restart|stop trading-advisor`.
**Verified live 2026-07-07:** bootstrap → running, health 200; kill → KeepAlive restart ≤10s; bootout/bootstrap cycle → exactly one listener on 8789; full 427-test TA suite still green after the doc/launch.json edits.
**Watchpoint:** the historical no-LaunchAgent reason in the archived 2026-06-26 entry is now doubly moot (SSD move + this explicit re-authorization) — do not resurrect it as a blocker for future dashboard-adjacent launchd work in this repo.
Enforced-by: — none yet (operational verification only)

### 2026-07-06 — Building the cross-agent memory protocol: a frontmatter `project:` slug that differs from the folder name silently fragments cross-referencing
tags: #pattern:canonical-identity #project:trading-advisor

**Symptom:** while building the vault's `vault_doctor.py`/`vault_index.py` (cross-project retention/decay tooling), Sync Ledger rows written under folder-name project labels ("Codex Trader", "SportsBet") didn't match the doctor's internal per-project key, producing spurious "last synced never" warnings even right after syncing.
**Root cause:** two vault Home notes carry an optional frontmatter `project:` slug (`codex-trader`, `sportsbet`) that the indexer preferred over the folder name; the other two Home notes have no such field and fall back to the folder name — so "project identity" silently had two different resolution rules depending on which note you looked at.
**Fix:** made the top-level folder name always canonical for cross-referencing (matches the Vault Guide's own "one folder per project, globally unique" rule); kept the frontmatter slug as a separate `project_slug` field for display only, never for matching.
**Validation:** live-verified — after the fix, `repo-drift` and `sync-ledger` checks agreed with the ledger rows on the first try.
**Watchpoint:** whenever two notes describing "the same kind of thing" have an optional field that overrides a mandatory, always-present one (here: slug vs. folder), pick the always-present one as the identity key — the optional field will eventually exist on some notes and not others.
Enforced-by: scripts/tests/test_vault_doctor.py (vault repo, not this one)

### 2026-07-06 — moomoo paper accounts are per-market with their own acc_ids; the SDK's trade context is HK-filtered BY DEFAULT
tags: #tool:moomoo-sdk #pattern:context-filter #project:trading-advisor

First paper-trade attempt (M0) failed three ways before the root cause emerged, all live-verified: (1) MooMoo's configured real `MOOMOO_ACCOUNT_ID` → "Nonexisting acc_id" — paper orders need the SIMULATE account's own id, not the real account's; (2) acc_id=0 (SDK default-account mode) → routed to the HK paper account → "does not support trading US.AUPH" — **paper accounts are per-market**: this operator has TWO (acc 2506451 = SIMULATE CASH [HK], acc 2506450 = SIMULATE MARGIN [US]); (3) explicitly setting the US sim acc_id → "Nonexisting acc_id" again, because **`OpenSecTradeContext` defaults to `filter_trdmarket=TrdMarket.HK`** and MooMoo's `_trade_context()` passes no filter — the context literally cannot see non-HK accounts, for both `get_acc_list` AND acc_id validation on orders. Fix verified live with a 1-share SIMULATE probe: `filter_trdmarket=TrdMarket.NONE` + `acc_id=2506450` placed US.AUPH fine (order queued SUBMITTED while market closed — moomoo SIMULATE accepts weekend orders) and canceled via `modify_order(ModifyOrderOp.CANCEL, ...)` (there is NO `cancel_order` method on that context — a direct-SDK trap). Codex owns the code fix (work order sent); TA-side takeaway: **when a broker API rejects an account id that plainly exists, suspect a context-level market/env filter before suspecting the id.** Also noted: the real account is currently not exposed by OpenD under ANY filter — likely paper-only OpenD login; read-only real-account sync will fail until the operator re-logs OpenD with the real account.
Enforced-by: — none yet

### 2026-07-04/05 — Detached `python -m pkg.module` dies silently from an agent session; `python -c "import...main()"` survives (MooMoo server)
tags: #tool:python #pattern:daemon-lifecycle #project:trading-advisor

While cross-verifying MooMoo dashboard round 2, every attempt to start MooMoo's `serve-dashboard` (port 8788) as a detached background process died instantly with a **completely empty log** — no traceback, no startup print, despite `-u`. Tried and failed: `nohup+disown`, the harness's background-task feature, wrapper scripts, system python3, `screen -dmS`, localhost-only bind. **Root cause pinned 2026-07-05 by stepwise bisection: the `-m` module-execution mode itself.** Discriminating facts: (a) minimal detached venv/system pythons survive; (b) `import moomoo` (SDK) survives detached; (c) the full server startup sequence — settings, write_dashboard, Job, socket bind, `serve_forever`, even `dashboard_urls()`'s ifconfig subprocess — ALL survive detached when launched via `-c`; (d) the identical code dies instantly when launched via `python -m moomoo_adapter.cli`. **Working launch (agent-runnable):**
```
cd "/Volumes/Mac Mini SSD/Projects/Codex/MooMoo" && PYTHONPATH=src nohup .venv/bin/python -u -c "import sys; sys.argv=['moomoo-adapter','serve-dashboard']; from moomoo_adapter.cli import main; main()" </dev/null > /tmp/moomoo-dashboard.log 2>&1 & disown
```
Verified: server persists across calls, dashboard 200, `/api/quotes` returns live OpenD data. General lesson promoted to the vault's `Lessons — Cross-Project.md` (applies to any project): **if a detached long-running process dies silently pre-output, try converting `python -m pkg.mod` to `python -c "from pkg.mod import main; main()"` before assuming TCC/permissions.** Also still true: don't kill an operator-started server unless necessary, and say so if you do.
Enforced-by: — none yet

### 2026-07-02 — Claude Preview MCP tool can't launch `server.py` from the SSD project path ("Operation not permitted")
tags: #tool:preview_start #pattern:sandboxed-subprocess #project:trading-advisor

While live-verifying Analysis C2–C4 (Risk Simulator gates + Discovery panel), `preview_start` on the `dashboard` launch config failed: `/Users/aiagent/.local/bin/python3: can't open file '.../server.py': [Errno 1] Operation not permitted`. The SAME command runs fine via the Bash tool. Smells like the same family as a sandboxed subprocess lacking a permission grant the interactive shell inherits, but root cause not confirmed this session. **Workaround used:** when the preview tool can't reach the dashboard server, fall back to static verification — build `dashboard.html` via Bash, then parse the output directly (`window.TA_SIM = {...}` JSON blob, grep rendered rows for expected text/badges) rather than a live browser. Caught real, correct data end-to-end for C2–C4 even without an interactive browser session — good enough for pure-data verification, though it can't confirm JS gate *rendering* behavior the way a real click-through can.
Enforced-by: — none yet

### 2026-07-02 — Broker (MooMoo) panel (Bridge Phase 3): observed-but-never-submitted intents need their own display fallback
tags: #pattern:cross-repo-display #project:trading-advisor

**Real bug caught only by live-verifying the panel against MooMoo's actual on-disk `staged_orders.json`** (not synthetic fixtures): a staged order observed in `sync_state.json` but never actually submitted (no `order_id`, no `journal_path`) fell through to displaying the **raw `intent_id` string** in the panel's ticker column. Fix: `_display_ticker()` falls back to parsing the ticker out of `intent_id`'s own `source:TICKER:path` format before ever falling back to the whole raw string.

**Reusable lesson (second time in one day): always render/exercise a new cross-repo status surface against the real upstream artifact at least once, even after exhaustive synthetic-fixture tests pass.** Synthetic fixtures naturally model the "normal, complete" shapes an author expects; real production data reliably contains the partial/incomplete shapes that only show up from actually running the thing.

**MooMoo's `trade_ledger.json` reflects the operator's REAL brokerage account, not paper trading** — no `SIMULATE` filtering applied. Any TA surface reading it must label it unambiguously as real-account context, separate from the paper-trading picture `broker-sync` tracks.
Enforced-by: tests/test_broker_panel.py

### 2026-07-02 — broker-sync (Bridge Phase 2): MooMoo already aggregates fills; don't re-derive them; check "is there a fill to attribute?" before journal resolution
tags: #pattern:precondition-check #project:trading-advisor

**MooMoo's `staged_orders.json` is the authoritative, ALREADY-AGGREGATED per-intent view — don't re-derive fill totals from raw `fills.json`.** TA's broker-sync reads that, not raw fills.

**Real bug caught by live-verifying against MooMoo's actual on-disk data: a staged-but-not-yet-submitted order was being flagged for manual review** because the original decision logic checked "did journal_path resolve?" before checking "is there even a fill to attribute?". This is the MOST COMMON state a staged order sits in — flagging it every run would have been constant noise. Fix: check fill-existence FIRST; only look at journal resolution once there's actually something to attribute. **Lesson: always run a new sync/attribution loop against real on-disk data before shipping — synthetic fixtures had already covered every branch of the decision table and still missed this**, because the fixtures didn't happen to model the "staged, unfilled, no journal_path key at all" shape real un-submitted orders actually have.

**MooMoo's paper-vs-real separation is a field, not a separate file — `trading_env` defaults to `"REAL"` when absent.** Old/pre-Phase-1 fill rows lack the field entirely — NOT tagged `SIMULATE` — so any code reading MooMoo fills must explicitly filter `env == "SIMULATE"`.

**Journal resolution matches by the exact basename STEM of a cross-repo path, not the raw absolute path string** — `journal_path` bakes in another machine's `TRADING_ADVISOR_ROOT`; resolving by `Path(journal_path).stem` is EXACT traceability since journal filenames are unique in this project's convention.
Enforced-by: tests/test_broker_sync.py

### 2026-07-02 — Guardrails Phase B: why the pump-and-dump flag is `'warn'`, not `'bad'`; and cross-skill imports ARE allowed for shared logic
tags: #pattern:warn-not-block #project:trading-advisor

**The Risk Simulator's `hardBads` list has real teeth** — `gates.filter(x => x.ok === 'bad')` directly disables the "Create Prospectus" button with no override affordance anywhere in the UI. Making the P&D composite `'bad'` would have been the project's **first real hard block**, contradicting doctrine §1 (operator decides) and warn-loudly-never-block. **Decision: ship it as `'warn'`** — visually distinct (🚩 prefix) but never disables anything. Verified live in Chromium via Playwright.

**Cross-skill imports are an established, intentional pattern for genuinely shared logic — the "self-contained skill dirs" rule (see `notes/learned-archive.md`, 2026-06-13 entry) is about NOT sharing trivial boilerplate, not a blanket ban.** `j.py`'s `sync_portfolio()` already imports from `dashboard/`; `quality_flags.py`'s thresholds are exactly the kind of thing that MUST be single-sourced. Don't duplicate the module; mirror the existing cross-skill-import pattern.

**Operational note, not a code gotcha: be extremely careful chaining `git stash` into a "just check status" one-liner.** Mid-session, a command meant to check `git status` accidentally included `git stash -u -q` first, silently stashing ~200 lines of uncommitted work. Recovered cleanly with `git stash pop`, but never bundle state-mutating git commands into a multi-command one-liner opportunistically.
Enforced-by: — none yet (procedural discipline for the git-stash note)

### 2026-07-02 — Structural-quality flags (quality_flags.py): two live-verification catches
tags: #pattern:none-vs-zero #project:trading-advisor

**1. yfinance omits `numberOfAnalystOpinions` entirely (`None`) for zero-coverage names — it's not an explicit `0`.** A naive `== 0` check misses every uncovered microcap. Fix: treat `None` as no-coverage too, but gate on `price is not None` first — otherwise a totally-failed fetch spuriously flags NO_COVERAGE alone with zero other evidence.

**2. Context-only gauges (SPY, `EARNINGS_SKIP_TICKERS`) need the SAME skip applied to quality flags as to earnings.** Caught only by exact-match live verification (`<b>SPY</b>` in the rendered `dashboard.html`) — a loose substring search missed it because "SPY" appears in unrelated contexts elsewhere on the page. **Lesson: when grepping a rendered dashboard for a ticker's row, anchor on the exact cell pattern, not a bare substring.**

**Reusable pattern:** `chg_5d_pct`/`chg_30d_pct` were added to `fetch_yfinance_ticker`'s output for free — the 1y price history is already loaded in memory for RSI/SMA/ATR. Check what's already in the response/dataframe before reaching for a new fetch.
Enforced-by: tests/test_quality_flags.py

### 2026-07-01 — klsescreener comment threads + the "KLSE news already exists" trap
tags: #provider:klsescreener #project:trading-advisor

**1. klsescreener has a per-stock community comment thread with a working endpoint:** `https://www.klsescreener.com/v2/comments/all/stock/{CODE}` (GET, server-rendered HTML, no auth, caps ~26 comments). Fills the retail-sentiment gap StockTwits (404s on KLSE) + Reddit (thin Bursa) leave. Dead ends mapped: the singular `/v2/comments/comment/stock/{code}` and doubled `/v2/comments/comments/stock/{code}/{page}` both 404 — deprecated. The stock **view** page only server-renders a ~2-comment preview — do NOT use it to gauge volume.

**2. KLSE *news* is ALREADY scraped programmatically by `news_glyph`, not the klse-news skill.** `us-news/news_glyph.py::refresh_klse` already scrapes `/v2/news/stock/{code}`. A standalone klse-news fetcher was built and then DELETED as redundant. **Recurring lesson: grep for the capability in the consuming module before building a fetcher** — the SKILL.md dir isn't the whole story.
Enforced-by: tests/test_news_glyph_klse.py

### 2026-06-29 — Project moved off `~/Documents` to the external SSD — corrects the 2026-06-26 entry below
tags: #pattern:workspace-hygiene #project:trading-advisor

The repo now lives at **`/Volumes/Mac Mini SSD/Projects/Claude/Trading Advisor`** (moved 2026-06-29). This corrects two now-stale claims: (1) "this folder isn't moving anytime soon" — it did move; the SSD must be mounted to reach the repo (and the vault). (2) The launchd `EX_CONFIG`/TCC trap documented below was specific to `~/Documents` (TCC-protected); the project is no longer there, so that failure mode no longer applies here — kept as general reference in `notes/learned-archive.md` (still true for any project under `~/Documents`/`~/Desktop`/`~/Downloads`). `/Volumes/…` external volumes aren't TCC-protected the same way, but a launchd job firing before the volume mounts would fail differently (path not found). Autostart remains unwanted regardless — manual launch is the standing preference.
Enforced-by: — none yet

### 2026-06-26 — Dashboard launches manually via `Trading Dashboard.command`; `--lan` is the persistent piece
tags: #pattern:daemon-lifecycle #project:trading-advisor

**SUPERSEDED 2026-07-07 — see the entry above.** Kept for history only.

**Decision (Kenson, 2026-06-26):** the dashboard does NOT need to auto-start on reboot. Manual start is fine. The only thing that must persist is the `--lan` flag, so every manual launch binds dual-stack (`::`) and is reachable on Tailscale at **http://100.71.94.40:8789** [corrected 2026-07-07 — port was 8789 all along, this note had a stale 8787]. Without `--lan` the server is loopback-only and the phone/iPad get connection-refused.

**How to launch:** double-click **`Trading Dashboard.command`** in the project root:
```sh
exec /usr/bin/env python3 ".claude/skills/dashboard/server.py" --lan --open
```
`--lan` → dual-stack bind; `--open` → opens browser to localhost. Manual workflow only — close the Terminal window to stop the server.

**Do NOT install a LaunchAgent for autostart** without checking with Kenson first — manual launch is the standing preference. The historical reason why (a launchd/TCC failure mode, no longer a live constraint since the 2026-06-29 SSD move) is kept as reference in `notes/learned-archive.md`.

**Verify after a manual launch:** `curl -sS -o /dev/null -w "%{http_code}\n" http://100.71.94.40:8789/` should return `200`. If `000`, either the dashboard isn't running or `--lan` got dropped — check `Trading Dashboard.command` first.
Enforced-by: — none yet

### 2026-06-25 — Data builds need system `python3`, NOT `.venv-playwright` (pandas/yfinance)
tags: #tool:python #project:trading-advisor

The project venv `.venv-playwright` has pytest + playwright but NOT pandas/yfinance. So `dashboard.py --force` (or anything calling `fetch_yfinance_ticker`) only works under **system `python3`** — the venv only succeeds on cache hits. `server.py` spawns builds via `sys.executable`, so **run the server with system `python3`** or builds fail on the first cache miss. Tests that touch pandas use `pytest.importorskip("pandas")` so the suite stays green in the venv. Bootstrap pytest still uses the venv; only *data builds* need system python.
Enforced-by: — none yet

### 2026-06-11 — Polymarket crypto events expire daily; macro/geo don't — cache needed an age-based auto-refresh
tags: #provider:polymarket #pattern:cache-ttl #project:trading-advisor

Polymarket crypto price-band events ("Bitcoin price on June 10?") resolve at midnight UTC and flip `closed=true`; the fetcher's filter correctly drops them, leaving the Crypto column empty on an overnight-aged cache. Macro/econ/geopolitics events are long-dated and survive cache age comfortably — Polymarket has **categorically different cache half-lives by category**. Fix: `dashboard.py` now auto-refreshes polymarket when its cache is >18h old or missing. **Audit recipe:** if the Crypto column ever shows "no events" again, check cache age (`stat .claude/cache/polymarket/events.json`) and confirm the API has active events today.
Enforced-by: — none yet

### 2026-06-10 — Finnhub free tier: `/stock/candle` returns HTTP 403 (premium-gated)
tags: #provider:finnhub #project:trading-advisor

Quotes (`/quote`) still work fine, but historical candles are premium-gated on the free tier. Any code needing OHLCV history (returns, RSI-from-closes, relative strength) cannot use Finnhub on the free tier — use yfinance for history (batched `yf.download`, not per-ticker `.info`). Finnhub stays the source for live intraday quotes only.
Enforced-by: — none yet

### 2026-06-05 — FMP free tier only covers ~30-50 megacap US symbols
tags: #provider:fmp #project:trading-advisor

HTTP 402 (Payment Required) on most non-megacap symbol fetches from FMP `/stable/` endpoints. Any fundamentals path relying on FMP for the full screener universe (176 names) will hit paywalls for ~130 of them. Current code falls back to yfinance.
Enforced-by: — none yet

### 2026-06-05 — Tokenomist.ai is a Next.js SPA — direct urllib scraping returns no data
tags: #provider:tokenomist #tool:webfetch #project:trading-advisor

`urllib.request.urlopen` returns near-empty HTML — all token-unlock data is fetched client-side via JS. The `crypto-unlocks` skill is agent-only — uses WebFetch to render the SPA, then pipes results into `crypto-unlocks-cache` for persistence.
Enforced-by: — none yet

### 2026-06-04 — yfinance occasionally returns rows with NaN Close
tags: #provider:yfinance #project:trading-advisor

Some `yf.Ticker(t).history()` results have a final-row Close=NaN, especially for thinly-traded names or right after a session boundary. Always `.dropna(subset=["Close"])` before reading the last row; fall back to Twelve Data if the dropna leaves an empty DataFrame.
Enforced-by: — none yet

### 2026-06-15 — "N source(s) refreshable" stuck forever = health LOOKUP mismatch, not a data gap
tags: #pattern:health-vs-reality #project:trading-advisor

`refreshable = stale + transient + MISSING`; when it's stuck with 0 stale / N missing, that's N phantom "missing" no refresh can clear. Two causes found, both health expecting the WRONG filename (crypto cache keyed by CoinGecko slug vs a lowercased-ticker guess; SPY intentionally never `us_news`-fetched but health expected `SPY.json`). **General lesson (3rd time this pattern has bitten): the Data Health panel makes a promise — "this is refreshable." When health flags something refreshable that a refresh won't fix, suspect a health-vs-reality mismatch, not a fetch failure.** Cross-check: does the cache file actually exist under the name `collect_health` computes?
Enforced-by: — none yet

## Archive pointer

Older, superseded, reference-only, and test-enforced entries: see `notes/learned-archive.md` (grep target; not read at bootstrap).
