# Decisions — rationale for non-obvious choices

Append-only log of why we did things the way we did. Newest at top. Read this when puzzled by a "why is it like this?" question.

---

### 2026-06-25 — Live-dashboard upgrade (v2.7.0): incremental, client-driven, no daemon
Re-evaluate: 2026-10-04

Reframed `dashboard.html` from a static export into a live, server-backed surface — but as **incremental enrichment of the existing stdlib `server.py`, NOT the deferred 5–6 week FastAPI+SQLite rewrite** (still parked in notes/ideas.md). Four decisions shaped it:

- **Client-driven liveness, no background daemon.** Live quotes stream from the browser while the tab is open; no server-side auto-refresh thread. Consistent with the 2026-06-06 "no rogue background process" stance — the daemon was explicitly offered and the operator declined.
- **State-preservation over flash-free morph.** Planned Phase 2 was an in-place DOM *morph*; doing it safely required re-initializing the ~480-line Risk Simulator + prospectus forms after every swap (high risk, hard to verify without exhaustive browser testing). Shipped the lower-risk path instead — snapshot scroll/expanded/sort/filter → reload → restore — which solves the real pain ("don't lose my place"). Morph remains future polish; it matters less now that cheap updates patch in place (Phase 5).
- **Dropped the planned 2s cache-poll (Phase 4).** Polling server caches every 2s only pays off with a daemon mutating them out-of-band; without one they change only on rebuild. Kept the genuine value: atomic `cache_set` (temp + os.replace) and the in-place Data Health refresh (`/api/panel/health`).
- **One watchlist-add path.** Removed the static copy-paste "Watchlist Manager" (it emitted a `wl.py` command with no rebuild, so a successful add looked broken); the live control-panel form — now a superset with section override + force-add — is canonical.

### 2026-06-08 — Adopted full semver (MAJOR.MINOR.PATCH) mid-project
Re-evaluate: 2026-10-04

After v1.4 shipped, operator pointed out that several recent "minor" releases were actually patches: v1.2 was a README clone-URL typo fix that didn't deserve a MINOR slot. Under our old two-level scheme (`MAJOR.MINOR`), small fixes burned MINOR numbers, making the version signal noisier than it should have been.

Switched to standard `MAJOR.MINOR.PATCH`. Decision rules + edge cases codified upfront in CHANGELOG.md so future release calls don't depend on in-the-moment judgment. PATCH = backward-compat with no new capability and no mental-model shift. MINOR = new capability or mental-model shift. MAJOR = past recommendations re-classified or existing operator setup breaks silently.

**Historical tags not renumbered.** v1.2 stays as it shipped; renumbering would break GitHub release links, tag references, and anyone watching the repo. The "v1.2 would have been v1.1.1" observation lives in CHANGELOG.md as a historical note.

**First semver release: v1.4.1** (this entry's release — pure docs change, no behavior). Next functional release will be v1.5.0.

### 2026-06-08 — CLAUDE.md + AGENTS.md include auto-bootstrap instructions
Re-evaluate: 2026-10-04

Operator asked how to simplify the per-session bootstrap ritual. Three options considered:
- (A) auto-bootstrap via instructions in CLAUDE.md/AGENTS.md (zero typing, leverages existing auto-load)
- (B) custom `/start` slash command (explicit but requires one command)
- (C) standalone SESSION_START.md to paste from (always requires typing)

Chose A. Claude Code auto-loads CLAUDE.md as system prompt; Codex auto-loads AGENTS.md. Imperative instructions in those files get followed reliably. Cost: CLAUDE.md grew from 7 lines (pointer-only) to ~35 lines. Both files now contain mirrored "Session bootstrap" sections so the behavior is identical regardless of which agent loads which.

Bootstrap reads only **3 files** (notes/learned.md + CHANGELOG.md + git log) — explicitly NOT PROJECT_LOG.md (heavy, ~600 lines, on-demand only). Orient out loud in ~5 lines, then wait for the actual request. Skipped via `quick:`/`oneshot:` prefix for one-off questions.

Risk acknowledged: I can't test the auto-bootstrap firing in the session that introduced it. Operator verifies tomorrow by opening a fresh session and seeing if it fires unprompted. If unreliable, fall back to Option B (slash command).

### 2026-06-07 — AGENTS.md is the canonical doctrine file (CLAUDE.md is a pointer)
Re-evaluate: 2026-10-04

We renamed `CLAUDE.md → AGENTS.md` to follow the emerging cross-agent convention. Codex auto-loads `AGENTS.md` natively; Claude Code auto-loads `CLAUDE.md`. The new `CLAUDE.md` is a 7-line pointer that redirects to AGENTS.md so Claude Code still finds the doctrine.

**Why not a separate Codex.md?** Two doctrine files would drift. Single canonical file + thin pointers is cheaper to maintain.

**Why not just rename without the pointer?** Existing forks, external links, and operator notes still reference CLAUDE.md. The pointer keeps backward compatibility free.

See v1.3 release notes.

---

### 2026-06-06 — Daily backup uses Claude CronCreate, not system cron or launchd
Re-evaluate: 2026-10-04

The operator explicitly rejected (a) launchd (auto-mode classifier blocked unauthorized persistence install) and (b) system cron (don't want a background backup script running when Claude isn't open). CronCreate is session-aware: backups only fire while Claude Code is running and the REPL is idle.

**Trade-off:** Jobs auto-expire after 7 days (need re-scheduling) and only fire while Claude is open. Backups can lag if the operator goes 5+ days without opening Claude. Operator accepted this trade in exchange for "no rogue background processes."

See `scripts/README.md` for the alternative (system cron) path documented for other operators.

---

### 2026-06-05 — Public repo + separate private backup remote (not just one repo)
Re-evaluate: 2026-10-04

`origin` = `kensongan-prog/trading-advisor` (public, canonical) — deliberate pushes only, on tagged releases. `backup` = `kensongan-prog/trading-advisor-backup` (private) — daily sync of main + tags via `scripts/sync-backup.sh`.

**Why:** the operator wants the public history to stay clean (versioned releases only) while still having a real off-machine backup for in-progress work. One repo can't serve both.

---

### 2026-06-05 — FMP /stable/ endpoints, not /api/v3/
Re-evaluate: 2026-10-04

FMP migrated their public endpoints from `/api/v3/` to `/stable/` in 2025. All skill code uses `/stable/`. If you see legacy `/api/v3/` URLs anywhere in a future patch, that's a regression to fix.

---

### 2026-06-04 — Position sizing is operator-defined, not formula-dictated
Re-evaluate: 2026-07-05 (overdue — the Risk Simulator has changed multiple times since this decision was recorded; re-confirm the "always pre-populated with max, editable" behavior still matches current UI before trusting it silently)

Doctrine §5 derives the *maximum permitted* size, not the obligatory size. Risk Simulator's Size field auto-prefills to the doctrine maximum but is editable — operators routinely down-size for correlation tax, lower conviction, or partial-fill plans.

**Wrong abstraction we tried first:** "Empty field = use doctrine max, populated field = override." Three review agents (during `/simplify`) independently flagged this as the wrong altitude. Fixed in v1.1 by making the field always pre-populated with the max.
