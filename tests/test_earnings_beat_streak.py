"""
test_earnings_beat_streak.py — Analysis C4: earnings-surprise beat/miss history
as context (not a gate).

_parse_earnings_surprise_history() turns yfinance's Ticker.earnings_dates
DataFrame into a compact, most-recent-first history + a consecutive-beat
streak. earnings_streak_text() renders that into the one-line summary shown
in both the watchlist's expanded row detail and the Discovery panel.
fetch_earnings_beat_streak() is the cached on-demand lookup used for
Discovery candidates (capped to the rendered rows, not the full scanned
universe — see its docstring).
"""
from datetime import datetime, timezone

import pytest

import dashboard


def test_yf_sector_to_spdr_name_covers_every_sector_rotation_row():
    """Every SPDR name sector-rotation.py emits must have a yfinance-sector key
    pointing at it, or Analysis C3's bottom-3 check silently never matches that
    sector for any US ticker."""
    spdr_names = {
        "Technology", "Financials", "Health Care", "Consumer Disc.",
        "Consumer Staples", "Energy", "Industrials", "Materials",
        "Utilities", "Real Estate", "Comm. Services",
    }
    assert set(dashboard.YF_SECTOR_TO_SPDR_NAME.values()) == spdr_names


def test_earnings_streak_text_no_history():
    assert dashboard.earnings_streak_text(0, []) == "—"
    assert dashboard.earnings_streak_text(None, None) == "—"


def test_earnings_streak_text_multi_beat_streak():
    history = [{"date": "2026-05-01", "surprise_pct": 3.2}, {"date": "2026-02-01", "surprise_pct": 1.1}]
    assert dashboard.earnings_streak_text(2, history) == "🔥 2 beats in a row (last +3.2%)"


def test_earnings_streak_text_single_beat():
    history = [{"date": "2026-05-01", "surprise_pct": 0.5}]
    assert dashboard.earnings_streak_text(1, history) == "beat last qtr (+0.5%)"


def test_earnings_streak_text_recent_miss():
    history = [{"date": "2026-05-01", "surprise_pct": -2.0}]
    assert dashboard.earnings_streak_text(0, history) == "missed last qtr (-2.0%)"


def test_earnings_streak_text_inline_no_surprise_data():
    history = [{"date": "2026-05-01", "surprise_pct": None}]
    assert dashboard.earnings_streak_text(0, history) == "last n/a"


def test_parse_earnings_surprise_history_none_or_empty():
    assert dashboard._parse_earnings_surprise_history(None, datetime.now(timezone.utc)) == ([], 0)


def test_parse_earnings_surprise_history_real_dataframe():
    pd = pytest.importorskip("pandas")
    now = datetime(2026, 7, 2, tzinfo=timezone.utc)
    idx = pd.to_datetime([
        "2026-06-01", "2026-03-01", "2025-12-01", "2025-09-01", "2026-09-01",  # future row excluded
    ]).tz_localize("UTC")
    df = pd.DataFrame({
        "EPS Estimate": [1.0, 1.0, 1.0, 1.0, 1.0],
        "Reported EPS": [1.1, 1.05, 0.9, 1.2, None],
        "Surprise(%)": [10.0, 5.0, -10.0, 20.0, None],
    }, index=idx)
    history, streak = dashboard._parse_earnings_surprise_history(df, now)
    # Future row (2026-09-01) excluded; most-recent-first among the remaining 4.
    assert [h["date"] for h in history] == ["2026-06-01", "2026-03-01", "2025-12-01", "2025-09-01"]
    assert history[0]["surprise_pct"] == 10.0
    # Beat streak stops at the first non-positive surprise (2025-12-01 = -10.0).
    assert streak == 2


def test_parse_earnings_surprise_history_nan_surprise_treated_as_unknown():
    pd = pytest.importorskip("pandas")
    now = datetime(2026, 7, 2, tzinfo=timezone.utc)
    idx = pd.to_datetime(["2026-06-01"]).tz_localize("UTC")
    df = pd.DataFrame({"Surprise(%)": [float("nan")]}, index=idx)
    history, streak = dashboard._parse_earnings_surprise_history(df, now)
    assert history == [{"date": "2026-06-01", "surprise_pct": None}]
    assert streak == 0  # unknown surprise doesn't extend a streak


def test_fetch_earnings_beat_streak_uses_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "CACHE_DIR", tmp_path)

    calls = {"n": 0}

    class _FakeTicker:
        def __init__(self, ticker):
            calls["n"] += 1

        @property
        def earnings_dates(self):
            return None  # exercised via _parse_earnings_surprise_history's None branch

    class _FakeYF:
        Ticker = _FakeTicker

    monkeypatch.setitem(__import__("sys").modules, "yfinance", _FakeYF())

    first = dashboard.fetch_earnings_beat_streak("ZZZZ")
    assert first["history"] == []
    assert first["beat_streak"] == 0
    assert calls["n"] == 1

    second = dashboard.fetch_earnings_beat_streak("ZZZZ")
    assert calls["n"] == 1  # cached — no second yfinance.Ticker() construction
    assert second["history"] == []
