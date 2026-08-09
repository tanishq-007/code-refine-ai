"""
agent/llm_client.py

LLM client for the two call sites that need one (scoring, fix generation /
orchestration). Uses any OpenAI-compatible tool-calling endpoint; defaults
to Mistral's hosted models. Override LLM_BASE_URL/LLM_API_KEY/
LLM_*_MODEL to point at a different OpenAI-compatible provider (Groq,
Together, Fireworks, a local vLLM or Ollama server, ...) instead.

No key set -> callers fall back to their own offline path (heuristic
scoring; fix generation has none and raises).

All chat-completion calls should go through create_chat_completion() below
rather than calling client().chat.completions.create() directly -- it adds
a small client-side delay between requests (LLM_MIN_INTERVAL_SECONDS) to
avoid tripping per-minute rate limits, and raises the typed
RateLimitExhausted on a 429 so callers can stop cleanly instead of
retrying into a wall (a daily token-quota 429 won't clear on retry).
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional

BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.mistral.ai/v1")
# Override with LLM_SCORING_MODEL/LLM_FIX_MODEL/LLM_ORCH_MODEL to point at any
# other model/provider. codestral-latest is Mistral's code-specialized model,
# used for fix generation (diff writing) rather than the general chat model.
SCORING_MODEL = os.environ.get("LLM_SCORING_MODEL", "mistral-small-latest")
FIX_MODEL = os.environ.get("LLM_FIX_MODEL", "codestral-latest")
ORCH_MODEL = os.environ.get("LLM_ORCH_MODEL", "mistral-small-latest")

MIN_INTERVAL_SECONDS = float(os.environ.get("LLM_MIN_INTERVAL_SECONDS", "1.0"))

_last_call_ts = 0.0


class RateLimitExhausted(RuntimeError):
    """The provider returned 429. Callers should stop and surface this
    cleanly rather than retrying/self-correcting -- retrying a 429
    immediately just burns another request against the same limit."""


def api_key() -> Optional[str]:
    return (
        os.environ.get("LLM_API_KEY")
        or os.environ.get("MISTRAL_API_KEY")
        or os.environ.get("GROQ_API_KEY")
    )


def have_key() -> bool:
    return bool(api_key())


def client():
    import openai
    return openai.OpenAI(api_key=api_key(), base_url=BASE_URL)


def response_format_kwargs(schema: Optional[Dict] = None) -> Dict:
    """Return OpenAI-compatible response_format kwargs for JSON outputs."""
    if not schema:
        schema = {"type": "json_object"}
    if schema.get("type") == "json_schema":
        return {"response_format": schema}
    return {"response_format": {"type": "json_object"}}


def parse_json_response(raw: str) -> Dict:
    """Parse JSON from an LLM response, stripping fence blocks and empty wrappers."""
    text = (raw or "").strip()
    if not text:
        return {}
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if text.startswith("{") and text.endswith("}"):
            return json.loads(text[1:-1]) if text[1:-1].strip() else {}
        raise


def request_json_response(raw_out: Optional[List[str]] = None, **kwargs) -> Dict:
    """Request JSON output from the chat-completions endpoint and parse it.

    Some OpenAI-compatible endpoints reject the `response_format` parameter even
    though they still return JSON payloads. When that happens we retry once
    without it and use the same fence-stripping parser as the normal path.

    If `raw_out` is given, the model's raw response text is appended to it
    before parsing -- this lets a caller recover what the model actually said
    even when parsing raises (e.g. to feed the bad response back into a retry
    prompt), which the return value alone can't do once parse_json_response
    has thrown.
    """
    try:
        response = create_chat_completion(
            **kwargs,
            **response_format_kwargs({"type": "json_object"}),
        )
    except TypeError:
        response = create_chat_completion(**kwargs)
    except RateLimitExhausted:
        raise  # a 429 won't clear by retrying without response_format -- surface it
    except Exception:
        response = create_chat_completion(**kwargs)

    raw = (response.choices[0].message.content or "").strip()
    if raw_out is not None:
        raw_out.append(raw)
    return parse_json_response(raw)


def create_chat_completion(**kwargs):
    """client().chat.completions.create(**kwargs), but paced to avoid
    tripping per-minute rate limits, and with 429s converted to
    RateLimitExhausted instead of a raw provider exception."""
    global _last_call_ts
    import openai

    elapsed = time.monotonic() - _last_call_ts
    if elapsed < MIN_INTERVAL_SECONDS:
        time.sleep(MIN_INTERVAL_SECONDS - elapsed)

    try:
        return client().chat.completions.create(**kwargs)
    except openai.RateLimitError as e:
        raise RateLimitExhausted(str(e)) from e
    finally:
        _last_call_ts = time.monotonic()


def to_openai_tools(anthropic_tool_schemas: List[Dict]) -> List[Dict]:
    """mcp_server/tools.py's TOOL_SCHEMAS are Anthropic-style
    {name, description, input_schema}; convert to OpenAI-style
    {"type": "function", "function": {name, description, parameters}}."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in anthropic_tool_schemas
    ]
