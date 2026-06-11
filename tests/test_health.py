"""
test_health.py — data-health classification.

Pins the per-cache-file state classification (fresh / stale / error_transient
/ error_permanent / no_coverage / missing) and the transient-error detector.
The whole point of the data-health surface is to make silent degradation
visible — if the classifier itself silently miscategorizes, the surface lies.
"""
from datetime import datetime, timezone, timedelta
import pytest
import health


NOW = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)


def _ts(hours_ago):
    """Build an ISO timestamp for `hours_ago` hours before NOW."""
    return (NOW - timedelta(hours=hours_ago)).isoformat(timespec="seconds")


class TestTransientErrorClassifier:
    @pytest.mark.parametrize("err", [
        "HTTP 429: rate-limited",
        "HTTP 500 internal server error",
        "HTTP 502 bad gateway",
        "HTTP 503: gemma-4-31b-it:free is temporarily rate-limited upstream",
        "HTTP 504 timeout",
        "URLError: connection refused",
        "TimeoutError: read timeout",
        "rate limit exceeded",
        "gemma is temporarily unavailable",
    ])
    def test_transient_returns_true(self, err):
        assert health.is_transient_error(err) is True

    @pytest.mark.parametrize("err", [
        "HTTP 401 unauthorized",
        "HTTP 403 forbidden",
        "HTTP 404 not found",
        "JSON parse failed",
        "Expected list, got dict",
        "OPENROUTER_API_KEY missing",
    ])
    def test_permanent_returns_false(self, err):
        assert health.is_transient_error(err) is False

    def test_none_empty_returns_false(self):
        assert health.is_transient_error("") is False
        assert health.is_transient_error(None) is False
        assert health.is_transient_error(123) is False  # non-string


class TestClassifyFileState:
    def test_missing_payload(self):
        state, age, detail = health.classify_file_state(None, 24, "feed", now=NOW)
        assert state == health.STATE_MISSING
        assert age is None
        assert "no cache" in detail

    def test_fresh_with_data(self):
        payload = {"fetched_at": _ts(2), "feed": [{"item": 1}]}
        state, age, _ = health.classify_file_state(payload, 24, "feed", now=NOW)
        assert state == health.STATE_FRESH
        assert age == pytest.approx(2, abs=0.1)

    def test_stale_past_ttl(self):
        payload = {"fetched_at": _ts(30), "feed": [{"item": 1}]}
        state, age, _ = health.classify_file_state(payload, 24, "feed", now=NOW)
        assert state == health.STATE_STALE
        assert age == pytest.approx(30, abs=0.1)

    def test_transient_error_overrides_freshness(self):
        # Even a fresh cache with a transient error is "transient" — we want to refresh
        payload = {"fetched_at": _ts(1), "error": "HTTP 429: rate limited", "feed": []}
        state, _, detail = health.classify_file_state(payload, 24, "feed", now=NOW)
        assert state == health.STATE_ERR_TRANSIENT
        assert "429" in detail

    def test_permanent_error(self):
        payload = {"fetched_at": _ts(1), "error": "HTTP 401: unauthorized"}
        state, _, _ = health.classify_file_state(payload, 24, None, now=NOW)
        assert state == health.STATE_ERR_PERMANENT

    def test_no_coverage_explicit(self):
        # Fetcher signals "fetched OK, nothing exists"
        payload = {"fetched_at": _ts(1), "no_coverage": True, "reason": "skip-mapped"}
        state, _, detail = health.classify_file_state(payload, 24, None, now=NOW)
        assert state == health.STATE_NO_COVERAGE
        assert "skip-mapped" in detail

    def test_no_coverage_implicit_empty_data_field(self):
        # No explicit flag but the data field is empty — same outcome
        payload = {"fetched_at": _ts(1), "feed": []}
        state, _, _ = health.classify_file_state(payload, 24, "feed", now=NOW)
        assert state == health.STATE_NO_COVERAGE

    def test_no_data_field_check_when_field_is_none(self):
        # If caller doesn't specify a data field, we shouldn't try to read one
        payload = {"fetched_at": _ts(1)}
        state, _, _ = health.classify_file_state(payload, 24, None, now=NOW)
        assert state == health.STATE_FRESH

    def test_missing_timestamp_is_fresh(self):
        # No fetched_at field is suspicious but not actionable — treat as fresh
        payload = {"feed": [{"x": 1}]}
        state, age, _ = health.classify_file_state(payload, 24, "feed", now=NOW)
        assert state == health.STATE_FRESH
        assert age is None

    def test_ttl_boundary(self):
        # Exactly at TTL should be fresh (the comparison is >, not >=)
        payload = {"fetched_at": _ts(24), "feed": [{"x": 1}]}
        state, _, _ = health.classify_file_state(payload, 24, "feed", now=NOW)
        assert state == health.STATE_FRESH


class TestPayloadAgeKeys:
    """Different caches use different timestamp keys; the helper should
    handle all of them."""

    @pytest.mark.parametrize("ts_key", [
        "fetched_at", "_fetched_at", "scored_at",
        "_generated_at", "_last_full_pass_at",
    ])
    def test_handles_all_known_timestamp_keys(self, ts_key):
        payload = {ts_key: _ts(3), "feed": [{"x": 1}]}
        state, age, _ = health.classify_file_state(payload, 24, "feed", now=NOW)
        assert state == health.STATE_FRESH
        assert age == pytest.approx(3, abs=0.1)


class TestSentimentSourceClassifier:
    def test_all_sources_present(self):
        payload = {"sources": {
            "stocktwits": {"present": True},
            "reddit":     {"present": True},
            "hackernews": {"present": True},
        }}
        out = health.classify_sentiment_sources(payload)
        for src in ("stocktwits", "reddit", "hackernews"):
            assert out[src][0] == health.STATE_FRESH

    def test_rgld_actual_failure_mode(self):
        # The exact shape the operator hit on RGLD before the v2.0.6 fix
        payload = {"sources": {
            "stocktwits": {"present": False, "error": "HTTP 429: gemma is rate-limited"},
            "reddit":     {"present": False, "error": None},
            "hackernews": {"present": False, "error": None},
        }}
        out = health.classify_sentiment_sources(payload)
        assert out["stocktwits"][0] == health.STATE_ERR_TRANSIENT
        # Reddit and HN with `error: null` are legitimate no-coverage
        assert out["reddit"][0] == health.STATE_NO_COVERAGE
        assert out["hackernews"][0] == health.STATE_NO_COVERAGE

    def test_permanent_error_distinguished(self):
        payload = {"sources": {
            "stocktwits": {"present": False, "error": "HTTP 401: bad key"},
        }}
        out = health.classify_sentiment_sources(payload)
        assert out["stocktwits"][0] == health.STATE_ERR_PERMANENT

    def test_missing_composite(self):
        out = health.classify_sentiment_sources(None)
        for src in ("stocktwits", "reddit", "hackernews"):
            assert out[src][0] == health.STATE_MISSING


class TestSummarize:
    def test_empty_input(self):
        s = health.summarize([])
        assert s["total"] == 0
        assert s["healthy_pct"] == 100.0
        assert s["n_actionable"] == 0

    def test_mixed_states(self):
        records = [
            {"state": health.STATE_FRESH},
            {"state": health.STATE_FRESH},
            {"state": health.STATE_NO_COVERAGE},
            {"state": health.STATE_STALE},
            {"state": health.STATE_ERR_TRANSIENT},
            {"state": health.STATE_ERR_PERMANENT},
        ]
        s = health.summarize(records)
        assert s["total"] == 6
        # fresh + no_coverage are both "healthy" outcomes — 3/6
        assert s["healthy_pct"] == 50.0
        assert s["n_actionable"] == 3   # stale + transient + permanent
        assert s["n_transient"] == 1
        assert s["n_permanent"] == 1
        assert s["n_stale"] == 1

    def test_all_fresh_is_100(self):
        s = health.summarize([{"state": health.STATE_FRESH}] * 5)
        assert s["healthy_pct"] == 100.0
        assert s["n_actionable"] == 0


class TestStatePriority:
    def test_transient_higher_than_permanent(self):
        """A transient error is more actionable (a refresh fixes it) than a
        permanent error (which needs code/config work) — so it should sort
        higher for the operator's eye."""
        assert health.state_priority(health.STATE_ERR_TRANSIENT) > \
               health.state_priority(health.STATE_ERR_PERMANENT)

    def test_errors_higher_than_stale(self):
        assert health.state_priority(health.STATE_ERR_PERMANENT) > \
               health.state_priority(health.STATE_STALE)

    def test_fresh_is_lowest_priority(self):
        # We don't want to surface fresh items at the top of the alert list
        for s in (health.STATE_STALE, health.STATE_ERR_TRANSIENT,
                  health.STATE_ERR_PERMANENT, health.STATE_NO_COVERAGE,
                  health.STATE_MISSING):
            assert health.state_priority(health.STATE_FRESH) <= health.state_priority(s)
