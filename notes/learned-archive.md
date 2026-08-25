# Learned — archive

Append-only overflow of `notes/learned.md` — grep target, never read at bootstrap. Entries here are superseded, reference-only, or enforced by a regression test (the guard is the memory now). Newest at top.

---

### 2026-07-06 — Building the cross-agent memory protocol: a frontmatter `project:` slug that differs from the folder name silently fragments cross-referencing
> Archived 2026-08-25: the regression test is now the durable guard.
tags: #pattern:canonical-identity #project:trading-advisor

**Symptom:** while building the vault's `vault_doctor.py`/`vault_index.py` (cross-project retention/decay tooling), Sync Ledger rows written under folder-name project labels ("Codex Trader", "SportsBet") didn't match the doctor's internal per-project key, producing spurious "last synced never" warnings even right after syncing.
**Root cause:** two vault Home notes carry an optional frontmatter `project:` slug (`codex-trader`, `sportsbet`) that the indexer preferred over the folder name; the other two Home notes have no such field and fall back to the folder name — so "project identity" silently had two different resolution rules depending on which note you looked at.
**Fix:** made the top-level folder name always canonical for cross-referencing (matches the Vault Guide's own "one folder per project, globally unique" rule); kept the frontmatter slug as a separate `project_slug` field for display only, never for matching.
**Validation:** live-verified — after the fix, `repo-drift` and `sync-ledger` checks agreed with the ledger rows on the first try.
**Watchpoint:** whenever two notes describing "the same kind of thing" have an optional field that overrides a mandatory, always-present one (here: slug vs. folder), pick the always-present one as the identity key — the optional field will eventually exist on some notes and not others.
Enforced-by: scripts/tests/test_vault_doctor.py (vault repo, not this one)

### 2026-06-26 — Dashboard launches manually via `Trading Dashboard.command`; `--lan` is the persistent piece
> Archived 2026-07-07: SUPERSEDED by the 2026-07-07 "dashboard now runs under launchd, GG-8-owned" entry in `notes/learned.md`. The dashboard is now a launchd service (`ai.hermes.trading-advisor-dashboard`) started/monitored by GG-8, not a manual `Trading Dashboard.command` process — so the manual-launch instructions below are historical. Kept for the port-history (8787→8789) and the `--lan`/dual-stack rationale.
tags: #pattern:daemon-lifecycle #project:trading-advisor

**Decision (Kenson, 2026-06-26):** the dashboard does NOT need to auto-start on reboot. Manual start is fine. The only thing that must persist is the `--lan` flag, so every manual launch binds dual-stack (`::`) and is reachable on Tailscale at **http://100.71.94.40:8789** [corrected 2026-07-07 — port was 8789 all along, this note had a stale 8787]. Without `--lan` the server is loopback-only and the phone/iPad get connection-refused.

**How to launch (historical):** double-click **`Trading Dashboard.command`** in the project root:
```sh
exec /usr/bin/env python3 ".claude/skills/dashboard/server.py" --lan --open
```
`--lan` → dual-stack bind; `--open` → opens browser to localhost. Manual workflow only — close the Terminal window to stop the server.

**Verify after a manual launch:** `curl -sS -o /dev/null -w "%{http_code}\n" http://100.71.94.40:8789/` should return `200`. If `000`, either the dashboard isn't running or `--lan` got dropped.
Enforced-by: — none yet (superseded)

### 2026-06-25 — klsescreener stock URL is `/v2/stocks/view/{code}`, not `/quote/`
> Archived 2026-07-06: enforced-by-test.

The dashboard's KLSE 📊 quote button had drifted to `klsescreener.com/v2/stocks/quote/{code}` → HTTP 404. The real path is `/v2/stocks/view/{code}` — the exact path `klse-quote` + `klse-refresh` already use. Fixed v2.7.0. The `/view/` page is a JS-rendered SPA, so a raw urllib fetch returning empty/no-`<title>` is normal flakiness — trust the 200-vs-404 status, not page-body content.
Enforced-by: tests/test_klse_quote_link.py

### 2026-06-25 — Server control-bar JS is scoped; re-query elements after an innerHTML swap
> Archived 2026-07-06: settled, narrow DOM fix.

Two DOM gotchas from the v2.7.0 live-dashboard work: (1) `server.py`'s CONTROL_BAR `<script>` is NOT global scope — functions reachable from inline `onclick` are explicitly `window.X = …`; plain `function foo(){}` there is scoped. To test such a function, mirror its body in the test rather than calling it. (2) An `innerHTML` swap detaches all children — any element reference grabbed before the swap is stale; re-`getElementById` after swapping. Panel collapse is event-delegated precisely so a swapped panel's new `<h2>` still folds without re-binding.

### 2026-06-15 — Data-utilization audit: "is each stream on the rung it deserves?"
> Archived 2026-07-06: v2.6.0-era audit, closed out.

When asked "does our analysis use all the data we ingest?", the useful reframe is a utilization ladder per stream: rung 0 = not ingested; rung 1 = displayed only; rung 2 = computed into a signal; rung 3 = gates a decision. The gaps are almost never "missing data" — they're streams stuck a rung too low. **Verify in code, don't trust the mental map** — a v2.6.0 audit "discovered" funding was unused, but tracing showed it already drove a sim factor. Three gaps closed in v2.6.0: risk ⊥ sentiment were siloed; sentiment was sample-size blind; only funding was ingested from crypto-derivatives, not OI/long-short. Key recurring rule: don't double-count correlated crowding signals — funding + OI + L/S all measure the same thing, share ONE gate. Not everything belongs in the dashboard: `hyperliquid-flow` whale-position tracking needs a target address you supply — it's an interactive agent tool, not a per-coin auto-build signal.

### 2026-06-14 — HTTPS over Tailscale (for OS notifications) needs the admin HTTPS toggle, then `tailscale serve`
> Archived 2026-07-06: one-time infra setup, now settled.

OS/browser notifications require a secure context (`https://` or `localhost`); over Tailscale you hit `http://100.x.x.x:8787`, neither, so notifications silently don't fire (in-page toast still works). Fix: enable HTTPS certs in the Tailscale admin console (MagicDNS must be on too — without this, `tailscale cert`/`tailscale serve` fail with "your Tailscale account does not support getting TLS certs", which is the toggle being off, not a plan limit). Then `tailscale serve --bg 8787` once — persistent tailnet config, survives reboots. Gotcha: `tailscale serve --bg` hangs (no error) when HTTPS certs aren't enabled. Self-signed + a server.py `--https` flag is the fallback.

### 2026-06-13 — Skill dirs are deliberately self-contained; don't DRY across them
> Archived 2026-07-06: settled architectural decision, referenced by the 2026-07-02 Guardrails Phase B entry in Hot.

During the v2.3.0 optimization pass the instinct was to dedup the `.env` loader copy-pasted across 9 skill dirs. **Decision: don't.** Each `.claude/skills/<x>/` dir runs standalone with zero cross-skill imports — that self-containment is a feature (skills are independently copyable for replication). What IS worth deduping: same-directory helpers with real logic and a history of drift (the operator-loop CLIs' `_cli_lib.py`). Rule of thumb: dedup within a dir, stay self-contained across dirs.

### 2026-06-12 — Dashboard "refresh does nothing" cluster: three structural root causes
> Archived 2026-07-06: specific bug, fixed in v2.2.0.

Root cause #1: sources with no refresh path in any button (klse_announcements, klse_fundamentals only had standalone CLIs; crypto_unlocks is agent/WebFetch only). Root cause #2: TTL disagreements so a refresh never cleared the stale flag (health.py marked screener stale at 12h, dashboard.py gated at 18h). Root cause #3: `taRefresh` silently discarded `ok:false` — operator clicked into void. Fix (v2.2.0): `health.py` `REFRESH_VIA` maps every source to its refresh mechanism; TTL gates aligned; `taRefresh` shows "⏳ busy" on failure. **Implication for new data sources: register in both `TTL_HOURS` AND `REFRESH_VIA`, or the source appears stale with no refresh path.**

### 2026-06-11 — Data Health surface (v2.1.0) — what to expect on bootstrap
> Archived 2026-07-06: stable feature, documented in PROJECT_LOG.md.

The dashboard carries a sticky DATA slot in the Action Rail plus a collapsed Data Health panel. Each per-source row shows chip counts (✓ fresh, ⏰ stale, ⚠ transient-error, 🛑 permanent-error, — no-coverage, ? missing). The health classifier (`health.py`) is pure-logic and tested (41 tests). v2.0.x found four bugs where degraded data rendered identically to good data — the Data Health surface makes the difference visible.

### 2026-06-10 — Sentiment classifier had no LLM fallback — a single Gemma 429 killed the whole source
> Archived 2026-07-06: enforced-by-test; promoted to the vault's Lessons — Cross-Project.md (silent-fallback class).

`sentiment_cache.classify_messages` made ONE LLM call; on any failure (including transient 429s) it gave up. `FALLBACK_MODEL` was defined but never referenced. Fix: `_classify_one_attempt` + a retry loop that calls the fallback on a transient error (429, 5xx, network), with `_is_transient_error` explicitly enumerating codes so future tweaks can't accidentally widen "transient". Validated: re-scoring RGLD surfaced a real 🔥 EXTREME_BULL read that had been silently hidden.
Enforced-by: tests/test_classifier_fallback.py

### 2026-06-10 — Sentiment classifier had no relevance gate — off-topic items polluted bull/bear%
> Archived 2026-07-06: settled, pattern now baked into the classifier.

The classifier scored every body as bull/bear/neutral with no way to flag "this isn't actually about the ticker" (e.g. "Microsoft Project Solara" polluting the SOL HN signal). Fix: added `relevance: primary|mention|none` to the output schema — `none` gets zero weight, `mention` half weight, `primary` full weight. The company-name label is passed in the prompt so the LLM can distinguish "Solana" from "Microsoft Project Solara".

### 2026-06-10 — BTFD/STR panel: naïve zip() pairing crypto rows by index silently dropped candidates
> Archived 2026-07-06: enforced-by-test; promoted to the vault's Lessons — Cross-Project.md (zip-by-index class).

The Action Rail showed `2 BTFD` but the panel rendered only 1 candidate. `crypto_rows` comes back from CoinGecko in market-cap order, not watchlist order — a naive `zip(watchlist, crypto_rows)` paired entries by position instead of identity. Fix: lookup-by-symbol (`{sym: row for row in ...}`). **Audit recipe: any time "rail count = X but panel shows Y" for crypto-derived signals, suspect a zip-by-index.**
Enforced-by: tests/test_data_join.py

### 2026-06-10 — Mobile expanded-row dropdown was rendering 1543px wide in a 390px viewport
> Archived 2026-07-06: settled, narrow CSS bug.

The mobile CSS made `.panel table` `min-width: 1100px` so the body fits 16 columns; the expanded row's `<td colspan>` inherited that min-width and rendered ~1543px wide on a 390px viewport. Fix: `.exp-details-content` uses `position: sticky; left: 0; max-width: calc(100vw - 24px)`.

### 2026-06-10 — HN sentiment: `num_comments>=3` filter silently dropped niche-ticker coverage
> Archived 2026-07-06: settled fix with an audit recipe.

The Algolia search's `num_comments>=3` floor eliminated every real signal for non-mainstream names (niche posts often sit at 1-2 comments). Fix: lowered `MIN_COMMENTS_FILTER` to 1. Tradeoff: admits some noise (e.g. "Microsoft Project Solara" for SOL), tolerable because the downstream classifier's relevance gate handles it. **Audit recipe:** `python3 .claude/skills/hn-sentiment/hn_sentiment.py --show` lists per-ticker queries + cache freshness.

### 2026-06-10 — News-glyph LLM scoring: KLSE non-English headlines need a company-label in the prompt
> Archived 2026-07-06: settled fix, audit tool documented separately.

80%+ of Chinese-press KLSE headlines scored `relevance=none` and silently dropped — the model had no way to know a 4-digit Bursa code maps to a Chinese company name. Fix: `COMPANY_LABELS` map carries both Latin and Chinese forms per KLSE ticker. **What NOT to do: don't auto-add COMPANY_LABELS entries via watchlist parsing** — manual map entry on watchlist add is correct. Audit tool: `python3 .claude/skills/us-news/audit_glyph.py`.

### 2026-06-07 — macOS XProtect popup on dashboard build — investigated, unreproducible at real load
> Archived 2026-07-06: settled investigation, defensive logging in place.

Occasional "Malicious Script Blocked" popup during `dashboard.py --with-discovery`. Diagnostic testing showed 2/10/50/130 sequential `yf.Ticker(t).info` calls all completed clean — the "130 rapid calls trip XProtect" hypothesis was based on an upper bound that never actually happens (real load is ~1-2 calls/run). Plausible actual cause: a one-off XProtect signature push, unrelated process, or intermittent borderline match. Defensive `print` line added to the fundamentals loop so if it fires again there's actionable diagnostic data. Verified end-to-end 2026-06-08 with no recurrence across the full verification pass. **What NOT to do: don't ship a fundamentals-path migration to FMP-only "as a precaution"** — the real load doesn't justify it.

### 2026-06-15 — Free, no-spend sentiment re-scoring: the `sentiment-inline` skill
> Archived 2026-07-06: feature documentation, see the skill's own SKILL.md.

The `sentiment-cache` LLM leg (OpenRouter free models) is the slow part of a build. `sentiment-inline` monkeypatches only the `classify_messages` LLM call so a session can score inline, reusing 100% of the real pipeline. Manual, session-only — NOT headless. Landmines mapped while scoring real feeds: StockTwits/HN are heavily polluted (promo spam, look-alike company names) — the `relevance: none` discount does real work to keep them from diluting the on-topic read.

### 2026-06-15 — launchd can't daemonize from ~/Documents (macOS TCC); + server dual-stack
> Archived 2026-07-06: [reference-only since 2026-06-29 — project moved to the external SSD; the launchd/TCC-under-~/Documents failure mode no longer applies to this repo, kept as general reference for any project still under ~/Documents/~/Desktop/~/Downloads]. The dual-stack bind fix below is a settled, already-applied code change.

**1. Dual-stack bind.** `server.py` bound IPv4-only; macOS `localhost` resolves to `::1` (IPv6) first, and Tailscale MagicDNS hands out an IPv6 address — both got connection-refused. Fix: `DualStackHTTPServer(ThreadingHTTPServer)` with `address_family = AF_INET6` and `setsockopt(IPPROTO_IPV6, IPV6_V6ONLY, 0)`, binding `::` in `--lan`. Verify with `lsof` showing `IPv6 ... TCP *:PORT (LISTEN)` and curling both `127.0.0.1` and `[::1]`.

**2. launchd LaunchAgent flaps with `EX_CONFIG` (78) when the job lives under ~/Documents.** `~/Documents` (also `~/Desktop`, `~/Downloads`) is TCC-protected; a launchd agent can't read the script / write StandardOutPath there. The interactive shell only works because it inherited Terminal's TCC grant. No scriptable fix — either grant Full Disk Access to `/usr/bin/python3` (one-time, manual, GUI), or move the project out of `~/Documents` (done, 2026-06-29). Until then, run detached with `nohup … & disown` (inherits the session's TCC grant, survives the session but not reboot/logout).

**Bonus gotcha:** a long-lived `server.py` (≈4 days) wedged — `/api/status` still answered 200 but `/`/`/dashboard.html` returned `ERR_EMPTY_RESPONSE`. A clean restart cleared it.

### 2026-06-26 (excised) — The TCC trap and the "no LaunchAgent" reasoning, kept as reference
> Archived 2026-07-06: [reference-only since 2026-06-29 — project moved to the external SSD; see the 2026-06-29 entry in `notes/learned.md`]. Excised from the 2026-06-26 entry (which otherwise stays in `notes/learned.md` Hot — the launch instructions are still live) to keep Hot's budget down.

An earlier session explored making the dashboard autostart via a LaunchAgent and discovered the TCC trap below; the LaunchAgent + autostart .command + Application Support directory were all removed when Kenson said autostart wasn't wanted. If a future session is tempted to "make it persistent again," check with Kenson first — manual launch is the standing preference.

A naive LaunchAgent like `ProgramArguments = [/usr/bin/python3, .../server.py, --lan, --port, 8787]` **silently fails with exit code 78 (EX_CONFIG)** because the project lived under `~/Documents/`, which macOS TCC treats as protected. A launchd-spawned process has NO TCC grants for `~/Documents` and errors with `Operation not permitted` before `server.py` is even read. Symptoms in `launchctl print`: `state = spawn scheduled` (forever); `last exit code = 78: EX_CONFIG`; nothing in StandardOutPath if that path is also in `~/Documents`.

The workaround that **did** work (if ever wanted again) is `/usr/bin/open -g -j <autostart.command>` from a LaunchAgent, where the autostart .command lives outside ~/Documents and nohup-detaches a python that the user-session Terminal launches. `open` dispatches via LaunchServices so the spawned chain inherits the user's TCC grants. Don't set KeepAlive on that pattern — `open` exits immediately and it would respawn forever.
