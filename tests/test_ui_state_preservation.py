"""
test_ui_state_preservation.py — an update never throws away your place (Phase 2).

Before: every server-driven update ended in location.reload(), losing scroll
position, expanded rows, sort order, and the watchlist filter. Now the control
server snapshots that state (taCaptureUiState) right before the reload, and the
rebuilt page restores it (taRestoreUiState), keying expanded rows by ticker so they
survive re-sorting and add/remove.

Pins the cross-file wiring so the capture/restore pair can't silently drift apart.
"""
from pathlib import Path

DASH_DIR = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "dashboard"
DASHBOARD_SRC = (DASH_DIR / "dashboard.py").read_text()
SERVER_SRC = (DASH_DIR / "server.py").read_text()


def test_page_defines_and_calls_restore():
    assert "function taRestoreUiState" in DASHBOARD_SRC
    assert "taRestoreUiState();" in DASHBOARD_SRC  # invoked on load


def test_sort_is_factored_for_reuse():
    # restore re-applies a saved sort via applySort — the click handler must share it
    assert "function applySort" in DASHBOARD_SRC
    assert "applySort(t, idx," in DASHBOARD_SRC


def test_server_captures_before_reload():
    assert "function taCaptureUiState" in SERVER_SRC
    # capture must run immediately before the reload, not after (which would be too late)
    assert "taCaptureUiState();location.reload()" in SERVER_SRC


def test_shared_sessionstorage_key():
    # both halves must use the same key or the handoff silently no-ops
    assert "ta_ui_state" in DASHBOARD_SRC
    assert "ta_ui_state" in SERVER_SRC
