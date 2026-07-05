"""Canonical tool names (Appendix B §B.4).

These 6 names are the allowed values in an agent's `tools[]` (PRD §5.1,
`tools_json`). Phase 1 only needs the *set* to validate agent create/edit
bodies; the actual handlers + registry arrive in Phase 3 (Appendix B), which
will remain the runtime source of truth for isolation. Kept here as a plain
constant so agent CRUD does not depend on the tool package yet.
"""

from __future__ import annotations

# stored name -> whether the tool is workspace-scoped (Appendix B §B.4).
TOOLS: dict[str, bool] = {
    "web_search": False,
    "file_search": True,
    "file_read": True,
    "file_edit": True,
    "calculator": False,
    "current_datetime": False,
}

TOOL_NAMES: frozenset[str] = frozenset(TOOLS)
