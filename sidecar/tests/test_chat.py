"""Phase 2: keys (A.2.6) + the chat turn loop (A.2.3–A.2.5, A.3.2).

The OpenRouter round-trip is mocked (`agent_backend.llm.call_openai_compatible`) so
these stay offline and deterministic; the real provider is exercised by the
manual integration smoke, not the unit suite.
"""

from __future__ import annotations

import pytest

VALID_MODEL = "poolside/laguna-m.1:free"


def _make_agent(client, **overrides):
    body = {
        "name": "Chatbot",
        "description": "You are terse.",
        "model_id": VALID_MODEL,
        "tools": [],
        "workspace_folder": None,
    }
    body.update(overrides)
    return client.post("/agents", json=body).get_json()["agent"]


def _stub_llm(monkeypatch, message):
    """Make call_openai_compatible return `message` verbatim (no network)."""
    from agent_backend import llm

    def fake(**kwargs):
        return message

    monkeypatch.setattr(llm, "call_openai_compatible", fake)


# --- keys (A.2.6) --------------------------------------------------------

def test_keys_start_unset(client):
    assert client.get("/keys").get_json() == {"openrouter": "unset", "tavily": "unset"}


def test_put_keys_sets_presence_without_returning_value(client):
    resp = client.put("/keys", json={"openrouter": "sk-secret"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["openrouter"] == "set"
    assert body["tavily"] == "unset"
    # The value is never echoed back anywhere.
    assert "sk-secret" not in resp.get_data(as_text=True)
    assert "sk-secret" not in client.get("/keys").get_data(as_text=True)


# --- send a message (A.2.4 / A.3.2) --------------------------------------

def test_send_message_happy_path(client, monkeypatch):
    agent = _make_agent(client)
    client.put("/keys", json={"openrouter": "sk-test"})
    _stub_llm(monkeypatch, {"role": "assistant", "content": "Hi."})

    resp = client.post(f"/agents/{agent['id']}/messages", json={"content": "hello"})
    assert resp.status_code == 200
    msgs = resp.get_json()["messages"]

    # A.2.4: new rows in order — user msg, then final assistant msg.
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "hello"
    assert msgs[1]["content"] == "Hi."
    assert all(m["id"] > 0 and m["created_at"] for m in msgs)


def test_send_message_persists_and_history_reads_back(client, monkeypatch):
    agent = _make_agent(client)
    client.put("/keys", json={"openrouter": "sk-test"})
    _stub_llm(monkeypatch, {"role": "assistant", "content": "Hi."})

    client.post(f"/agents/{agent['id']}/messages", json={"content": "hello"})
    history = client.get(f"/agents/{agent['id']}/messages").get_json()["messages"]
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["tool_calls"] is None
    assert history[0]["tool_call_id"] is None


def test_send_without_key_is_bad_api_key_envelope(client, monkeypatch):
    agent = _make_agent(client)
    # no key configured
    resp = client.post(f"/agents/{agent['id']}/messages", json={"content": "hello"})
    assert resp.status_code == 401
    assert resp.get_json()["error"]["kind"] == "bad_api_key"


def test_send_message_empty_content_is_400(client):
    agent = _make_agent(client)
    resp = client.post(f"/agents/{agent['id']}/messages", json={"content": ""})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["kind"] == "bad_request"


def test_send_message_missing_agent_is_404(client):
    resp = client.post("/agents/999/messages", json={"content": "hello"})
    assert resp.status_code == 404
    assert resp.get_json()["error"]["kind"] == "not_found"


def test_reasoning_details_stored_but_not_exposed(client, monkeypatch):
    """message_json is stored verbatim; the API never surfaces reasoning."""
    from agent_backend import db

    agent = _make_agent(client)
    client.put("/keys", json={"openrouter": "sk-test"})
    _stub_llm(monkeypatch, {
        "role": "assistant",
        "content": "42",
        "reasoning_details": [{"type": "reasoning.text", "text": "secret chain"}],
    })

    resp = client.post(f"/agents/{agent['id']}/messages", json={"content": "q"})
    # Not leaked across the REST seam...
    assert "reasoning_details" not in resp.get_data(as_text=True)
    assert "secret chain" not in resp.get_data(as_text=True)
    # ...but stored verbatim for replay (§5.5).
    rows = db.get_message_rows(agent["id"])
    assert any("secret chain" in (r["message_json"] or "") for r in rows)


# --- clear conversation (A.2.5) ------------------------------------------

def test_clear_conversation(client, monkeypatch):
    agent = _make_agent(client)
    client.put("/keys", json={"openrouter": "sk-test"})
    _stub_llm(monkeypatch, {"role": "assistant", "content": "Hi."})
    client.post(f"/agents/{agent['id']}/messages", json={"content": "hello"})

    resp = client.delete(f"/agents/{agent['id']}/messages")
    assert resp.status_code == 200
    assert resp.get_json() == {"cleared": True}
    assert client.get(f"/agents/{agent['id']}/messages").get_json()["messages"] == []


def test_cors_header_echoed_for_local_origin(client):
    resp = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert resp.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"
