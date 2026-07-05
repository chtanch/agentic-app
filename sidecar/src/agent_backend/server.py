"""Flask app — the frontend↔sidecar REST contract (Appendix A §A.2).

Phase 1 scope: health, curated models, and agent CRUD, all against SQLite, with
the uniform error envelope. Chat / turn loop (§A.3) and keys (§A.2.6) arrive in
later phases.
"""

from __future__ import annotations

import logging

from flask import Flask, jsonify, request
from pydantic import BaseModel, Field, ValidationError, field_validator

from . import db, models_catalog
from .errors import ApiError, bad_request, not_found
from .tool_names import TOOL_NAMES

log = logging.getLogger(__name__)


# --- request bodies ------------------------------------------------------

class AgentBody(BaseModel):
    """POST/PUT /agents body (Appendix A §A.2.2). Full replace on PUT."""

    name: str = Field(min_length=1)
    description: str = ""
    model_id: str
    tools: list[str] = Field(default_factory=list)
    workspace_folder: str | None = None

    @field_validator("tools")
    @classmethod
    def _known_tools(cls, v: list[str]) -> list[str]:
        unknown = [t for t in v if t not in TOOL_NAMES]
        if unknown:
            raise ValueError(f"unknown tool(s): {', '.join(unknown)}")
        return v


def create_app() -> Flask:
    app = Flask(__name__)

    # --- error handling: everything funnels to the A.2.7 envelope --------

    @app.errorhandler(ApiError)
    def _handle_api_error(err: ApiError):
        # bad_request/not_found are expected; log at INFO. Others are surfaced
        # runtime failures already logged with context at their source.
        log.info("api error: kind=%s message=%s", err.kind, err.message)
        return jsonify(err.envelope()), err.http_status

    @app.errorhandler(404)
    def _handle_404(_err):
        return jsonify(not_found("resource not found").envelope()), 404

    @app.errorhandler(405)
    def _handle_405(_err):
        return jsonify(
            bad_request("method not allowed").envelope()
        ), 405

    @app.errorhandler(Exception)
    def _handle_unexpected(err: Exception):
        # Never leak a stack trace to the client; it goes to the DEBUG log.
        log.exception("unhandled error")
        return jsonify(
            ApiError("bad_request", "internal error", http_status=500).envelope()
        ), 500

    # --- health (A.2.1) --------------------------------------------------

    @app.get("/health")
    def health():
        return jsonify({"ok": True})

    # --- models (A.2.8) --------------------------------------------------

    @app.get("/models")
    def models():
        return jsonify({"models": models_catalog.list_for_api()})

    # --- agents (A.2.2) --------------------------------------------------

    @app.get("/agents")
    def list_agents():
        return jsonify({"agents": db.list_agents()})

    @app.post("/agents")
    def create_agent():
        body = _parse_agent_body()
        model_config = _expand_model(body.model_id)
        agent = db.create_agent(
            name=body.name,
            description=body.description,
            model_config=model_config,
            tools=body.tools,
            workspace_folder=body.workspace_folder,
        )
        log.info("agent created: id=%s name=%r", agent["id"], agent["name"])
        return jsonify({"agent": agent}), 201

    @app.get("/agents/<int:agent_id>")
    def get_agent(agent_id: int):
        agent = db.get_agent(agent_id)
        if agent is None:
            raise not_found(f"no agent with id {agent_id}")
        return jsonify({"agent": agent})

    @app.put("/agents/<int:agent_id>")
    def update_agent(agent_id: int):
        body = _parse_agent_body()
        model_config = _expand_model(body.model_id)
        agent = db.update_agent(
            agent_id,
            name=body.name,
            description=body.description,
            model_config=model_config,
            tools=body.tools,
            workspace_folder=body.workspace_folder,
        )
        if agent is None:
            raise not_found(f"no agent with id {agent_id}")
        log.info("agent updated: id=%s", agent_id)
        return jsonify({"agent": agent})

    @app.delete("/agents/<int:agent_id>")
    def delete_agent(agent_id: int):
        if not db.delete_agent(agent_id):
            raise not_found(f"no agent with id {agent_id}")
        log.info("agent deleted: id=%s", agent_id)
        return jsonify({"deleted": True})

    return app


# --- helpers -------------------------------------------------------------

def _parse_agent_body() -> AgentBody:
    payload = request.get_json(silent=True)
    if payload is None:
        raise bad_request("request body must be JSON")
    try:
        return AgentBody.model_validate(payload)
    except ValidationError as e:
        raise bad_request("invalid agent fields", detail=e.errors(include_url=False).__repr__())


def _expand_model(model_id: str):
    model_config = models_catalog.expand(model_id)
    if model_config is None:
        raise bad_request(f"unknown model_id: {model_id!r}")
    return model_config
