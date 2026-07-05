"""Test fixtures: redirect all sidecar state into a temp dir per test."""

from __future__ import annotations

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Point the data dir at a fresh temp folder BEFORE the app touches the DB.
    monkeypatch.setenv("AGENT_BACKEND_DATA_DIR", str(tmp_path))

    from agent_backend import db
    from agent_backend.server import create_app

    db.init_db()
    app = create_app()
    app.testing = True
    with app.test_client() as c:
        yield c
