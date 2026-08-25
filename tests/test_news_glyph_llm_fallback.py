"""OpenAI/Codex structured-output contract for news-glyph scoring."""

from unittest.mock import patch

import news_glyph as ng


def test_openai_codex_luna_is_news_provider():
    assert ng.LLM_PROVIDER == "openai-codex"
    assert ng.LLM_DEFAULT_MODEL == "gpt-5.6-luna"


def test_news_batch_uses_shared_structured_client():
    payload = ({"items": [{"relevance": "primary", "score": 0.4}]}, None, "raw", {})
    with patch.object(ng, "classify_json", return_value=payload) as mocked:
        out, err = ng._llm_score_batch(
            "AUPH", ["AUPH reports positive trial data"], asset_class="us"
        )
    assert err is None
    assert out == [{"relevance": "primary", "score": 0.4}]
    assert mocked.call_args.kwargs["schema"] == ng.NEWS_SCORE_SCHEMA


def test_news_provider_failure_does_not_retry_or_replace_cache():
    items = [{"headline": "AUPH reports positive trial data"}]
    with patch.object(
        ng,
        "_llm_score_batch",
        return_value=(None, "OpenAI/Codex request failed: HTTP 429"),
    ) as mocked:
        _cached, fetched, err = ng.llm_score_items_for_ticker("AUPH", items)
    assert mocked.call_count == 1
    assert fetched == 0
    assert "429" in err


def test_news_cache_records_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(ng, "LLM_SCORE_CACHE", tmp_path)
    items = [{"headline": "AUPH reports positive trial data"}]
    with patch.object(
        ng,
        "_llm_score_batch",
        return_value=([{"relevance": "primary", "score": 0.4}], None),
    ):
        _cached, fetched, err = ng.llm_score_items_for_ticker("AUPH", items)
    assert err is None
    assert fetched == 1
    saved = ng._llm_cache_load("AUPH")
    assert next(iter(saved.values()))["provider"] == "openai-codex"
