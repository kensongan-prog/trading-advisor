"""
test_classifier_fallback.py — LLM fallback path in classify_messages.

Why these tests exist: v2.0.6 found that RGLD's StockTwits source was reported
as "no source data" despite 30 messages being cached — the classifier hit a
single 429 on the primary model (`gemma-4-31b-it:free`) and gave up without
trying the fallback (`gpt-oss-120b:free`). The FALLBACK_MODEL constant was
defined but never referenced anywhere. These tests pin the contract: any
transient HTTP failure on the primary model triggers a retry on the fallback.
"""
import pytest
from unittest.mock import patch
import sentiment_cache as sc


class TestTransientErrorClassifier:
    """The _is_transient_error helper decides which errors get a retry."""

    @pytest.mark.parametrize("err", [
        "HTTP 429: Provider returned error rate limit",
        "HTTP 500: internal server error",
        "HTTP 502: bad gateway",
        "HTTP 503: gemma-4-31b-it:free is temporarily rate-limited",
        "HTTP 504: gateway timeout",
        "URLError: connection refused",
        "TimeoutError: connection timeout",
    ])
    def test_known_transient_returns_true(self, err):
        assert sc._is_transient_error(err) is True

    @pytest.mark.parametrize("err", [
        "HTTP 401: unauthorized",
        "HTTP 403: forbidden",
        "HTTP 404: not found",
        "JSON parse failed: Expecting value",
        "Expected list, got dict",
        "OPENROUTER_API_KEY missing",
    ])
    def test_non_transient_returns_false(self, err):
        # Permanent failures — the fallback would produce the same error
        assert sc._is_transient_error(err) is False

    def test_empty_or_none_returns_false(self):
        assert sc._is_transient_error("") is False
        assert sc._is_transient_error(None) is False


class TestFallbackTriggers:
    """classify_messages should retry the fallback model when primary fails
    transiently, and NOT retry when the failure is permanent."""

    def test_fallback_called_on_429(self):
        """Primary 429 → fallback gets called, returns success."""
        ok_result = ([{"sentiment": "bullish", "conviction": 1.0, "relevance": "primary"}],
                     None, "raw-fallback-response")
        err_result = (None, "HTTP 429: rate limited", "")
        with patch.object(sc, "_classify_one_attempt", side_effect=[err_result, ok_result]) as mock:
            out, err, _raw = sc.classify_messages(["msg"], "TEST", model="gemma")
            assert mock.call_count == 2
            # First call was primary model
            assert mock.call_args_list[0].args[2] == "gemma"
            # Second call was the fallback
            assert mock.call_args_list[1].args[2] == sc.FALLBACK_MODEL
            assert err is None
            assert out == ok_result[0]

    def test_no_fallback_on_permanent_error(self):
        """Primary 401 → no fallback, error returned directly."""
        err_result = (None, "HTTP 401: unauthorized — bad API key", "")
        with patch.object(sc, "_classify_one_attempt", side_effect=[err_result]) as mock:
            out, err, _raw = sc.classify_messages(["msg"], "TEST", model="gemma")
            assert mock.call_count == 1
            assert "HTTP 401" in err

    def test_no_fallback_when_primary_already_is_fallback(self):
        """Caller explicitly invoked the fallback model — don't loop."""
        err_result = (None, "HTTP 429: rate limited", "")
        with patch.object(sc, "_classify_one_attempt", side_effect=[err_result]) as mock:
            out, err, _raw = sc.classify_messages(["msg"], "TEST", model=sc.FALLBACK_MODEL)
            assert mock.call_count == 1
            assert "HTTP 429" in err

    def test_both_fail_reports_both_errors(self):
        """Primary AND fallback both 429 → error mentions both attempts."""
        err1 = (None, "HTTP 429: gemma rate limited", "")
        err2 = (None, "HTTP 503: gpt-oss provider down", "")
        with patch.object(sc, "_classify_one_attempt", side_effect=[err1, err2]) as mock:
            out, err, _raw = sc.classify_messages(["msg"], "TEST", model="gemma")
            assert mock.call_count == 2
            assert "primary=" in err
            assert "fallback=" in err
            assert "429" in err
            assert "503" in err

    def test_primary_success_skips_fallback(self):
        """Primary returns clean → no fallback call."""
        ok = ([{"sentiment": "neutral", "conviction": 0.5, "relevance": "primary"}], None, "raw")
        with patch.object(sc, "_classify_one_attempt", side_effect=[ok]) as mock:
            out, err, _raw = sc.classify_messages(["msg"], "TEST")
            assert mock.call_count == 1
            assert err is None

    def test_no_retry_on_parse_failure(self):
        """JSON parse error on primary → no fallback (would just fail again)."""
        err = (None, "JSON parse failed: Expecting value at line 1", "garbage")
        with patch.object(sc, "_classify_one_attempt", side_effect=[err]) as mock:
            out, e, _raw = sc.classify_messages(["msg"], "TEST", model="gemma")
            assert mock.call_count == 1
            assert "JSON parse failed" in e


class TestEmptyInput:
    """Empty message list short-circuits before any LLM call."""

    def test_empty_returns_immediately(self):
        with patch.object(sc, "_classify_one_attempt") as mock:
            out, err, _raw = sc.classify_messages([], "TEST")
            assert mock.call_count == 0
            assert out == []
            assert err is None
