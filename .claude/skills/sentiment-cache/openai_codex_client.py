"""Minimal structured-output client for Trading Advisor LLM classification.

This module deliberately reuses Hermes' authenticated ``openai-codex``
Responses client.  It does not read API keys, start an interactive agent, load
project rules, or expose tools to untrusted forum/news text.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


PROVIDER = "openai-codex"
DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_REASONING = "low"


def get_model() -> str:
    """Return the explicitly configured Codex model or the cheap default."""
    return os.environ.get("OPENAI_CODEX_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _hermes_agent_root() -> Path:
    configured = os.environ.get("HERMES_AGENT_ROOT", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".hermes" / "hermes-agent"


def _resolve_client(model: str):
    root = _hermes_agent_root()
    if not (root / "agent" / "auxiliary_client.py").is_file():
        raise RuntimeError(f"Hermes OpenAI/Codex runtime unavailable at {root}")
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    try:
        from agent.auxiliary_client import resolve_provider_client
    except Exception as exc:
        raise RuntimeError(
            "Hermes OpenAI/Codex client import failed; run with the managed "
            f"Hermes Python runtime ({type(exc).__name__}: {exc})"
        ) from exc

    client, resolved_model = resolve_provider_client(
        PROVIDER,
        model=model,
        raw_codex=True,
        api_mode="codex_responses",
    )
    if client is None:
        raise RuntimeError(
            "OpenAI/Codex OAuth unavailable; authenticate the existing Hermes/Codex route"
        )
    return client, resolved_model or model


def _consume_stream(stream, model: str):
    from agent.codex_runtime import _consume_codex_event_stream

    return _consume_codex_event_stream(stream, model=model)


def _response_text(response) -> str:
    parts = []
    for item in getattr(response, "output", None) or []:
        item_type = getattr(item, "type", None)
        if item_type is None and isinstance(item, dict):
            item_type = item.get("type")
        if item_type != "message":
            continue
        content = getattr(item, "content", None)
        if content is None and isinstance(item, dict):
            content = item.get("content")
        for part in content or []:
            part_type = getattr(part, "type", None)
            if part_type is None and isinstance(part, dict):
                part_type = part.get("type")
            if part_type not in ("output_text", "text"):
                continue
            text = getattr(part, "text", None)
            if text is None and isinstance(part, dict):
                text = part.get("text")
            if text:
                parts.append(str(text))
    return "".join(parts).strip()


def classify_json(
    *,
    instructions: str,
    user_text: str,
    schema: dict,
    schema_name: str,
    model: str | None = None,
    timeout: int = 60,
):
    """Return ``(parsed_object, error, raw_text, metadata)``.

    The request has no tool definitions and uses strict JSON Schema output.
    Provider errors and malformed responses fail closed; callers retain their
    existing cache/stale result.
    """
    selected_model = model or get_model()
    metadata = {
        "provider": PROVIDER,
        "model": selected_model,
        "reasoning": DEFAULT_REASONING,
    }
    try:
        client, resolved_model = _resolve_client(selected_model)
        metadata["model"] = resolved_model
        stream = client.responses.create(
            model=resolved_model,
            instructions=instructions,
            input=[{"role": "user", "content": user_text}],
            reasoning={"effort": DEFAULT_REASONING, "summary": "auto"},
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
            store=False,
            stream=True,
            timeout=timeout,
        )
        try:
            response = _consume_stream(stream, resolved_model)
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
        raw = _response_text(response)
        usage = getattr(response, "usage", None)
        metadata["input_tokens"] = getattr(usage, "input_tokens", None)
        metadata["output_tokens"] = getattr(usage, "output_tokens", None)
        if getattr(response, "status", "completed") != "completed":
            return None, f"OpenAI/Codex response status: {response.status}", raw, metadata
        try:
            parsed = json.loads(raw)
        except Exception as exc:
            return None, f"JSON parse failed: {exc}", raw, metadata
        if not isinstance(parsed, dict):
            return None, f"Expected object, got {type(parsed).__name__}", raw, metadata
        return parsed, None, raw, metadata
    except Exception as exc:
        detail = str(exc).replace("\n", " ")[:300]
        return None, f"OpenAI/Codex request failed: {type(exc).__name__}: {detail}", "", metadata
