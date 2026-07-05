"""Filesystem paths and network binding for the sidecar.

Everything the app persists lives under a single per-user data dir
(`%APPDATA%/agentic-app/` on Windows, PRD §5.5/§5.6/§6.1). The bind address is
127.0.0.1 with a hardcoded port (Appendix A §A.2, Decision #11): never 0.0.0.0.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "agentic-app"

# Sidecar bind. 127.0.0.1 ONLY (never 0.0.0.0) — the API holds keys and file
# tools (PRD §5.0). Port is fixed and shared verbatim by the Rust shell and the
# frontend (settled decision: no dynamic negotiation).
HOST = "127.0.0.1"
PORT = 8765


def data_dir() -> Path:
    """The per-user data directory, created on first access.

    Honors `AGENT_BACKEND_DATA_DIR` as an override (used by tests to redirect
    all state into a temp dir); otherwise `%APPDATA%/agentic-app/`, falling back
    to `~/agentic-app/` if APPDATA is unset.
    """
    override = os.environ.get("AGENT_BACKEND_DATA_DIR")
    if override:
        base = Path(override)
    else:
        appdata = os.environ.get("APPDATA")
        base = (Path(appdata) if appdata else Path.home()) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return data_dir() / "app.db"


def logs_dir() -> Path:
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_file() -> Path:
    """Optional TOML key file, read at startup (PRD §5.6). May not exist."""
    return data_dir() / "config.toml"
