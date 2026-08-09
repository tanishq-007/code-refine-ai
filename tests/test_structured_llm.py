import json

from agent import llm_client


def test_json_response_format_helper_uses_object_schema():
    params = llm_client.response_format_kwargs({"type": "json_object"})
    assert params == {"response_format": {"type": "json_object"}}

    params = llm_client.response_format_kwargs({"type": "json_schema", "json_schema": {"name": "Result", "schema": {"type": "object"}}})
    assert params["response_format"]["type"] == "json_schema"
    assert params["response_format"]["json_schema"]["name"] == "Result"


def test_parse_llm_json_strips_code_fences():
    raw = "```json\n{\"ok\": true}\n```"
    parsed = llm_client.parse_json_response(raw)
    assert parsed == {"ok": True}

    raw = "{\"ok\": true}"
    parsed = llm_client.parse_json_response(raw)
    assert parsed == {"ok": True}


def test_request_json_response_falls_back_when_response_format_is_unsupported(monkeypatch):
    class FakeResponse:
        class Choice:
            class Message:
                content = '{"ok": true}'

            message = Message()

        choices = [Choice()]

    calls = []

    def fake_create_chat_completion(**kwargs):
        calls.append(kwargs)
        if 'response_format' in kwargs:
            raise RuntimeError("unsupported parameter 'response_format'")
        return FakeResponse()

    monkeypatch.setattr(llm_client, 'create_chat_completion', fake_create_chat_completion)

    parsed = llm_client.request_json_response(
        model='test-model',
        max_tokens=32,
        messages=[{'role': 'user', 'content': 'ping'}],
    )

    assert parsed == {'ok': True}
    assert len(calls) == 2
    assert 'response_format' in calls[0]
    assert 'response_format' not in calls[1]
