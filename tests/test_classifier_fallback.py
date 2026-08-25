"""OpenAI/Codex provider and parser contract for retail sentiment."""

from unittest.mock import patch

import sentiment_cache as sc


def _payload(items):
    return {"items": items}, None, '{"items":[]}', {
        "provider": "openai-codex",
        "model": sc.DEFAULT_MODEL,
    }


class TestParserSafety:
    def test_structured_items_are_normalized(self):
        result = [{"sentiment": "bullish", "conviction": 0.8, "relevance": "primary"}]
        with patch.object(sc, "classify_json", return_value=_payload(result)) as mocked:
            out, err, _raw = sc._classify_one_attempt(
                ["bull case"], "TEST", sc.DEFAULT_MODEL, 1, None
            )
        assert err is None
        assert out == result
        kwargs = mocked.call_args.kwargs
        assert kwargs["schema"] == sc.SENTIMENT_SCHEMA
        assert kwargs["model"] == sc.DEFAULT_MODEL

    def test_non_list_payload_is_reported_not_coerced(self):
        payload = ({"items": "not a list"}, None, "raw", {})
        with patch.object(sc, "classify_json", return_value=payload):
            out, err, raw = sc._classify_one_attempt(
                ["hedged case"], "TEST", sc.DEFAULT_MODEL, 1, None
            )
        assert out is None
        assert "Expected items list" in err
        assert raw == "raw"


class TestProviderSelection:
    def test_openai_codex_luna_is_default(self):
        assert sc.LLM_PROVIDER == "openai-codex"
        assert sc.DEFAULT_MODEL == "gpt-5.6-luna"

    def test_provider_error_is_not_rerouted(self):
        failure = (None, "OpenAI/Codex request failed: HTTP 429", "", {})
        with patch.object(sc, "classify_json", return_value=failure) as mocked:
            out, err, _raw = sc.classify_messages(["msg"], "TEST")
        assert mocked.call_count == 1
        assert out is None
        assert "429" in err


class TestEmptyInput:
    def test_empty_returns_immediately(self):
        with patch.object(sc, "_classify_one_attempt") as mocked:
            out, err, _raw = sc.classify_messages([], "TEST")
        assert mocked.call_count == 0
        assert out == []
        assert err is None


class TestClassifierInputCache:
    def test_fingerprint_ignores_fetch_timestamp_but_tracks_message_changes(self):
        raw = {
            "ticker": "TEST",
            "asset_class": "us_equity",
            "fetched_at": "2026-08-25T00:00:00Z",
            "messages": [{"body": "bull case", "likes": 2, "reshares": 0}],
        }
        fp1 = sc._classification_input_fingerprint(
            "TEST", sc.DEFAULT_MODEL, "us_equity", raw, None, None, None
        )
        raw["fetched_at"] = "2026-08-25T12:00:00Z"
        fp2 = sc._classification_input_fingerprint(
            "TEST", sc.DEFAULT_MODEL, "us_equity", raw, None, None, None
        )
        raw["messages"][0]["body"] = "bear case"
        fp3 = sc._classification_input_fingerprint(
            "TEST", sc.DEFAULT_MODEL, "us_equity", raw, None, None, None
        )
        assert fp1 == fp2
        assert fp2 != fp3

    def test_unchanged_codex_input_reuses_cache_without_llm_call(self):
        raw = {
            "ticker": "TEST",
            "asset_class": "us_equity",
            "messages": [{"body": "bull case", "likes": 2, "reshares": 0}],
        }
        fingerprint = sc._classification_input_fingerprint(
            "TEST", sc.DEFAULT_MODEL, "us_equity", raw, None, None, None
        )
        cached = {
            "ticker": "TEST",
            "provider": "openai-codex",
            "model": sc.DEFAULT_MODEL,
            "input_fingerprint": fingerprint,
            "sources": {
                "stocktwits": {"present": True},
                "reddit": {"present": False, "error": None},
                "hackernews": {"present": False, "error": None},
                "klse": {"present": False, "error": None},
            },
            "composite": {"label": "BULL"},
        }
        with patch.object(sc, "load_stocktwits", return_value=raw), \
             patch.object(sc, "load_reddit", return_value=None), \
             patch.object(sc, "load_hackernews", return_value=None), \
             patch.object(sc, "load_klse_comments", return_value=None), \
             patch.object(sc, "load_cache", return_value=cached), \
             patch.object(sc, "process_stocktwits") as scorer:
            result = sc.score_ticker("TEST", verbose=False)
        assert result is cached
        scorer.assert_not_called()

    def test_provider_failure_cache_is_never_reused(self):
        cached = {
            "provider": "openai-codex",
            "model": sc.DEFAULT_MODEL,
            "input_fingerprint": "abc",
            "sources": {"stocktwits": {"present": False, "error": "HTTP 429"}},
            "composite": {},
        }
        assert sc._reusable_cache(cached, sc.DEFAULT_MODEL, "abc") is False

    def test_prefingerprint_cache_adopts_only_when_raw_inputs_are_older(self):
        cached = {
            "provider": "openai-codex",
            "model": sc.DEFAULT_MODEL,
            "scored_at": "2026-08-25T12:00:00Z",
            "sources": {"stocktwits": {"present": True}},
            "composite": {},
        }
        older = {"fetched_at": "2026-08-25T11:59:00Z"}
        newer = {"fetched_at": "2026-08-25T12:01:00Z"}
        assert sc._can_adopt_fingerprint(cached, sc.DEFAULT_MODEL, (older,)) is True
        assert sc._can_adopt_fingerprint(cached, sc.DEFAULT_MODEL, (newer,)) is False
