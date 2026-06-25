"""
test_live_quotes.py — whole-watchlist live-quote loop (Phase 3, live dashboard).

The per-row 🔄 fetchers (Finnhub/Binance/CoinGecko, CORS-clean, browser-direct) are
reused by a "⚡ Live quotes" toggle that sweeps every row on a staggered interval.
Honesty guardrail (§1/§4): live values land in each row's .live-quote span, distinct
from the baked daily close — the authoritative price/RSI/BTFD cells are never
overwritten from a live tick.

Pins the wiring + the staggering so the loop can't silently break or hammer Finnhub.
"""
from pathlib import Path

DASHBOARD_SRC = (Path(__file__).resolve().parent.parent
                 / ".claude" / "skills" / "dashboard" / "dashboard.py").read_text()


def test_live_toggle_and_sweep_defined():
    assert "window.taToggleLive" in DASHBOARD_SRC
    assert "function liveSweep" in DASHBOARD_SRC
    assert 'id="ta-live-btn"' in DASHBOARD_SRC


def test_click_and_sweep_share_one_fetch_path():
    # both the per-row click and the live sweep must call runBtn (no divergent fetch logic)
    assert "async function runBtn" in DASHBOARD_SRC
    assert "if (liveTimer) runBtn(btn)" in DASHBOARD_SRC  # sweep path
    assert "runBtn(btn); });" in DASHBOARD_SRC            # click path


def test_sweep_is_staggered_under_rate_limit():
    # a stagger gap must exist so a sweep of ~13 US names stays well under Finnhub 60/min
    assert "LIVE_STAGGER_MS" in DASHBOARD_SRC
    assert "i * LIVE_STAGGER_MS" in DASHBOARD_SRC


def test_live_does_not_overwrite_authoritative_cells():
    # live render target is the .live-quote sibling span, not the price/RSI cells
    assert "btn.nextElementSibling" in DASHBOARD_SRC
