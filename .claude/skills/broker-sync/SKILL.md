---
name: broker-sync
description: DEPRECATED compatibility skill for the retired MooMoo-owned SIMULATE paper flow. MooMoo paper execution is disabled; Trading Advisor now uses manual paper journaling. Do not run this as part of the current workflow.
---

# broker-sync — MooMoo paper fills → journal

> **Deprecated 2026-07-14.** MooMoo no longer owns paper execution, and the
> operator confirmed manual Trading Advisor paper journaling is sufficient.
> This implementation remains only as historical compatibility code. Do not
> run, schedule, or extend it unless a future architecture decision explicitly
> introduces a new paper simulator contract.

The feedback half of the Trading Advisor ↔ MooMoo bridge (see the vault note
"Bridge Contract — Trading Advisor ↔ MooMoo" for the full cross-repo contract).
MooMoo (`Projects/Codex/MooMoo`) owns broker execution and already aggregates
per-intent fill state in `data/moomoo/staged_orders.json` — this skill reads
that read-only and writes into TA's own journal via TA's own `j.py`, nothing
else.

## Usage

```bash
python3 .claude/skills/broker-sync/broker_sync.py sync          # preview, then confirm
python3 .claude/skills/broker-sync/broker_sync.py sync --yes    # execute without prompting
python3 .claude/skills/broker-sync/broker_sync.py show          # read-only: last sync state + review items
```

Config: set `MOOMOO_ROOT` in `.claude/skills/broker-sync/.env` (copy from
`.env.example`) or the environment — the absolute path to the MooMoo repo.
Manual by design — no cron, run it whenever you want journal state to catch
up with the paper broker.

## What it does

For every **SIMULATE** staged order (paper only — MooMoo's realized-P&L
ledger intentionally ignores SIMULATE rows, so this is the only place paper
fills get attributed anywhere):

1. Resolve `journal_path` to a real file in `journal/` by the **full stem**
   of its basename (not the raw absolute path, which may encode a different
   machine's checkout) — exact traceability, not a heuristic.
2. **BUY, first fill, journal still PROSPECTUS** → `j.py live --paper --fill
   --shares` (flips status, one time).
3. **BUY, fill grew further, journal already LIVE** → `j.py update` (an
   Updates note recording the new total — never re-flips status).
4. **BUY, journal already CLOSED/DEAD** → skipped entirely. Never regress a
   journal that's already ahead of the broker event.
5. **SELL fill (any)** → always lands in the review artifact. Closing a
   position needs win/loss/scratch/timeout classification (doctrine §9),
   which is a human judgment call `j.py close --result` already requires
   explicitly — broker-sync never guesses it.
6. **filled_qty decreased since last sync, non-integer share count, an
   unresolvable journal_path, an unrecognized journal status** → all land in
   the review artifact rather than being silently dropped or guessed at.

## Idempotency

`.claude/cache/moomoo_sync/sync_state.json` records the last-observed
`filled_qty`/`approval_state` per `intent_id`. A re-run that finds nothing new
performs **zero** journal writes — not even a no-op confirm prompt. Every
staged order (acted-on or not) gets a fresh record each run, so `show` always
reflects the current full picture.

## Review artifact

`.claude/cache/moomoo_sync/review.json` — regenerated fresh every run (not
appended forever), so a resolved issue disappears on its own next time. Printed
prominently in `sync`'s output too; never silent.

## Landmine already caught

A staged-but-not-yet-submitted order (the common case — `approval_state:
"staged"`, no fill, often no `journal_path` yet) must NOT be flagged for
review just because its journal can't be resolved — there's nothing to
attribute. The no-fill-yet check runs *before* journal resolution is even
attempted. See `notes/learned.md` 2026-07-02.

## See also

- `journal` skill (`j.py`) — the actual mutation path this calls into
- Vault: "Bridge Contract — Trading Advisor ↔ MooMoo"
