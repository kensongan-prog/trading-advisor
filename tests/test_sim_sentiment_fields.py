"""
test_sim_sentiment_fields.py — the §4 sentiment plumbing into the Risk Simulator.

dashboard.sentiment_sim_fields() extracts the per-ticker contrarian flag +
conviction and decides staleness (>24h sentiment TTL / missing) so the sim can
degrade to 'not assessed' rather than asserting on old data. Pins that mapping.
"""
from datetime import datetime, timezone, timedelta
import dashboard


def _iso(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def test_fresh_flagged_read(monkeypatch):
    monkeypatch.setattr(dashboard, "load_sentiment", lambda t: {
        "composite": {"contrarian_flag": "FADE", "conviction": 0.82},
        "scored_at": _iso(2)})
    f = dashboard.sentiment_sim_fields("NVDA")
    assert f["sentiment_flag"] == "FADE"
    assert f["sentiment_conviction"] == 0.82
    assert f["sentiment_stale"] is False


def test_stale_beyond_ttl(monkeypatch):
    monkeypatch.setattr(dashboard, "load_sentiment", lambda t: {
        "composite": {"contrarian_flag": "BUY", "conviction": 0.9},
        "scored_at": _iso(48)})  # > 24h
    f = dashboard.sentiment_sim_fields("AUPH")
    assert f["sentiment_stale"] is True
    # flag/conviction still passed through; the sim ignores them when stale
    assert f["sentiment_flag"] == "BUY"


def test_missing_cache_is_stale(monkeypatch):
    monkeypatch.setattr(dashboard, "load_sentiment", lambda t: None)
    f = dashboard.sentiment_sim_fields("ZZZZ")
    assert f["sentiment_flag"] is None
    assert f["sentiment_stale"] is True


def test_present_but_undated_is_usable(monkeypatch):
    # A composite with no timestamp shouldn't be treated as stale.
    monkeypatch.setattr(dashboard, "load_sentiment", lambda t: {
        "composite": {"contrarian_flag": None, "conviction": 0.3}})
    f = dashboard.sentiment_sim_fields("KO")
    assert f["sentiment_stale"] is False
