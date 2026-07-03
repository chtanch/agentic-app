# Appendix B — Tool Layer (Registry, Context, and the 6 Tools)

**Companion to:** PRD — Windows Agentic Desktop Application (v0.91) and Appendix A (Architecture & Interfaces).
**Purpose:** Close the one gap Appendix A leaves open (A.4): the concrete `input_schema` for each of the 6 tools, plus the shared `Tool` / `ExecutionContext` types (handlers return a plain `str`) and the registry mechanics. Written so Phase 3 ("tool registry + isolation + the 6 tools") can be built directly against fixed types, with no invented schemas.

This appendix is the authority for the **tool-side** contract. It does not change any REST contract (A.2) or the turn loop (A.3) — it fills in the `registry[call.name].handler(args, ctx)` call site those describe.

---

## B.1 Shared types

Two types are shared by every tool. They are the tool-side seam: the turn loop (A.3.2) depends only on these, and each tool depends only on these. Nothing else crosses the boundary.

**A handler returns a plain `str`.** That string is the tool's content, fed back to the model as the tool result. There is no wrapper type and no success/failure flag, because the model treats a success string and a failure string the same way: it reads the content and proceeds. The failure/success distinction is expressed by control flow, not by a return field —

- **Recoverable failure → return an error string.** Bad path, Tavily down, workspace unset, timezone unknown. The handler returns a short, safe, human-readable message; the model reads it and can retry or explain to the user. This is the ordinary path for anything the handler can anticipate.
- **Unrecoverable failure → raise.** Genuine bugs and conditions the handler did not anticipate. The handler does not try to encode these as a return value; it lets the exception propagate. The turn loop catches it, logs it with a full traceback (B.5), and hands the model a safe generic string so the turn survives — but the crash is loud in the log, distinct from a recoverable failure.

```python
# tools/base.py
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
```

Notes that matter:
- **`args_model` is the single source of truth.** `input_schema` is derived via `model_json_schema()`, so the schema advertised to the LLM and the validation applied to the LLM's arguments are guaranteed identical.
- **Recoverable failures are returned strings; unrecoverable ones raise.** A handler returns an error string for anything it can anticipate (bad path, Tavily down, workspace unset) so the model can recover. It raises only for genuine bugs. The turn loop's per-call `try/except` (B.5) catches any raise, logs it as a crash with a full traceback, and substitutes a safe string so the turn is never aborted by a single tool call (A.3.3 §2) — the crash is distinguished from a recoverable failure in the log, not in the return value.

---

## B.2 The registry

```python
# tools/registry.py
from __future__ import annotations

from .base import Tool

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
```

```python
# tools/__init__.py
from . import calculator, files, web_search, datetime_tool  # noqa: F401
# Importing each module runs its register(...) call, populating the registry.
# Add a new tool = add one module here. Nothing else changes.
```

The turn loop (A.3.2) uses this registry exactly as written there: `serialize_tools(agent.tools)` for the request, and `registry.get(call.name).handler(args, ctx)` at the call site — with the `call.name not in agent.tools` guard (A.3.3 §3) kept as defense in depth.

**One clarification vs. A.3.2 pseudocode:** the handler is called as `handler(args, ctx)`, where `args` is the validated pydantic model instance and `ctx` is the full `ExecutionContext` (which *contains* `workspace_folder` plus `agent_id` for log correlation), not a bare `workspace=` kwarg. The context object is the tidier form of "plus a small execution context" from §5.3.

---

## B.3 The 6 tools

Each tool is one module: a pydantic args model, a handler returning `str`, and a `register(...)` call. All 6 follow your calculator pattern verbatim.

### B.3.1 Calculator

```python
# tools/calculator.py
import ast
import operator as op

from pydantic import BaseModel, Field

from .base import ExecutionContext, Tool
from .registry import register


class CalculatorArgs(BaseModel):
    expression: str = Field(
        description="A mathematical expression to evaluate, e.g. '2 * (3 + 4)'. "
                    "No variables, no function calls, no names."
    )


# Safe evaluator (PRD Decision #8: no raw eval). Whitelisted operators only.
_BINOPS = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
    ast.Div: op.truediv, ast.FloorDiv: op.floordiv,
    ast.Mod: op.mod, ast.Pow: op.pow,
}
_UNARYOPS = {ast.UAdd: op.pos, ast.USub: op.neg}

# Guard against resource-exhaustion via exponentiation. `2 ** (10 ** 9)` is a
# tiny expression that would otherwise pin a CPU and blow up memory building the
# integer — "safe evaluator" (Decision #8) means safe from DoS, not just from
# `eval`. We cap both the exponent and the base magnitude before computing pow.
_MAX_POW_EXPONENT = 1000
_MAX_POW_BASE = 1e6


def _guarded_pow(base: float, exponent: float) -> float:
    if abs(exponent) > _MAX_POW_EXPONENT or abs(base) > _MAX_POW_BASE:
        raise ValueError("exponent or base too large")
    return op.pow(base, exponent)


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError("only numeric constants are allowed")
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left, right = _safe_eval(node.left), _safe_eval(node.right)
        if isinstance(node.op, ast.Pow):
            return _guarded_pow(left, right)
        return _BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return _UNARYOPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("unsupported expression element")


def calculator(args: CalculatorArgs, ctx: ExecutionContext) -> str:
    try:
        tree = ast.parse(args.expression, mode="eval")
        result = _safe_eval(tree.body)
    except ZeroDivisionError:
        return "Error: division by zero"
    except OverflowError:
        return "Error: result too large to compute"
    except (ValueError, SyntaxError, TypeError):
        return "Error: could not evaluate that expression"
    return str(result)


register(Tool(
    name="calculator",
    description="Evaluate a math expression. No variables, no function calls.",
    args_model=CalculatorArgs,
    handler=calculator,
))
```

### B.3.2 Current Date & Time

```python
# tools/datetime_tool.py
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from .base import ExecutionContext, Tool
from .registry import register


class DateTimeArgs(BaseModel):
    timezone: str | None = Field(
        default=None,
        description="Optional IANA timezone name, e.g. 'America/New_York' or "
                    "'Europe/London'. If omitted, the system local timezone is used.",
    )


def current_datetime(args: DateTimeArgs, ctx: ExecutionContext) -> str:
    try:
        tz = ZoneInfo(args.timezone) if args.timezone else datetime.now().astimezone().tzinfo
    except ZoneInfoNotFoundError:
        return f"Error: unknown timezone: {args.timezone!r}"
    now = datetime.now(tz)
    return now.isoformat()


register(Tool(
    name="current_datetime",
    description="Return the current date and time, timezone-aware (ISO 8601).",
    args_model=DateTimeArgs,
    handler=current_datetime,
))
```

### B.3.3 Web Search (Tavily)

Requires the Tavily key (PRD Decision #2). Key resolution is the sidecar's job; the handler reads the already-resolved key from a small accessor rather than the DB directly, so tools stay ignorant of persistence.

```python
# tools/web_search.py
import httpx
from pydantic import BaseModel, Field

from .base import ExecutionContext, Tool
from .registry import register
from ..keys import get_key            # resolves 'tavily' per §5.6 precedence (file/env > DB)

_TAVILY_URL = "https://api.tavily.com/search"
_TIMEOUT = 15.0


class WebSearchArgs(BaseModel):
    query: str = Field(description="The search query.")
    max_results: int = Field(
        default=5, ge=1, le=10,
        description="How many results to return (1-10).",
    )


def web_search(args: WebSearchArgs, ctx: ExecutionContext) -> str:
    key = get_key("tavily")
    if not key:
        # A missing tool key is a recoverable/explainable failure returned as a
        # string, NOT the turn-aborting bad_api_key envelope — that one is
        # reserved for the agent's own model key (A.3.1 / A.3.3 §2).
        return "Error: web search is unavailable: no Tavily API key configured"
    try:
        resp = httpx.post(
            _TAVILY_URL,
            headers={"Authorization": f"Bearer {key}"},   # Tavily auth is a Bearer header
            json={
                "query": args.query,
                "max_results": args.max_results,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.TimeoutException:
        return "Error: web search timed out"
    except httpx.HTTPStatusError as e:
        return f"Error: web search request failed (HTTP {e.response.status_code})"
    except httpx.HTTPError:
        return "Error: web search request failed"

    results = data.get("results", [])
    if not results:
        return "No results found."

    lines = [
        f"- {r.get('title', '(untitled)')}\n  {r.get('url', '')}\n  {r.get('content', '')}"
        for r in results
    ]
    return "\n".join(lines)


register(Tool(
    name="web_search",
    description="Search the web and return summarized, linked results.",
    args_model=WebSearchArgs,
    handler=web_search,
))
```

### B.3.4 File tools (shared sandbox helper + three tools)

All three file tools share one sandbox resolver. This is where the per-agent sandbox is enforced **inside the handler** (PRD §5.3, A.3.3 §6): the context carries the root, the handler resolves the requested path against it and refuses anything that escapes — including the `workspace_folder is None` case, which returns an error string the model sees rather than falling back to any default.

```python
# tools/files.py
from pathlib import Path

from pydantic import BaseModel, Field

from .base import ExecutionContext, Tool
from .registry import register


def _resolve_in_sandbox(ctx: ExecutionContext, rel_path: str) -> Path | str:
    """Resolve `rel_path` against the calling agent's workspace root.

    Returns a safe absolute Path, or an error string if there is no workspace
    or the path escapes it. Callers must check `isinstance(result, str)` and
    return it straight to the model. Enforcement lives HERE, per agent
    (A.3.3 §6) — not in the turn loop, not in the UI.
    """
    if not ctx.workspace_folder:
        return "Error: no workspace folder configured for this agent"
    root = Path(ctx.workspace_folder).resolve()
    try:
        target = (root / rel_path).resolve()
    except (OSError, ValueError):
        return "Error: invalid path"
    # Containment check: target must be root itself or below it.
    if target != root and root not in target.parents:
        return "Error: path escapes the agent's workspace folder"
    return target


class FileSearchArgs(BaseModel):
    pattern: str = Field(
        description="A glob pattern to match file names, e.g. '*.txt' or "
                    "'notes/**/*.md'. Matched relative to the agent's workspace.",
    )


def file_search(args: FileSearchArgs, ctx: ExecutionContext) -> str:
    resolved = _resolve_in_sandbox(ctx, ".")
    if isinstance(resolved, str):
        return resolved
    root = resolved
    try:
        # NotImplementedError: Path.glob raises it for absolute patterns (and,
        # on some versions, certain `**` uses) — adversarial input like an
        # absolute pattern must return a clean error string, not propagate as a
        # "crash" the turn loop logs as a bug.
        matches = sorted(
            str(p.relative_to(root)) for p in root.glob(args.pattern) if p.is_file()
        )
    except (OSError, ValueError, NotImplementedError):
        return "Error: file search failed"
    if not matches:
        return "No matching files."
    return "\n".join(matches)


class FileReadArgs(BaseModel):
    path: str = Field(
        description="Path to the file to read, relative to the agent's workspace.",
    )


def file_read(args: FileReadArgs, ctx: ExecutionContext) -> str:
    resolved = _resolve_in_sandbox(ctx, args.path)
    if isinstance(resolved, str):
        return resolved
    target = resolved
    if not target.is_file():
        return f"Error: no such file: {args.path}"
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "Error: could not read file"
    return text


class FileEditArgs(BaseModel):
    path: str = Field(
        description="Path to the file to write, relative to the agent's workspace. "
                    "Created if it does not exist.",
    )
    content: str = Field(
        description="The full new file contents. This OVERWRITES the entire file; "
                    "there is no partial edit and no undo.",
    )


def file_edit(args: FileEditArgs, ctx: ExecutionContext) -> str:
    resolved = _resolve_in_sandbox(ctx, args.path)
    if isinstance(resolved, str):
        return resolved
    target = resolved
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(args.content, encoding="utf-8")
    except OSError:
        return "Error: could not write file"
    return f"Wrote {len(args.content)} chars to {args.path}"


register(Tool(
    name="file_search",
    description="Find files by glob pattern within the agent's workspace folder.",
    args_model=FileSearchArgs,
    handler=file_search,
))
register(Tool(
    name="file_read",
    description="Read a file's contents from within the agent's workspace folder.",
    args_model=FileReadArgs,
    handler=file_read,
))
register(Tool(
    name="file_edit",
    description="Overwrite a file (full-file, no undo) within the agent's workspace folder.",
    args_model=FileEditArgs,
    handler=file_edit,
))
```

---

## B.4 Tool-name registry (the canonical set)

These 6 names are the canonical `tools[]` values stored on an agent (PRD §5.1, `tools_json`) and checked by the turn loop's isolation guard (A.3.3 §3). The frontend's per-tool checkboxes (§5.4) map one-to-one to these.

| Stored name        | Tool                | Workspace-scoped |
| ------------------ | ------------------- | ---------------- |
| `web_search`       | Web Search (Tavily) | no               |
| `file_search`      | File Search         | yes              |
| `file_read`        | File Read           | yes              |
| `file_edit`        | File Edit           | yes              |
| `calculator`       | Calculator          | no               |
| `current_datetime` | Current Date & Time | no               |

The "workspace-scoped" column is the only place a tool's relationship to `workspace_folder` is asserted as data. The frontend uses it to decide when to prompt for a workspace (PRD §5.4: prompt "whenever a file tool is checked") — i.e. when any checked tool has `workspace-scoped = yes`.

---

## B.5 How this maps back to the turn loop (A.3.2)

The call site in A.3.2, in concrete terms:

```python
import logging

from pydantic import ValidationError

from tools import registry
from tools.base import ExecutionContext

log = logging.getLogger(__name__)

ctx = ExecutionContext(workspace_folder=agent.workspace_folder, agent_id=agent.id)

# ISOLATION at serialization (the real enforcement, G4):
tool_defs = registry.serialize_tools(agent.tools)

# ... inside the loop, for each call the model makes.
# result is ALWAYS a str fed back to the model as the tool result.
if call.name not in agent.tools:                 # defense in depth (A.3.3 §3)
    result = "Error: tool not assigned to this agent"
else:
    tool = registry.get(call.name)
    try:
        # OpenRouter/OpenAI return function.arguments as a JSON-encoded STRING,
        # not a mapping. model_validate() expects a mapping, so parse the raw
        # JSON string here. model_validate_json raises ValidationError on
        # malformed JSON too, so the except below still catches it. (`or "{}"`
        # guards zero-arg tools whose arguments may arrive as "" or null.)
        args = tool.args_model.model_validate_json(call.arguments or "{}")   # schema == validation
        result = tool.handler(args, ctx)          # recoverable failures come back as strings
    except ValidationError:
        result = "Error: invalid tool arguments"
    except Exception:                             # unrecoverable: a genuine bug in the handler
        # Log loudly with a full traceback + correlation context (§6.1), but do
        # NOT abort the turn — hand the model a safe generic string so it can
        # move on. The crash is distinguished from a recoverable failure HERE,
        # in the log, not in the return value.
        log.exception("tool crashed", extra={"agent_id": agent.id, "tool": call.name})
        result = "Error: the tool failed unexpectedly"
```

Two things this pins down that the pseudocode left implicit:
1. **Argument validation is `model_validate_json` against the same model that produced `input_schema`.** The provider delivers `function.arguments` as a JSON-encoded string, so it is parsed and validated in one step against the model that generated the advertised schema. A malformed tool call from the model — bad JSON or schema-invalid — becomes an error string the model can correct, not a 500.
2. **Every path out of a handler yields a `str` fed back to the model.** Recoverable failures are returned strings; an unrecoverable raise is caught here, logged as a crash with a full traceback, and replaced with a safe generic string. The turn loop never lets a raised exception from a tool abort the turn, matching A.3.3 §2 ("tool errors are data, not exceptions") — and the raw exception text never reaches the model, only the log.

---

## B.6 What B still leaves open (safely)

- **Exact Tavily response fields to surface.** B.3.3 uses `title/url/content`; trimming or reformatting is a display choice with no contract impact.
- **File-read size cap / binary handling.** v1 reads text with `errors="replace"`; a max-bytes guard is a reasonable hardening add (Phase 6) and changes no signature.
- **`current_datetime` output format.** ISO 8601 chosen; any format is internal to the handler.

None of these cross the tool-side seam (the shared types in B.1 and the `str` handler return), so they're safe to settle during the build.
