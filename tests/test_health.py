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
        assert s["n_actionable_server"] == 0
        assert s["n_actionable_agent"] == 0

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
        # Records have no source → REFRESH_VIA unknown → neither bucket
        assert s["n_actionable_server"] == 0
        assert s["n_actionable_agent"] == 0

    def test_all_fresh_is_100(self):
        s = health.summarize([{"state": health.STATE_FRESH}] * 5)
        assert s["healthy_pct"] == 100.0
        assert s["n_actionable"] == 0

    def test_server_vs_agent_split(self):
        records = [
            {"state": health.STATE_STALE,         "source": "us_news"},           # server (--refresh-news)
            {"state": health.STATE_ERR_TRANSIENT,  "source": "polymarket"},        # server
            {"state": health.STATE_MISSING,        "source": "screener"},          # server
            {"state": health.STATE_STALE,          "source": "crypto_unlocks"},    # agent-only
            {"state": health.STATE_ERR_PERMANENT,  "source": "us_news"},           # permanent: excluded from split
            {"state": health.STATE_NO_COVERAGE,    "source": "us_news"},           # no-coverage: excluded
            {"state": health.STATE_STALE,          "source": "sentiment.reddit"},  # server (via sentiment parent)
        ]
        s = health.summarize(records)
        assert s["n_actionable_server"] == 4   # us_news stale + polymarket + screener + sentiment.reddit
        assert s["n_actionable_agent"] == 1    # crypto_unlocks


class TestRefreshVia:
    def test_every_ttl_source_has_refresh_via_entry(self):
        """REFRESH_VIA must cover every key in TTL_HOURS so --refresh-stale
        can route all flagged sources."""
        missing = set(health.TTL_HOURS) - set(health.REFRESH_VIA)
        assert missing == set(), f"TTL_HOURS keys missing from REFRESH_VIA: {missing}"

    def test_no_extra_refresh_via_keys(self):
        """REFRESH_VIA must not reference sources that don't exist in TTL_HOURS
        (orphaned entries cause silent mis-routing)."""
        extras = set(health.REFRESH_VIA) - set(health.TTL_HOURS)
        assert extras == set(), f"REFRESH_VIA keys not in TTL_HOURS: {extras}"

    @pytest.mark.parametrize("source", [
        "us_news", "finnhub_news", "klse_news", "crypto_news",
        "reddit_sentiment", "stocktwits_sentiment", "hn_sentiment", "sentiment",
        "polymarket", "sector_rotation", "screener",
    ])
    def test_flag_sources_return_flag_tuple(self, source):
        via = health.source_refresh_via(source)
        assert via is not None
        assert via[0] == "flag"
        assert via[1].startswith("--")

    @pytest.mark.parametrize("source", ["klse_announcements", "klse_fundamentals"])
    def test_cli_sources_return_cli_tuple(self, source):
        via = health.source_refresh_via(source)
        assert via is not None
        assert via[0] == "cli"
        assert via[1].endswith(".py")

    def test_crypto_unlocks_is_agent_only(self):
        via = health.source_refresh_via("crypto_unlocks")
        assert via == ("agent",)

    def test_sentiment_sub_sources_resolve_to_flag(self):
        for sub in ("sentiment.stocktwits", "sentiment.reddit", "sentiment.hackernews"):
            via = health.source_refresh_via(sub)
            assert via == ("flag", "--refresh-sentiment"), f"wrong via for {sub}: {via}"

    def test_unknown_source_returns_none(self):
        assert health.source_refresh_via("nonexistent_source") is None
        assert health.source_refresh_via("") is None

    def test_every_flag_is_a_real_dashboard_argparse_flag(self):
        """dashboard.py --refresh-stale derives the argparse attribute from each
        REFRESH_VIA flag name (no second mapping table). If a flag in REFRESH_VIA
        doesn't exist as a dashboard.py argument, --refresh-stale would silently
        fail to refresh that source. Pin the flag↔argparse contract statically."""
        from pathlib import Path
        import re
        dash = (Path(__file__).resolve().parent.parent
                / ".claude" / "skills" / "dashboard" / "dashboard.py").read_text()
        declared = set(re.findall(r'ap\.add_argument\("(--[a-z-]+)"', dash))
        flags = {via[1] for via in health.REFRESH_VIA.values() if via[0] == "flag"}
        missing = flags - declared
        assert missing == set(), f"REFRESH_VIA flags not declared in dashboard.py argparse: {missing}"


class TestValidateRefreshSource:
    def test_valid_flag_source_accepted(self):
        ok, via = health.validate_refresh_source("us_news")
        assert ok is True
        assert via == ("flag", "--refresh-news")

    def test_valid_cli_source_accepted(self):
        ok, via = health.validate_refresh_source("klse_announcements")
        assert ok is True
        assert via[0] == "cli"

    def test_agent_only_rejected(self):
        ok, msg = health.validate_refresh_source("crypto_unlocks")
        assert ok is False
        assert "agent" in msg.lower()

    def test_unknown_source_rejected(self):
        ok, msg = health.validate_refresh_source("totally_made_up")
        assert ok is False
        assert "unknown" in msg.lower()


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
