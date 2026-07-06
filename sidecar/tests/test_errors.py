"""Phase 6 hardening: the four failure modes each surface as a clear,
non-crashing signal (PRD §6, §8.6).

Three of the four are *turn-aborting* and map to the A.2.7 error envelope:
  - offline      — provider unreachable (network/DNS/timeout)
  - bad_api_key  — key missing or rejected (401/403)
  - model_error  — any other provider failure (5xx, non-JSON, no completion,
                   or the runaway max-iterations guard)
The fourth — a *tool execution failure* — deliberately does NOT abort the turn
or produce an envelope (it comes back to the model as a string); that path is
covered in test_tools.py.

This module pins (a) the mapping inside `llm.call_openai_compatible` and
(b) that each envelope kind propagates through the message endpoint with the
right HTTP status.
"""

from __future__ import annotations

import pytest
import requests

from agent_backend import llm
from agent_backend.errors import ApiError

VALID_MODEL = "poolside/laguna-m.1:free"


class _FakeResp:
    """Minimal stand-in for a `requests.Response` (status/json/text only)."""

    def __init__(self, status_code, json_data=None, text="", raise_json=False):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("not json")
        return self._json


def _call(**over):
    kwargs = dict(
        base_url="https://provider.example/api/v1",
        model="m",
        api_key="k",
        system="",
        messages=[{"role": "user", "content": "hi"}],
    )
    kwargs.update(over)
    return llm.call_openai_compatible(**kwargs)


# --- llm.py mapping: the three turn-aborting kinds -----------------------

def test_unreachable_provider_is_offline(monkeypatch):
    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("no route to host")

    monkeypatch.setattr(llm.requests, "post", boom)
    with pytest.raises(ApiError) as ei:
        _call()
    assert ei.value.kind == "offline"
    assert ei.value.http_status == 503


def test_timeout_is_offline(monkeypatch):
    def boom(*a, **k):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(llm.requests, "post", boom)
    with pytest.raises(ApiError) as ei:
        _call()
    assert ei.value.kind == "offline"


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_key_is_bad_api_key(monkeypatch, status):
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: _FakeResp(status, text="unauthorized"))
    with pytest.raises(ApiError) as ei:
        _call()
    assert ei.value.kind == "bad_api_key"
    assert ei.value.http_status == 401


def test_server_error_is_model_error(monkeypatch):
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: _FakeResp(500, text="boom"))
    with pytest.raises(ApiError) as ei:
        _call()
    assert ei.value.kind == "model_error"
    assert ei.value.http_status == 502


def test_non_json_body_is_model_error(monkeypatch):
    monkeypatch.setattr(
        llm.requests, "post", lambda *a, **k: _FakeResp(200, raise_json=True, text="<html>gateway</html>")
    )
    with pytest.raises(ApiError) as ei:
        _call()
    assert ei.value.kind == "model_error"


def test_200_without_choices_is_model_error(monkeypatch):
    # OpenRouter can return HTTP 200 carrying an `error` object and no choices.
    monkeypatch.setattr(
        llm.requests,
        "post",
        lambda *a, **k: _FakeResp(200, json_data={"error": {"message": "rate limited"}}),
    )
    with pytest.raises(ApiError) as ei:
        _call()
    assert ei.value.kind == "model_error"
    assert ei.value.detail == "rate limited"


def test_api_key_never_appears_in_error(monkeypatch):
    """A rejected-key failure must not echo the secret anywhere on the error."""
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: _FakeResp(401, text="denied"))
    with pytest.raises(ApiError) as ei:
        _call(api_key="sk-super-secret")
    blob = f"{ei.value.kind} {ei.value.message} {ei.value.detail}"
    assert "sk-super-secret" not in blob


# --- propagation through the endpoint: kind -> HTTP status ---------------

def _make_agent(client):
    body = {
        "name": "ErrBot",
        "description": "",
        "model_id": VALID_MODEL,
        "tools": [],
        "workspace_folder": None,
    }
    return client.post("/agents", json=body).get_json()["agent"]


@pytest.mark.parametrize(
    "kind,status",
    [("offline", 503), ("bad_api_key", 401), ("model_error", 502)],
)
def test_turn_aborting_kinds_propagate_to_envelope(client, monkeypatch, kind, status):
    agent = _make_agent(client)
    client.put("/keys", json={"openrouter": "sk-test"})

    def raise_kind(**kwargs):
        raise ApiError(kind, f"{kind} happened")

    monkeypatch.setattr(llm, "call_openai_compatible", raise_kind)

    resp = client.post(f"/agents/{agent['id']}/messages", json={"content": "hi"})
    assert resp.status_code == status
    assert resp.get_json()["error"]["kind"] == kind


def test_max_iterations_guard_is_model_error(client, monkeypatch):
    """A model that calls a tool forever is stopped by the guard as model_error."""
    agent = client.post(
        "/agents",
        json={
            "name": "LoopBot",
            "description": "",
            "model_id": VALID_MODEL,
            "tools": ["calculator"],
            "workspace_folder": None,
        },
    ).get_json()["agent"]
    client.put("/keys", json={"openrouter": "sk-test"})

    # Always ask for another calculator call -> never terminates on its own.
    def always_calls(**kwargs):
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "calculator", "arguments": '{"expression": "1+1"}'},
                }
            ],
        }

    monkeypatch.setattr(llm, "call_openai_compatible", always_calls)

    resp = client.post(f"/agents/{agent['id']}/messages", json={"content": "loop"})
    assert resp.status_code == 502
    assert resp.get_json()["error"]["kind"] == "model_error"
