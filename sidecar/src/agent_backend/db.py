"""SQLite persistence — the sole data layer (PRD §5.5, Decision #13).

Schema matches §5.5 verbatim except the `messages.role` enum, which is trimmed
to `user | assistant | tool` (settled decision (e): the system prompt is the
agent's `description`, never a stored row). Foreign keys are enforced per
connection so deleting an agent cascades to its messages.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from .config import db_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    description       TEXT NOT NULL,
    model_config_json TEXT NOT NULL,
    tools_json        TEXT NOT NULL,
    workspace_folder  TEXT,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY,
    agent_id        INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
    content         TEXT,
    message_json    TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(agent_id, id);

CREATE TABLE IF NOT EXISTS api_keys (
    provider TEXT PRIMARY KEY,
    key      TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """One connection per operation; commits on success, rolls back on error.

    Open/close per call keeps threading trivial for a single-user local app and
    guarantees `PRAGMA foreign_keys = ON` (off by default in sqlite3) on every
    connection so cascade deletes actually fire.
    """
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(_SCHEMA)


# --- serialization -------------------------------------------------------

def agent_row_to_api(row: sqlite3.Row) -> dict[str, Any]:
    """Full `Agent` shape for the REST API (Appendix A §A.2.2).

    Stored `model_config_json` is collapsed back to the bare `model_id` the
    frontend uses; `base_url`/`api_key_provider` never cross the seam.
    """
    model_config = json.loads(row["model_config_json"])
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "model_id": model_config["model_id"],
        "tools": json.loads(row["tools_json"]),
        "workspace_folder": row["workspace_folder"],
        "created_at": row["created_at"],
    }


def message_row_to_api(row: sqlite3.Row) -> dict[str, Any]:
    """Flat `Message` shape for the REST API (Appendix A §A.2.3).

    `tool_calls`/`tool_call_id` are *derived* from the verbatim `message_json`
    — the UI never sees `reasoning`/`reasoning_details` (server-side replay
    concern only, A.3.2). `tool_calls` is present on assistant rows that made
    calls; `tool_call_id` on `tool` rows.
    """
    raw = json.loads(row["message_json"]) if row["message_json"] else None
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "tool_calls": raw.get("tool_calls") if raw else None,
        "tool_call_id": raw.get("tool_call_id") if raw else None,
        "created_at": row["created_at"],
    }


# --- agent CRUD ----------------------------------------------------------

def list_agents() -> list[dict[str, Any]]:
    """AgentSummary list `{id, name}` (Appendix A §A.2.2)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name FROM agents ORDER BY id"
        ).fetchall()
    return [{"id": r["id"], "name": r["name"]} for r in rows]


def get_agent(agent_id: int) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM agents WHERE id = ?", (agent_id,)
        ).fetchone()
    return agent_row_to_api(row) if row else None


def create_agent(
    *,
    name: str,
    description: str,
    model_config: dict[str, Any],
    tools: list[str],
    workspace_folder: Optional[str],
) -> dict[str, Any]:
    created_at = _now()
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO agents
                (name, description, model_config_json, tools_json,
                 workspace_folder, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                description,
                json.dumps(model_config),
                json.dumps(tools),
                workspace_folder,
                created_at,
            ),
        )
        new_id = cur.lastrowid
        row = conn.execute(
            "SELECT * FROM agents WHERE id = ?", (new_id,)
        ).fetchone()
    return agent_row_to_api(row)


def update_agent(
    agent_id: int,
    *,
    name: str,
    description: str,
    model_config: dict[str, Any],
    tools: list[str],
    workspace_folder: Optional[str],
) -> Optional[dict[str, Any]]:
    """Full replace (Appendix A §A.2.2 PUT). Returns None if the id is unknown."""
    with get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE agents
               SET name = ?, description = ?, model_config_json = ?,
                   tools_json = ?, workspace_folder = ?
             WHERE id = ?
            """,
            (
                name,
                description,
                json.dumps(model_config),
                json.dumps(tools),
                workspace_folder,
                agent_id,
            ),
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT * FROM agents WHERE id = ?", (agent_id,)
        ).fetchone()
    return agent_row_to_api(row)


def delete_agent(agent_id: int) -> bool:
    """Delete an agent; cascades to messages (DB-enforced). True if a row went."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        return cur.rowcount > 0


def load_agent(agent_id: int) -> Optional[dict[str, Any]]:
    """Internal (server-side) agent view used by the turn loop.

    Unlike `get_agent` (the collapsed API shape), this exposes the full parsed
    `model_config` — `base_url`/`api_key_provider`/`model_id` — that the turn
    loop needs to reach OpenRouter. Never crosses the REST seam.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM agents WHERE id = ?", (agent_id,)
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "model_config": json.loads(row["model_config_json"]),
        "tools": json.loads(row["tools_json"]),
        "workspace_folder": row["workspace_folder"],
    }


# --- messages ------------------------------------------------------------

def add_message(
    agent_id: int,
    *,
    role: str,
    content: Optional[str],
    message_json: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Append a message row and return its API shape.

    `message_json` (the FULL raw provider message) is stored verbatim for
    assistant/tool rows so the turn loop can replay it unmodified (PRD §5.5);
    plain `user` rows pass `None` and rely on `content` alone.
    """
    created_at = _now()
    payload = json.dumps(message_json) if message_json is not None else None
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO messages (agent_id, role, content, message_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (agent_id, role, content, payload, created_at),
        )
        row = conn.execute(
            "SELECT * FROM messages WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return message_row_to_api(row)


def get_message_rows(agent_id: int) -> list[sqlite3.Row]:
    """Raw message rows (chronological). The turn loop needs `message_json`."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM messages WHERE agent_id = ? ORDER BY id",
            (agent_id,),
        ).fetchall()


def list_messages(agent_id: int) -> list[dict[str, Any]]:
    """API-shaped message list for `GET /agents/{id}/messages` (A.2.3)."""
    return [message_row_to_api(r) for r in get_message_rows(agent_id)]


def clear_messages(agent_id: int) -> None:
    """Delete an agent's messages, leaving the agent intact (A.2.5 / §5.4)."""
    with get_conn() as conn:
        conn.execute("DELETE FROM messages WHERE agent_id = ?", (agent_id,))


# --- api keys ------------------------------------------------------------

def get_api_key(provider: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT key FROM api_keys WHERE provider = ?", (provider,)
        ).fetchone()
    return row["key"] if row else None


def set_api_key(provider: str, key: str) -> None:
    """Upsert a plaintext provider key (PRD §5.5; plaintext disclosed in README)."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO api_keys (provider, key) VALUES (?, ?)
            ON CONFLICT(provider) DO UPDATE SET key = excluded.key
            """,
            (provider, key),
        )
