"""Curated OpenRouter model list (PRD §5.2, Appendix A §A.2.8 / §A.4).

Loaded once from the bundled `data/models.json`. Single source of truth for
both the `GET /models` dropdown and `model_id` validation/expansion at agent
create/edit. The data file names the provider key axis `api_key_ref`; the stored
model-config shape (§5.5, Decision #10) calls it `api_key_provider`, so we
normalize on load.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from importlib.resources import files
from typing import Any, Optional

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _catalog() -> dict[str, Any]:
    raw = files("agent_backend").joinpath("data/models.json").read_text("utf-8")
    data = json.loads(raw)
    log.info("loaded %d curated models", len(data.get("models", [])))
    return data


def list_for_api() -> list[dict[str, str]]:
    """The dropdown payload: only `{id, label}` (Appendix A §A.2.8).

    Other fields (free/context/note/recommended) are reference-only and not
    exposed; the v1 UI shows the model name only.
    """
    return [{"id": m["id"], "label": m["label"]} for m in _catalog()["models"]]


def is_known(model_id: str) -> bool:
    return any(m["id"] == model_id for m in _catalog()["models"])


def expand(model_id: str) -> Optional[dict[str, str]]:
    """Expand a bare `model_id` into the stored `model_config` shape.

    Returns `{base_url, api_key_provider, model_id}` (Decision #10, A.2.2 note),
    or None if the id is not in the curated list.
    """
    if not is_known(model_id):
        return None
    defaults = _catalog()["provider_defaults"]
    return {
        "base_url": defaults["base_url"],
        # normalize the data file's `api_key_ref` -> canonical `api_key_provider`
        "api_key_provider": defaults["api_key_ref"],
        "model_id": model_id,
    }
