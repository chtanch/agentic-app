"""API key resolution (PRD §5.6, settled decision (a)).

Two independent sources, **config file wins**:
  1. `%APPDATA%/agentic-app/config.toml` — flat keys `openrouter_key` /
     `tavily_key` (a self-contained demo path).
  2. the `api_keys` table — written by the settings UI via `PUT /keys`.

There is deliberately NO environment-variable source (settled decision (a)),
despite the appendices' "file/env" wording. Keys are NEVER logged and NEVER
returned by `GET /keys` (presence only, A.2.6).
"""

from __future__ import annotations

import logging
import tomllib
from typing import Optional

from . import db
from .config import config_file

log = logging.getLogger(__name__)

PROVIDERS = ("openrouter", "tavily")

# config.toml uses flat, provider-suffixed keys; map them to provider names.
_FILE_KEY = {"openrouter": "openrouter_key", "tavily": "tavily_key"}


def _load_config() -> dict:
    """Read config.toml fresh (may not exist). Failures degrade to {}.

    Read per-call rather than cached so a dropped-in file takes effect without
    a restart; the file is tiny and access is local.
    """
    path = config_file()
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        # Never log the file's contents — only that parsing failed.
        log.warning("could not read config.toml: %s", e)
        return {}


def get_key(provider: str) -> Optional[str]:
    """Resolve a provider's key: config file wins, then the `api_keys` table."""
    cfg = _load_config()
    val = cfg.get(_FILE_KEY.get(provider, ""))
    if val:
        return val
    return db.get_api_key(provider)


def status() -> dict[str, str]:
    """Effective presence per provider for `GET /keys` — value never exposed."""
    return {p: ("set" if get_key(p) else "unset") for p in PROVIDERS}


def set_keys(values: dict[str, Optional[str]]) -> dict[str, str]:
    """Persist supplied keys to the DB (`PUT /keys`); returns new effective status.

    Only non-empty provided values are written. Note the config file still wins
    on read (A.2.6), so `status()` may report "set" from the file regardless.
    """
    for p in PROVIDERS:
        v = values.get(p)
        if v:
            db.set_api_key(p, v)
    return status()
