#!/usr/bin/env python3
"""
moomoo_status.py — read-only MooMoo bridge status for the dashboard's
"Broker (MooMoo)" panel (Bridge Phase 3).

Pure data collection, no rendering (mirrors quality_flags.py's split).
Reuses broker-sync's own MOOMOO_ROOT resolution and cache files — single
source of truth, no duplicated config (cross-skill import, same pattern as
j.py's sync_portfolio() -> dashboard/portfolio.py).

Everything here is READ-ONLY: TA's own .claude/cache/moomoo_sync/*.json
(written by broker-sync) plus MooMoo's data/moomoo/*.json (a different repo,
never written to). No order controls belong anywhere near this module — see
the vault note "Bridge Contract — Trading Advisor ↔ MooMoo".

Two clearly-separated halves in the returned dict:
  - "sync" / "review"  — the PAPER (SIMULATE) picture broker-sync tracks;
    this is what TA's Phase 1 doctrine actually cares about.
  - "real"             — the operator's actual brokerage account (real
    positions, real realized P&L). Informational context only; never
    conflated with paper-trading decisions.
"""
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_DIR = SCRIPT_DIR.parent

sys.path.insert(0, str(SKILLS_DIR / "broker-sync"))


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def _ticker_from_stem(stem):
    """'2026-06-03_AUPH' -> 'AUPH' (mirrors j.resolve_file's own ticker-tail regex)."""
    if not stem:
        return None
    m = re.match(r"\d{4}-\d{2}-\d{2}_(.+)", stem)
    return m.group(1) if m else stem


def _display_ticker(journal_stem, intent_id):
    """Best-effort short label for the intents table. journal_stem is only
    populated once an order is submitted (has a resolved journal_path) — an
    observed-but-never-submitted intent has neither, so fall back to parsing
    the ticker out of intent_id's own "source:TICKER:path" format rather than
    displaying the whole (long, path-laden) raw string."""
    ticker = _ticker_from_stem(journal_stem)
    if ticker:
        return ticker
    parts = str(intent_id or "").split(":")
    if len(parts) >= 2 and parts[1]:
        return parts[1]
    return intent_id or "—"


def collect_broker_status():
    """Returns a dict for render_broker_panel_html(). MOOMOO_ROOT being unset
    is a normal, expected state (the bridge is optional) — not an error."""
    try:
        import broker_sync as bs
    except ImportError as e:
        return {"configured": False, "error": f"broker-sync module unavailable: {e}"}

    root = bs.moomoo_root()
    if root is None:
        return {"configured": False, "error": None}

    sync_state = bs.load_sync_state()
    review = bs.load_review()

    intents = []
    for intent_id, rec in (sync_state.get("synced") or {}).items():
        intents.append({
            "intent_id": intent_id,
            "ticker": _display_ticker(rec.get("journal_stem"), intent_id),
            "journal_stem": rec.get("journal_stem"),
            "order_id": rec.get("order_id"),
            "filled_qty": rec.get("last_filled_qty"),
            "broker_status": rec.get("last_broker_status"),
            "approval_state": rec.get("last_approval_state"),
            "last_action": rec.get("last_action"),
            "synced_at": rec.get("synced_at"),
        })
    intents.sort(key=lambda r: r.get("synced_at") or "", reverse=True)

    moomoo_data = root / "data" / "moomoo"
    positions = _read_json(moomoo_data / "positions.json", {})
    ledger = _read_json(moomoo_data / "trade_ledger.json", {})
    ledger_summary = ledger.get("summary") or {}

    return {
        "configured": True,
        "error": None,
        "moomoo_root": str(root),
        "sync": {
            "as_of": sync_state.get("as_of"),
            "n_tracked": len(intents),
            "intents": intents,
        },
        "review": {
            "as_of": review.get("as_of"),
            "items": review.get("items") or [],
        },
        "real": {
            "positions_as_of": positions.get("as_of"),
            "positions": positions.get("positions") or [],
            "ledger_as_of": ledger.get("as_of"),
            "realized_pl": ledger_summary.get("realized_pl"),
            "total_fees": ledger_summary.get("total_fees"),
            "realized_trade_count": ledger_summary.get("realized_trade_count"),
            "open_lot_count": ledger_summary.get("open_lot_count"),
            "issue_count": ledger_summary.get("issue_count"),
        },
    }
