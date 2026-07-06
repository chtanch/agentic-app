"""The tool registry (Appendix B §B.2).

Handler-agnostic: a new tool is a new `register(...)` call in its own module +
one import line in `__init__.py` — no other code changes anywhere (PRD Decision
#15). `serialize_tools` is where per-agent tool ISOLATION is really enforced
(G4): only assigned, registered tools reach the provider.
"""

from __future__ import annotations

import logging

from .base import Tool

log = logging.getLogger(__name__)

_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    """Register one tool. Called once per tool at import time (see tools/__init__.py).

    'Dynamic tool registration' (PRD Decision #15) is scored on this: a new tool
    is a new register(...) call in its own module + one import line — no other
    code changes anywhere.
    """
    if tool.name in _REGISTRY:
        raise ValueError(f"duplicate tool name: {tool.name!r}")
    _REGISTRY[tool.name] = tool


def get(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def all_tools() -> dict[str, Tool]:
    return dict(_REGISTRY)


def serialize_tools(assigned: list[str]) -> list[dict]:
    """Build the OpenRouter `tools` array from an agent's assigned-tool list.

    ISOLATION (PRD G4): only assigned, registered tools are serialized. An
    assigned name with no registered tool is skipped (logged at DEBUG). The
    DEBUG log records exactly what this returns per request (§6.1), which is the
    audit trail for tool isolation.
    """
    out: list[dict] = []
    for name in assigned:
        tool = _REGISTRY.get(name)
        if tool is None:
            log.debug("skipping unregistered assigned tool: %r", name)
            continue                        # unknown assigned name — skip, log at DEBUG
        out.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        })
    return out
