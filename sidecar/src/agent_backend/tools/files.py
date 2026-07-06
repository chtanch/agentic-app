"""File tools — shared sandbox helper + the three file tools (Appendix B §B.3.4).

This is where the per-agent sandbox is enforced INSIDE the handler (PRD §5.3,
A.3.3 §6): the context carries the root, the handler resolves the requested path
against it and refuses anything that escapes — including the
`workspace_folder is None` case, which returns an error string the model sees
rather than falling back to any default. File Edit is a full-file overwrite with
no undo (PRD Decision, disclosed in README).
"""

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
