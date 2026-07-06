"""Shared tool-side types (Appendix B §B.1).

These two types are the ONLY thing that crosses the tool boundary: the turn loop
(A.3.2) depends only on `Tool`/`ExecutionContext`, and each handler depends only
on them. A handler returns a plain `str` — recoverable failures come back as an
error string; unrecoverable ones raise (caught + logged as a crash at the B.5
call site, never aborting the turn).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Type

from pydantic import BaseModel


@dataclass(frozen=True)
class ExecutionContext:
    """Small per-call context threaded into every handler by the turn loop.

    Carries the calling agent's sandbox root. File handlers read
    `workspace_folder`; non-file handlers ignore it. It is
    NOT validated here — a null/invalid workspace surfaces as an error string
    returned from inside the file handler, never as a raised exception.
    """
    workspace_folder: Optional[str]        # per-agent root; may be None
    agent_id: int                          # correlation context for DEBUG logs (§6.1)


# A handler takes validated args (a pydantic model instance) + context, returns a str.
# Recoverable failures are returned as an error string; unrecoverable ones raise.
Handler = Callable[[BaseModel, ExecutionContext], str]


@dataclass(frozen=True)
class Tool:
    """A registry entry"""
    name: str
    description: str
    args_model: Type[BaseModel]            # the pydantic model; source of truth for the schema
    handler: Handler

    @property
    def input_schema(self) -> dict[str, Any]:
        """The JSON Schema sent to the LLM as the tool's parameters.

        Derived from the pydantic model so schema and validation can never drift.
        """
        return self.args_model.model_json_schema()
