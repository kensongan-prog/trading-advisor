"""No-tools, strict-schema contract for the shared OpenAI/Codex client."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import openai_codex_client as occ


class _Stream:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _Responses:
    def __init__(self, stream):
        self.stream = stream
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.stream


def _response(text, status="completed"):
    return SimpleNamespace(
        status=status,
        output=[SimpleNamespace(
            type="message",
            content=[SimpleNamespace(type="output_text", text=text)],
        )],
        usage=SimpleNamespace(input_tokens=108, output_tokens=56),
    )


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"items": {"type": "array", "items": {"type": "string"}}},
    "required": ["items"],
}


def test_direct_structured_call_has_no_tools_and_records_usage():
    stream = _Stream()
    responses = _Responses(stream)
    client = SimpleNamespace(responses=responses)
    with patch.object(occ, "_resolve_client", return_value=(client, occ.DEFAULT_MODEL)), \
         patch.object(occ, "_consume_stream", return_value=_response('{"items":["ok"]}')):
        parsed, err, _raw, meta = occ.classify_json(
            instructions="Return JSON",
            user_text="classify",
            schema=SCHEMA,
            schema_name="test_schema",
        )
    assert err is None
    assert parsed == {"items": ["ok"]}
    assert stream.closed is True
    assert "tools" not in responses.kwargs
    assert responses.kwargs["text"]["format"]["strict"] is True
    assert responses.kwargs["reasoning"]["effort"] == "low"
    assert responses.kwargs["store"] is False
    assert meta == {
        "provider": "openai-codex",
        "model": "gpt-5.6-luna",
        "reasoning": "low",
        "input_tokens": 108,
        "output_tokens": 56,
    }


def test_malformed_output_fails_closed():
    stream = _Stream()
    client = SimpleNamespace(responses=_Responses(stream))
    with patch.object(occ, "_resolve_client", return_value=(client, occ.DEFAULT_MODEL)), \
         patch.object(occ, "_consume_stream", return_value=_response("not json")):
        parsed, err, raw, _meta = occ.classify_json(
            instructions="Return JSON",
            user_text="classify",
            schema=SCHEMA,
            schema_name="test_schema",
        )
    assert parsed is None
    assert "JSON parse failed" in err
    assert raw == "not json"


def test_client_failure_is_reported_without_fallback():
    with patch.object(occ, "_resolve_client", side_effect=RuntimeError("OAuth unavailable")):
        parsed, err, raw, meta = occ.classify_json(
            instructions="Return JSON",
            user_text="classify",
            schema=SCHEMA,
            schema_name="test_schema",
        )
    assert parsed is None
    assert "OAuth unavailable" in err
    assert raw == ""
    assert meta["provider"] == "openai-codex"


def test_active_classifier_modules_do_not_reference_openrouter():
    root = Path(__file__).parents[1]
    for path in (
        root / ".claude/skills/sentiment-cache/sentiment_cache.py",
        root / ".claude/skills/us-news/news_glyph.py",
        root / ".claude/skills/sentiment-cache/openai_codex_client.py",
    ):
        assert "openrouter" not in path.read_text(encoding="utf-8").lower()
