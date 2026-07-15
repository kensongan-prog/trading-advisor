#!/usr/bin/env python3
"""
broker_sync.py — deprecated compatibility implementation of the former
TA-side Phase 2 Trading Advisor ↔ MooMoo SIMULATE bridge.

MooMoo paper execution is disabled and manual TA paper journaling is the
current workflow. The CLI refuses to run unless
`TA_ENABLE_LEGACY_BROKER_SYNC=true` is set deliberately.

Reads MooMoo's `staged_orders.json` (SIMULATE/paper only, read-only, via
MOOMOO_ROOT) and attributes fills back into the correct journal entries via
the exact chain: staged order -> journal_path -> j.py mutation. MooMoo already
aggregates per-intent fill state (filled_qty, filled_avg_price, fill_count,
approval_state) in staged_orders.json — this skill does NOT re-derive that
from raw fills; it consumes MooMoo's own aggregate and writes into TA's own
journal via TA's own j.py, TA's own confirm/backup/portfolio-sync path.

See the vault note "Bridge Contract — Trading Advisor ↔ MooMoo" for the full
cross-repo contract this implements (Phase 2).

Design (see notes/learned.md 2026-07-02 for the full rationale):
  - Read-only into MooMoo's repo; TA only ever writes its own files
    (journal/*.md via j.py, plus this skill's own cache/state).
  - BUY fills flip PROSPECTUS -> LIVE (first fill) or append an Updates note
    (subsequent partial-fill growth). Never re-flips an already-LIVE journal.
  - SELL fills are NEVER auto-processed — closing a position requires
    win/loss/scratch/timeout classification (doctrine SS9), which needs
    human judgment j.py's own `close` command already requires explicit
    --result for. Every SELL fill lands in the review artifact instead.
  - A journal already CLOSED/DEAD is never touched, even if the broker shows
    a later fill ("don't regress journal state that's already ahead").
  - Journal resolution matches by the FULL STEM of journal_path's basename
    (not the raw absolute path string, which may encode a different
    machine's checkout) via j.resolve_file()'s exact-stem-match path --
    journal filenames are unique in this project's convention, so this is
    exact traceability, not a heuristic.
  - Idempotent: a TA-owned sync_state.json records the last-observed
    filled_qty/approval_state per intent_id; a run that finds nothing new
    performs zero journal writes.

Legacy maintenance only:
    python3 .claude/skills/broker-sync/broker_sync.py sync           # preview + confirm
    python3 .claude/skills/broker-sync/broker_sync.py sync --yes     # execute without prompting
    python3 .claude/skills/broker-sync/broker_sync.py show           # read-only: last sync state + review
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILLS_DIR.parent.parent
STATE_DIR = PROJECT_ROOT / ".claude" / "cache" / "moomoo_sync"
STATE_PATH = STATE_DIR / "sync_state.json"
REVIEW_PATH = STATE_DIR / "review.json"
LEGACY_ENABLE_ENV = "TA_ENABLE_LEGACY_BROKER_SYNC"

sys.path.insert(0, str(SKILLS_DIR / "journal"))
import j  # noqa: E402  — same-repo cross-skill import, mirrors j.py's own sync_portfolio() -> dashboard/portfolio.py


# ── Config ───────────────────────────────────────────────────────────────
def load_env():
    """Read MOOMOO_ROOT from .claude/skills/broker-sync/.env, mirroring
    wl.py's load_env() pattern. Env var (if already set) always wins."""
    env_path = SCRIPT_DIR / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip(); v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def moomoo_root():
    """Resolve MOOMOO_ROOT. Returns a Path or None (never guesses a default —
    an unconfigured path is a hard stop, not a heuristic fallback)."""
    load_env()
    val = os.environ.get("MOOMOO_ROOT")
    if not val:
        return None
    p = Path(val).expanduser()
    return p if p.is_dir() else None


# ── JSON I/O ─────────────────────────────────────────────────────────────
def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str))
    tmp.replace(path)  # atomic


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_sync_state():
    return _read_json(STATE_PATH, {"as_of": None, "synced": {}})


def save_sync_state(state):
    state["as_of"] = now_iso()
    _write_json(STATE_PATH, state)


def load_review():
    return _read_json(REVIEW_PATH, {"as_of": None, "items": []})


def save_review(items):
    _write_json(REVIEW_PATH, {"as_of": now_iso(), "items": items})


# ── MooMoo artifact reads (read-only) ─────────────────────────────────────
def load_staged_orders(root):
    """Return only SIMULATE (paper) staged orders — broker-sync never touches
    REAL/live rows; MooMoo's own ledger already ignores SIMULATE for realized
    P&L, so this is the ONLY place paper attribution happens."""
    payload = _read_json(root / "data" / "moomoo" / "staged_orders.json", {"orders": []})
    return [o for o in payload.get("orders", []) if str(o.get("env") or "").upper() == "SIMULATE"]


# ── Journal resolution ─────────────────────────────────────────────────────
def resolve_journal(journal_path):
    """Resolve MooMoo's recorded journal_path to a real file in journal/ by
    FULL STEM (basename minus extension) -- deliberately not the raw absolute
    path string, which may encode a different machine's checkout location.
    Journal filenames are unique in this project's convention, so this hits
    j.resolve_file()'s exact-stem-match branch: exact traceability, not a
    heuristic. Returns the Path, or None if unresolvable."""
    if not journal_path:
        return None
    stem = Path(str(journal_path)).stem
    if not stem:
        return None
    try:
        return j.resolve_file(stem)
    except SystemExit:
        return None


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── Planning (pure — no side effects, fully testable) ─────────────────────
def decide_action(staged, journal_status, prior):
    """Decide what (if anything) to do for one SIMULATE staged order.

    staged: one row from staged_orders.json (already filtered to SIMULATE).
    journal_status: the resolved journal's current **Status:** text, or None
        if the journal couldn't be resolved.
    prior: this intent_id's previous record from sync_state.json, or None.

    Returns (action, review_reason, note) where action is one of:
        'none'             — nothing to do (no fill yet, or already synced)
        'flip_live'        — first fill on a PROSPECTUS journal -> j.py live
        'update_partial'   — fill grew on an already-LIVE journal -> j.py update
        'skip_journal_ahead' — journal is CLOSED/DEAD; broker fill ignored,
                               never regress a journal that's already ahead
        'review'           — needs a human; review_reason explains why
    """
    side = str(staged.get("side") or "").upper()
    filled_qty = _f(staged.get("filled_qty"))
    filled_avg_price = _f(staged.get("filled_avg_price"))

    if side not in ("BUY", "SELL"):
        # A structural anomaly worth surfacing regardless of fill state.
        return "review", "unsupported_side", f"unexpected order side {side!r}"

    if not filled_qty:
        # The common case: a staged/submitted order with no fill yet. Nothing to
        # attribute, so we deliberately do NOT even look at journal_path/journal_status
        # here — an order that hasn't been submitted often has no journal_path at
        # all yet, and that is normal, not a review-worthy state.
        return "none", None, "no fill yet"

    if side == "SELL":
        return "review", "sell_fill_needs_manual_review", (
            f"SELL fill {filled_qty:g} @ {filled_avg_price} — closing needs win/loss/scratch/timeout "
            f"classification (doctrine SS9); run `j.py close` manually if this closes the position"
        )

    # side == BUY with a real fill from here — this is the only branch where an
    # unresolved journal is actually a problem worth reviewing.
    if journal_status is None:
        return "review", "journal_path_not_found", (
            f"journal_path {staged.get('journal_path')!r} did not resolve to a real journal file"
        )

    if abs(filled_qty - round(filled_qty)) > 1e-6:
        return "review", "non_integer_fill_qty", f"filled_qty {filled_qty} is not a whole share count"

    prior_filled = _f((prior or {}).get("last_filled_qty")) or 0.0
    if filled_qty < prior_filled - 1e-9:
        return "review", "filled_qty_decreased", (
            f"broker filled_qty {filled_qty:g} is LESS than the previously recorded {prior_filled:g} "
            f"— never act on a regression, needs manual investigation"
        )

    status_upper = (journal_status or "").upper()

    if status_upper.startswith("CLOSED") or status_upper.startswith("DEAD"):
        return "skip_journal_ahead", None, (
            f"journal status is {journal_status!r} but broker shows a fill — journal already ahead, not touching it"
        )

    if status_upper.startswith("LIVE"):
        if filled_qty > prior_filled + 1e-9:
            return "update_partial", None, f"fill grew {prior_filled:g} -> {filled_qty:g} @ {filled_avg_price}"
        return "none", None, "already LIVE, no fill change since last sync"

    if status_upper.startswith("PROSPECTUS") or not status_upper:
        return "flip_live", None, f"first fill detected: {filled_qty:g} @ {filled_avg_price}"

    return "review", "unexpected_journal_status", (
        f"journal status {journal_status!r} not recognized (expected PROSPECTUS/LIVE/CLOSED/DEAD)"
    )


def build_plan(staged_orders, prior_state):
    """Pure planning pass: resolve each staged order's journal + decide its
    action. No side effects (no journal writes, no state writes) — this is
    what makes the whole loop dry-run-able and unit-testable without mocking
    j.py's file I/O."""
    synced = (prior_state or {}).get("synced", {})
    plan = []
    for staged in staged_orders:
        intent_id = str(staged.get("intent_id") or "")
        journal_path = staged.get("journal_path")
        journal_file = resolve_journal(journal_path)
        journal_status = j.read_status(journal_file.read_text()) if journal_file else None
        prior = synced.get(intent_id)

        action, review_reason, note = decide_action(staged, journal_status, prior)

        plan.append({
            "intent_id": intent_id,
            "code": staged.get("code"),
            "market": staged.get("market"),
            "side": staged.get("side"),
            "order_id": staged.get("order_id"),
            "broker_status": staged.get("broker_status"),
            "approval_state": staged.get("approval_state"),
            "filled_qty": _f(staged.get("filled_qty")),
            "filled_avg_price": _f(staged.get("filled_avg_price")),
            "fill_count": staged.get("fill_count"),
            "last_fill_at": staged.get("last_fill_at"),
            "journal_path": journal_path,
            "journal_stem": journal_file.stem if journal_file else None,
            "journal_status": journal_status,
            "action": action,
            "review_reason": review_reason,
            "note": note,
        })
    return plan


# ── Execution (side effects — only runs on confirmed actionable items) ────
def execute_item(item):
    """Run the real j.py mutation for one actionable plan item. Returns
    (ok: bool, detail: str). Assumes the caller already obtained one combined
    confirm for the whole batch -- j.py's own confirm is always bypassed here
    (yes=True) so we don't double-prompt."""
    shares = int(round(item["filled_qty"])) if item["filled_qty"] is not None else None
    src_note = f"MooMoo broker-sync — order {item.get('order_id') or '?'} ({item.get('broker_status') or '?'})"

    if item["action"] == "flip_live":
        args = SimpleNamespace(
            id=item["journal_stem"], paper=True, real=False,
            fill=item["filled_avg_price"], shares=shares,
            time=item.get("last_fill_at"), notes=src_note, yes=True,
        )
        rc = j.cmd_live(args)
        return rc == 0, "flipped LIVE — paper"

    if item["action"] == "update_partial":
        note = (f"MooMoo broker-sync — fill grew to {item['filled_qty']:g} @ {item['filled_avg_price']} "
                f"(order {item.get('order_id') or '?'}, {item.get('broker_status') or '?'})")
        args = SimpleNamespace(id=item["journal_stem"], notes=note, yes=True)
        rc = j.cmd_update(args)
        return rc == 0, "posted Updates note"

    return False, f"no executor for action {item['action']!r}"


def execute_plan(plan):
    """Execute every actionable item, return (updated_synced_dict, review_items,
    executed_count). Every item — actionable or not — gets a fresh sync_state
    record, so idempotency and 'show' both reflect the FULL current picture,
    not just what changed this run."""
    now = now_iso()
    synced = {}
    review = []
    executed = 0

    for item in plan:
        record = {
            "journal_stem": item["journal_stem"],
            "order_id": item.get("order_id"),
            "last_filled_qty": item["filled_qty"],
            "last_filled_avg_price": item["filled_avg_price"],
            "last_broker_status": item.get("broker_status"),
            "last_approval_state": item.get("approval_state"),
            "last_action": item["action"],
            "synced_at": now,
        }

        if item["action"] in ("flip_live", "update_partial"):
            ok, detail = execute_item(item)
            record["last_action"] = item["action"] if ok else "execution_failed"
            record["last_action_detail"] = detail
            if ok:
                executed += 1
            else:
                review.append({**item, "review_reason": "execution_failed", "detail": detail})
        elif item["action"] == "review":
            review.append(item)

        if item["intent_id"]:
            synced[item["intent_id"]] = record

    return synced, review, executed


# ── CLI ──────────────────────────────────────────────────────────────────
def _fmt_item(item):
    tag = f"[{item['action']}]"
    reason = f" ({item['review_reason']})" if item.get("review_reason") else ""
    return f"  {tag:<18} {item.get('code') or '?':<10} {item.get('journal_stem') or '(unresolved)':<24} {item['note']}{reason}"


def cmd_sync(args):
    root = moomoo_root()
    if root is None:
        print("ERROR: MOOMOO_ROOT is not set or not a directory.", file=sys.stderr)
        print(f"  Set it in {SCRIPT_DIR / '.env'} or the environment (see .env.example).", file=sys.stderr)
        return 2

    staged_orders = load_staged_orders(root)
    prior_state = load_sync_state()
    plan = build_plan(staged_orders, prior_state)

    actionable = [i for i in plan if i["action"] in ("flip_live", "update_partial")]
    review_items = [i for i in plan if i["action"] == "review"]
    skipped_ahead = [i for i in plan if i["action"] == "skip_journal_ahead"]
    noop = [i for i in plan if i["action"] == "none"]

    print(f"MOOMOO_ROOT: {root}")
    print(f"SIMULATE staged orders: {len(staged_orders)}")
    print()

    if actionable:
        print(f"Will update {len(actionable)} journal(s):")
        for item in actionable:
            print(_fmt_item(item))
    else:
        print("No journal updates needed.")

    if review_items:
        print(f"\n⚠ {len(review_items)} item(s) need manual review (see review.json):")
        for item in review_items:
            print(_fmt_item(item))

    if skipped_ahead:
        print(f"\nℹ {len(skipped_ahead)} item(s) skipped — journal already ahead of the broker event:")
        for item in skipped_ahead:
            print(_fmt_item(item))

    print(f"\n({len(noop)} already in sync, no action needed)")

    if not actionable:
        # Still persist the observed state (idempotency baseline) + review, even with nothing to execute.
        synced, review, _ = execute_plan(plan)
        save_sync_state({"synced": synced})
        save_review(review)
        return 0

    print()
    if not args.yes and not j.confirm(f"Proceed with {len(actionable)} journal update(s)?"):
        print("Aborted. No journals were changed.")
        return 0

    synced, review, executed = execute_plan(plan)
    save_sync_state({"synced": synced})
    save_review(review)
    print(f"\n✓ Synced {executed}/{len(actionable)} journal update(s).")
    if review:
        print(f"⚠ {len(review)} item(s) in {REVIEW_PATH.relative_to(PROJECT_ROOT)} need manual attention.")
    return 0


def cmd_show(args):
    state = load_sync_state()
    review = load_review()
    synced = state.get("synced", {})
    print(f"Last sync: {state.get('as_of') or 'never'}")
    print(f"Tracked intents: {len(synced)}")
    for intent_id, rec in synced.items():
        print(f"  {rec.get('journal_stem') or intent_id}: {rec.get('last_action')} "
              f"(filled {rec.get('last_filled_qty')}, {rec.get('last_broker_status')}) "
              f"@ {rec.get('synced_at')}")
    print(f"\nReview items: {len(review.get('items', []))} (as of {review.get('as_of') or 'never'})")
    for item in review.get("items", []):
        print(_fmt_item(item))
    return 0


def main():
    if os.environ.get(LEGACY_ENABLE_ENV, "").strip().lower() != "true":
        print(
            "ERROR: broker-sync is deprecated because MooMoo paper execution is disabled. "
            "Use Trading Advisor's manual journal lifecycle. Set "
            f"{LEGACY_ENABLE_ENV}=true only for deliberate legacy-data maintenance.",
            file=sys.stderr,
        )
        return 2
    ap = argparse.ArgumentParser(description="TA-side broker-sync: MooMoo paper fills -> journal.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("sync", help="Read MooMoo SIMULATE fills, sync matching journals")
    ps.add_argument("--yes", "-y", action="store_true")
    ps.set_defaults(func=cmd_sync)

    psh = sub.add_parser("show", help="Print current sync state + review items (read-only)")
    psh.set_defaults(func=cmd_show)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
