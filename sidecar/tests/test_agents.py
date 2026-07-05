"""Phase 1: health, models, and agent CRUD against the A.2 contract."""

from __future__ import annotations

VALID_MODEL = "poolside/laguna-m.1:free"


def _make(client, **overrides):
    body = {
        "name": "Research Assistant",
        "description": "You help with research.",
        "model_id": VALID_MODEL,
        "tools": ["web_search", "calculator"],
        "workspace_folder": None,
    }
    body.update(overrides)
    return client.post("/agents", json=body)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


def test_models_returns_id_and_label_only(client):
    resp = client.get("/models")
    assert resp.status_code == 200
    models = resp.get_json()["models"]
    assert len(models) == 3
    for m in models:
        assert set(m.keys()) == {"id", "label"}
    assert any(m["id"] == VALID_MODEL for m in models)


def test_create_agent_returns_full_shape(client):
    resp = _make(client)
    assert resp.status_code == 201
    agent = resp.get_json()["agent"]
    assert agent["id"] > 0
    assert agent["name"] == "Research Assistant"
    assert agent["model_id"] == VALID_MODEL          # base_url/provider never leak
    assert agent["tools"] == ["web_search", "calculator"]
    assert agent["workspace_folder"] is None
    assert "created_at" in agent
    assert "model_config" not in agent


def test_create_rejects_unknown_model(client):
    resp = _make(client, model_id="not/a-real-model")
    assert resp.status_code == 400
    assert resp.get_json()["error"]["kind"] == "bad_request"


def test_create_rejects_unknown_tool(client):
    resp = _make(client, tools=["web_search", "bogus_tool"])
    assert resp.status_code == 400
    assert resp.get_json()["error"]["kind"] == "bad_request"


def test_create_rejects_non_json(client):
    resp = client.post("/agents", data="not json", content_type="text/plain")
    assert resp.status_code == 400
    assert resp.get_json()["error"]["kind"] == "bad_request"


def test_get_and_list_agents(client):
    created = _make(client).get_json()["agent"]

    got = client.get(f"/agents/{created['id']}")
    assert got.status_code == 200
    assert got.get_json()["agent"]["id"] == created["id"]

    listing = client.get("/agents").get_json()["agents"]
    assert listing == [{"id": created["id"], "name": "Research Assistant"}]


def test_get_missing_agent_is_404_envelope(client):
    resp = client.get("/agents/999")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["kind"] == "not_found"


def test_update_full_replace(client):
    created = _make(client).get_json()["agent"]
    resp = client.put(
        f"/agents/{created['id']}",
        json={
            "name": "Renamed",
            "description": "new prompt",
            "model_id": "poolside/laguna-xs.2:free",
            "tools": ["calculator"],
            "workspace_folder": "C:\\work",
        },
    )
    assert resp.status_code == 200
    agent = resp.get_json()["agent"]
    assert agent["name"] == "Renamed"
    assert agent["model_id"] == "poolside/laguna-xs.2:free"
    assert agent["tools"] == ["calculator"]
    assert agent["workspace_folder"] == "C:\\work"


def test_update_missing_agent_is_404(client):
    resp = client.put(f"/agents/999", json={
        "name": "x", "description": "", "model_id": VALID_MODEL,
        "tools": [], "workspace_folder": None,
    })
    assert resp.status_code == 404


def test_delete_agent(client):
    created = _make(client).get_json()["agent"]
    resp = client.delete(f"/agents/{created['id']}")
    assert resp.status_code == 200
    assert resp.get_json() == {"deleted": True}
    assert client.get(f"/agents/{created['id']}").status_code == 404


def test_delete_missing_agent_is_404(client):
    resp = client.delete("/agents/999")
    assert resp.status_code == 404


def test_delete_cascades_to_messages(client):
    """FK cascade must remove an agent's messages (PRAGMA foreign_keys = ON)."""
    from agent_backend import db

    created = _make(client).get_json()["agent"]
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (agent_id, role, content, created_at) "
            "VALUES (?, 'user', 'hi', '2026-01-01T00:00:00Z')",
            (created["id"],),
        )

    client.delete(f"/agents/{created['id']}")

    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE agent_id = ?",
            (created["id"],),
        ).fetchone()
    assert rows["n"] == 0
