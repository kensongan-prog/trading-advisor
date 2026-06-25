"""
test_watchlist_add_consolidation.py — one watchlist-add UI, no lost functionality.

Bug (2026-06-25): adding a ticker (MU) appeared to fail two different ways.
  - The static dashboard "Watchlist Manager" only *generated a copy-paste wl.py
    command* with no dashboard rebuild — so a successful CLI add stayed invisible
    on the static dashboard.html.
  - The server control-panel form ran wl.py live AND rebuilt, but rejected the
    already-added ticker as a duplicate.
Two redundant add UIs, one of which couldn't show its own result.

Fix: remove the static "Watchlist Manager" (the operator drives via the server),
leaving the live control-panel form as the single add/remove/update path. To not
lose functionality, the server form gained the static form's section-override and
force-add (--allow-unresolved) options.

These pin (a) the server handler forwards section + force-add to wl.py, and
(b) the static copy-paste manager is gone from the rendered dashboard.
"""
import sys
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "dashboard"
sys.path.insert(0, str(DASHBOARD_DIR))
import server  # noqa: E402


def _capture_add(body, monkeypatch):
    """Call the watchlist handler with run_cli/JOB stubbed; return the argv built."""
    seen = {}
    monkeypatch.setattr(server, "run_cli", lambda argv, timeout=None: (seen.setdefault("argv", argv), (0, "ok"))[1])

    class _Job:
        def start(self, *a, **k):
            seen["rebuild"] = True
            return True
    monkeypatch.setattr(server, "JOB", _Job())
    res = server.Handler._watchlist(None, body)
    return seen, res


def test_add_forwards_section_and_force(monkeypatch):
    seen, res = _capture_add(
        {"action": "add", "ticker": "MU", "text": "Memory shortage play",
         "section": "us", "allow_unresolved": True}, monkeypatch)
    argv = seen["argv"]
    assert "add" in argv and "MU" in argv
    assert "--thesis" in argv and "Memory shortage play" in argv
    assert argv[argv.index("--section") + 1] == "us"
    assert "--allow-unresolved" in argv
    assert res["ok"] is True
    assert seen.get("rebuild") is True, "a successful add must trigger a dashboard rebuild"


def test_add_auto_section_omits_flags(monkeypatch):
    # auto-classify + no force = clean wl.py invocation (no --section / --allow-unresolved)
    seen, _ = _capture_add(
        {"action": "add", "ticker": "NVDA", "text": "", "section": "auto",
         "allow_unresolved": False}, monkeypatch)
    argv = seen["argv"]
    assert "--section" not in argv
    assert "--allow-unresolved" not in argv


def test_static_watchlist_manager_removed():
    src = (DASHBOARD_DIR / "dashboard.py").read_text()
    # The copy-paste manager's identifiers must be gone — the server form is canonical now.
    for token in ("TA_WL", "wl-form-host", "wl-mode-tabs", "Watchlist Manager"):
        assert token not in src, f"static Watchlist Manager leftover: {token!r}"
