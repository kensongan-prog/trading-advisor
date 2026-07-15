#!/usr/bin/env python3
"""
moomoo_status.py — read-only MooMoo bridge status for the dashboard's
"Broker (MooMoo)" panel (Bridge Phase 3).

Pure data collection, no rendering. Everything here is READ-ONLY and limited
to the operator's real brokerage context from MooMoo's data/moomoo/*.json.
The former SIMULATE broker-sync path was retired on 2026-07-14 after the
operator confirmed manual TA paper journaling is sufficient.
"""
import json
import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_DIR = SCRIPT_DIR.parent
LEGACY_ENV_FILE = SKILLS_DIR / "broker-sync" / ".env"


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def _moomoo_root():
    """Resolve the read-only MooMoo checkout.

    MOOMOO_ROOT remains the contract. The old broker-sync .env location is
    accepted for compatibility so operators do not need to move configuration
    merely because the SIMULATE consumer was retired.
    """
    raw = os.environ.get("MOOMOO_ROOT", "").strip()
    if not raw and LEGACY_ENV_FILE.is_file():
        for line in LEGACY_ENV_FILE.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "MOOMOO_ROOT":
                raw = value.strip().strip("\"'")
                break
    return Path(raw).expanduser() if raw else None


def collect_broker_status():
    """Returns a dict for render_broker_panel_html(). MOOMOO_ROOT being unset
    is a normal, expected state (the bridge is optional) — not an error."""
    root = _moomoo_root()
    if root is None:
        return {"configured": False, "error": None}

    moomoo_data = root / "data" / "moomoo"
    positions = _read_json(moomoo_data / "positions.json", {})
    ledger = _read_json(moomoo_data / "trade_ledger.json", {})
    ledger_summary = ledger.get("summary") or {}

    return {
        "configured": True,
        "error": None,
        "moomoo_root": str(root),
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
