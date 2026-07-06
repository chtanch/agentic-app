// The six built-in tools (PRD §5.1 / Appendix B §B.4), mirrored on the frontend
// purely for display: the checkbox labels, help text, and which tools are
// workspace-scoped (so the editor knows when to require a workspace folder).
// The backend `tool_names.py` remains the source of truth for validation and
// isolation — these `name` values must match it exactly.

export const TOOLS = [
  { name: "web_search", label: "Web Search", file: false,
    description: "Search the web via Tavily (needs a Tavily API key)." },
  { name: "calculator", label: "Calculator", file: false,
    description: "Evaluate a math expression with a safe evaluator." },
  { name: "current_datetime", label: "Current Date & Time", file: false,
    description: "Return the current date and time (timezone-aware)." },
  { name: "file_search", label: "File Search", file: true,
    description: "Find files by name or pattern inside the workspace folder." },
  { name: "file_read", label: "File Read", file: true,
    description: "Read a file's contents from inside the workspace folder." },
  { name: "file_edit", label: "File Edit", file: true,
    description: "Overwrite a file inside the workspace folder (destructive, no undo)." },
];

const FILE_TOOLS = new Set(TOOLS.filter((t) => t.file).map((t) => t.name));

/** Does this selected-tool list include any workspace-scoped file tool? */
export const usesFileTools = (names) => names.some((n) => FILE_TOOLS.has(n));

/** Human label for a tool name (falls back to the raw name). */
export const toolLabel = (name) =>
  TOOLS.find((t) => t.name === name)?.label ?? name;
