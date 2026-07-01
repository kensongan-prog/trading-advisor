"""
test_news_glyph_klse.py — KLSE news window filter in news_glyph.refresh_klse.

news_glyph already scrapes KLSE news (do NOT build a parallel fetcher — see
notes/learned.md). These pin the 2026-07-01 additions: a 180-day recency window
(a ceiling for firehose names, a floor that trims quiet names' stale tail) and
the HTML-entity decode in the headline cleaner.
"""
from datetime import datetime, timezone, timedelta

import news_glyph as ng


def _iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def test_window_keeps_recent_drops_stale():
    items = [
        {"headline": "recent", "date": _iso(10)},
        {"headline": "old", "date": _iso(400)},
        {"headline": "edge-in", "date": _iso(179)},
        {"headline": "edge-out", "date": _iso(181)},
    ]
    kept = {i["headline"] for i in ng._window_klse_items(items, 180)}
    assert kept == {"recent", "edge-in"}


def test_window_keeps_undated_items():
    # dropping undated items would silently lose coverage
    items = [{"headline": "no-date", "date": None}, {"headline": "bad-date", "date": "not-a-date"}]
    assert len(ng._window_klse_items(items, 180)) == 2


def test_window_disabled_is_passthrough():
    items = [{"headline": "x", "date": _iso(9999)}]
    assert ng._window_klse_items(items, 0) == items


def test_clean_decodes_html_entities():
    # the nested _clean in _scrape_klse_news must unescape; verify the module
    # imports html and unescape works as used (&#039; -> ', &amp; -> &).
    import html
    assert html.unescape("Seni Jaya&#039;s Q3 &amp; more") == "Seni Jaya's Q3 & more"
