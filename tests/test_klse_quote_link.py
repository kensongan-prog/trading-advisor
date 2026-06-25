"""
test_klse_quote_link.py — the dashboard's KLSE 📊 quote button must use a real
klsescreener path.

Bug (2026-06-25): clicking a KLSE ticker's quote button (e.g. KJTS / 0293) opened
`klsescreener.com/v2/stocks/quote/{code}`, which 404s ("Not Found"). The real path
is `/v2/stocks/view/{code}` — the exact path both the `klse-quote` and
`klse-refresh` skills already use to fetch the same page. The link template had
drifted to a path that never existed.

These pin the correct path so the dashboard link can't drift away from the
fetch path the rest of the project relies on.
"""
from pathlib import Path

DASHBOARD_PY = (
    Path(__file__).resolve().parent.parent
    / ".claude" / "skills" / "dashboard" / "dashboard.py"
)
SRC = DASHBOARD_PY.read_text()


def test_klse_quote_button_uses_view_path():
    assert "/v2/stocks/view/" in SRC, "KLSE quote button must link to the real /view/ path"


def test_klse_quote_button_never_uses_404_quote_path():
    # /v2/stocks/quote/ is the path that returns HTTP 404 on klsescreener.
    assert "/v2/stocks/quote/" not in SRC, (
        "klsescreener.com/v2/stocks/quote/ 404s — use /v2/stocks/view/ instead"
    )
