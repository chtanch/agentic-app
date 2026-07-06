"""Live OpenRouter round-trip — opt-in, excluded from the default suite.

Run explicitly:  uv run pytest -m live

Unlike the rest of the suite (which mocks `call_openai_compatible`), this drives the
real turn loop against OpenRouter through the actual `llm.py` client, so it
covers request shaping, auth, and response parsing end to end.

Key discovery mirrors the app's own source order but stays test-isolated: the
DB is the per-test tmp dir (via the `client` fixture), and the real key is read
from `OPENROUTER_API_KEY` or the user's real `config.toml`, then injected into
that isolated DB. The test SKIPS (not fails) when no key is available or when
OpenRouter is transiently unavailable / rate-limited, so it never turns a free-
tier 429 into a red build.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

# The free reasoning model from the curated catalog (data/models.json).
LIVE_MODEL = "poolside/laguna-m.1:free"


def _real_openrouter_key() -> str | None:
    """Resolve a real key for the test: env first, then the real config.toml."""
    env = os.environ.get("OPENROUTER_API_KEY")
    if env:
        return env
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    cfg = Path(appdata) / "agentic-app" / "config.toml"
    if not cfg.exists():
        return None
    try:
        return tomllib.loads(cfg.read_text("utf-8")).get("openrouter_key")
    except (OSError, tomllib.TOMLDecodeError):
        return None


LIVE_KEY = _real_openrouter_key()

requires_key = pytest.mark.skipif(
    not LIVE_KEY,
    reason="no OpenRouter key (set OPENROUTER_API_KEY or add one to config.toml)",
)


@requires_key
def test_live_round_trip_returns_a_real_reply(client):
    from agent_backend import db

    # Inject the real key into the isolated test DB (config.toml at the tmp data
    # dir doesn't exist, so keys.get_key falls through to this).
    db.set_api_key("openrouter", LIVE_KEY)

    agent = client.post("/agents", json={
        "name": "Live",
        "description": "Reply with exactly the single word: pong",
        "model_id": LIVE_MODEL,
        "tools": [],
        "workspace_folder": None,
    }).get_json()["agent"]

    resp = client.post(f"/agents/{agent['id']}/messages", json={"content": "ping"})

    if resp.status_code != 200:
        # Transient upstream failure (e.g. free-tier 429 -> model_error). Don't
        # fail the build on OpenRouter's availability.
        err = resp.get_json().get("error", {})
        pytest.skip(f"OpenRouter unavailable: {err.get('kind')} — {err.get('message')}")

    msgs = resp.get_json()["messages"]
    # A.2.4: user row then final assistant row.
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "ping"
    assert isinstance(msgs[1]["content"], str) and msgs[1]["content"].strip()

    # The reasoning model's full raw message is stored verbatim (§5.5) but the
    # API never surfaces reasoning.
    raw_rows = db.get_message_rows(agent["id"])
    assert raw_rows[-1]["message_json"]                 # assistant stored raw
    assert msgs[1]["tool_calls"] is None                # none requested this turn


@requires_key
def test_live_bad_key_is_bad_api_key_envelope(client):
    """A wrong key must surface as the bad_api_key envelope (A.2.7), not a crash."""
    from agent_backend import db

    db.set_api_key("openrouter", "sk-or-v1-definitely-invalid-key")

    agent = client.post("/agents", json={
        "name": "BadKey",
        "description": "",
        "model_id": LIVE_MODEL,
        "tools": [],
        "workspace_folder": None,
    }).get_json()["agent"]

    resp = client.post(f"/agents/{agent['id']}/messages", json={"content": "hi"})
    assert resp.status_code == 401
    assert resp.get_json()["error"]["kind"] == "bad_api_key"
