"""
test_panel_fragments.py — in-place panel refresh (Phase 5, live dashboard).

render_health_panel was extracted from the monolithic render_html closure into a
standalone render_health_panel_html(...) so the control server can re-render JUST the
Data Health panel (/api/panel/health) from current cache states — no data fetch, no
full rebuild, no reload. The client swaps the panel's contents in place; the collapse
toggle is now delegated so a swapped panel still folds.

Pins the standalone renderer, the endpoint handler, and the client wiring.
"""
import sys
from pathlib import Path

DASH_DIR = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "dashboard"
sys.path.insert(0, str(DASH_DIR))
import dashboard  # noqa: E402
import health  # noqa: E402
import server  # noqa: E402


def test_health_fragment_renders_standalone():
    recs = health.collect_health(dashboard.parse_watchlist())
    frag = dashboard.render_health_panel_html(
        health, health.summarize(recs), health.group_by_source(recs))
    assert 'id="data-health-panel"' in frag   # stable swap target
    assert 'id="ta-health-data"' in frag      # toast-diff dataset travels with it
    assert "Data Health" in frag


def test_health_fragment_unavailable_is_graceful():
    frag = dashboard.render_health_panel_html(None, None, {}, "boom")
    assert "unavailable" in frag and "panel" in frag


def test_panel_health_endpoint_handler():
    # _panel_health uses no instance state — call it unbound to avoid a real socket
    res = server.Handler._panel_health(None)
    assert res["ok"] is True
    assert 'id="data-health-panel"' in res["html"]


def test_client_and_server_wiring():
    dash_src = (DASH_DIR / "dashboard.py").read_text()
    srv_src = (DASH_DIR / "server.py").read_text()
    assert "async function taRefreshHealthPanel" in dash_src
    assert "/api/panel/health" in dash_src            # client fetches it
    assert '"/api/panel/health"' in srv_src           # server routes it
    # collapse is delegated so a swapped panel still folds
    assert "e.target.closest('.panel > h2')" in dash_src
