# Appendix A — Architecture & Interfaces

**Companion to:** PRD — Windows Agentic Desktop Application (v0.91)
**Purpose:** Pin down the three things the PRD leaves implicit but a build needs explicit: (A) the component/data-flow picture, (B) the frontend↔sidecar REST contract, and (C) the agent turn / tool-calling loop. Written so a coding assistant can implement each half against a fixed seam.

---

## A.1 Component & Data Flow

```
┌──────────────────────────────────────────────────────────────┐
│  Windows .exe  (Tauri installer output)                       │
│                                                                │
│  ┌────────────────────────┐         ┌───────────────────────┐ │
│  │  Tauri shell (Rust)     │ spawn/  │  Flask sidecar         │ │
│  │  - window + webview     │ manage  │  (PyInstaller'd exe)   │ │
│  │  - spawns sidecar       ├────────▶│  - agent loop          │ │
│  │  - terminates on exit    │ life-   │  - tool registry       │ │
│  │                          │ cycle   │  - SQLite access        │ │
│  │  ┌────────────────────┐ │         │  bound 127.0.0.1:PORT   │ │
│  │  │ React + Mantine UI │ │  local  │                         │ │
│  │  │ (static bundle)    │ │  REST   │                         │ │
│  │  │                    │◀┼─────────┼─▶ GET /health           │ │
│  │  │  3 views + settings│ │ (HTTP,  │   /agents, /chat, ...   │ │
│  │  └────────────────────┘ │  JSON,  │                         │ │
│  └────────────────────────┘  no SSE) └───────────┬───────────┘ │
│                                                    │             │
└────────────────────────────────────────────────────┼────────────┘
                                                     │
                         ┌───────────────────────────┼───────────────┐
                         │                            │               │
                         ▼                            ▼               ▼
                  ┌─────────────┐            ┌──────────────┐  ┌────────────┐
                  │  SQLite DB   │            │  OpenRouter   │  │  Tavily    │
                  │ agents/msgs/ │            │  (LLM + tool  │  │  (web      │
                  │  api_keys    │            │   calling)    │  │   search)  │
                  └─────────────┘            └──────────────┘  └────────────┘
                                                     │
                                                     ▼
                                          ┌──────────────────────┐
                                          │ Workspace folder      │
                                          │ (file tools, sandboxed)│
                                          └──────────────────────┘
```

**Reading the diagram:**
- Everything above the outer box is one installed `.exe`. The Rust shell owns the window and the sidecar's lifecycle; it does *not* contain business logic.
- The React UI and the Flask sidecar are two separately-built halves that meet only at the REST contract in A.2. That seam is the contract; neither half assumes anything about the other beyond it.
- The sidecar is the only component that touches SQLite, OpenRouter, Tavily, and the filesystem. Keys never leave it; the frontend never calls OpenRouter/Tavily directly.
- The workspace folder is **per-agent**, not a single app-wide root. Each agent carries its own `workspace_folder`, and file-tool handlers are sandboxed to the calling agent's folder (PRD §5.3). The diagram's single "Workspace folder" box is per-agent at runtime — whichever agent is taking the turn supplies the root.

---

## A.2 Frontend ↔ Sidecar REST Contract

Conventions for all endpoints:
- Base URL `http://127.0.0.1:<PORT>` (hardcoded port per packaging decision).
- Request and response bodies are JSON; `Content-Type: application/json`.
- Non-streaming: every call is a single request → single response. A chat turn returns the *entire* resolved turn at once, including any tool calls and their results.
- Uniform error envelope (see A.2.7) — every failure, from any endpoint, returns the same shape so the UI has exactly one error path to render.

### A.2.1 Health / readiness

```
GET /health  →  200  { "ok": true }
```
Used by the frontend's launch-time retry/backoff to know the sidecar has bound its port before firing real calls. No auth, no side effects.

### A.2.2 Agents

```
GET /agents
  → 200 { "agents": [ AgentSummary, ... ] }

POST /agents
  body: { "name", "description", "model_id", "tools": ["web_search", ...],
          "workspace_folder": "C:\\Users\\me\\agent-files" | null }
  → 201 { "agent": Agent }

GET /agents/{id}
  → 200 { "agent": Agent }
  → 404 (error envelope) if not found

PUT /agents/{id}
  body: { "name", "description", "model_id", "tools": [...],
          "workspace_folder": "..." | null }                    // full replace
  → 200 { "agent": Agent }

DELETE /agents/{id}
  → 200 { "deleted": true }        // cascades to messages (DB-enforced, §5.5)
  → 404 (error envelope) if not found   // consistent with GET/PUT on a missing id
```

`AgentSummary` = `{ id, name }` — the minimum the list view needs (PRD §5.4: names with edit/delete/click-to-chat; the model isn't shown in the list). Full config is fetched on demand via `GET /agents/{id}` when the user opens the editor or chat.
`Agent` = `{ id, name, description, model_id, tools: [...], workspace_folder: "..." | null, created_at }`.
- `workspace_folder` is the per-agent sandbox root for file tools (PRD §5.3). It's nullable: an agent with no file tools assigned typically leaves it `null`. If file tools *are* assigned but `workspace_folder` is `null`, file-tool calls fail by returning an error string to the model at execution time (A.3.3 §6) rather than the create/edit call being rejected — the contract doesn't hard-require a workspace, it's validated per tool call. The frontend editor is where a workspace is prompted for when a file tool is checked.

Note: the request accepts a bare `model_id` for UI simplicity; the sidecar expands it into the stored `{base_url, api_key_provider, model_id}` shape (PRD Decision #10), where `api_key_provider` names a provider (e.g. `"openrouter"`) that the sidecar resolves to the literal key against the `api_keys` table at call time. The frontend never sees `base_url`/`api_key_provider`.

### A.2.3 Chat — read history

```
GET /agents/{id}/messages
  → 200 { "messages": [ Message, ... ] }   // chronological, ascending
```
`Message` = `{ id, role, content, tool_calls: [...] | null, tool_call_id: "..." | null, created_at }`.
- `role` ∈ `user | assistant | tool` (system prompt is the agent's `description`, not stored as a message row for display).
- `content` renders as a chat bubble **for `user` and `assistant` rows only**. `tool_calls` (when present on an assistant row) renders as the distinct collapsible cards (PRD §5.4).
- **`tool` rows are not rendered as their own bubble.** A `tool` row's `content` is a tool's raw output, which is already surfaced inside the originating assistant row's tool-call card (name → args → result). Rendering it again as a standalone bubble would duplicate it. The frontend therefore *skips `role="tool"` rows* when laying out bubbles; their content reaches the UI only through the card. (The rows are still returned by the API and still stored — the turn loop needs them for replay, PRD §5.5 — this is purely a rendering filter.)
- **`tool_call_id`** is present on `tool` rows and is how the frontend pairs a tool *result* with the assistant `tool_calls` entry that produced it (each `tool_calls[i]` carries a matching `id`). It's `null` on `user`/`assistant` rows.
- The REST shape is unchanged by the storage change: the sidecar stores the full raw message in the `message_json` column (PRD §5.5) but the API still exposes only the flat `content` + `tool_calls` + `tool_call_id` the UI needs. `tool_calls` and `tool_call_id` are derived from `message_json` server-side. Reasoning/`reasoning_details` are **not** sent to the frontend — they're a server-side replay concern only (A.3.2), never rendered.

### A.2.4 Chat — send a message (the core call)

```
POST /agents/{id}/messages
  body: { "content": "user text" }
  → 200 {
      "messages": [ Message, ... ]   // the NEW rows produced by this turn,
                                     // in order: user msg, any tool msgs,
                                     // final assistant msg
    }
  → error envelope on a turn-aborting failure (bad key / model error / offline)
                                     // a tool failing does NOT abort the turn: it
                                     // comes back to the model as a tool-result string (A.3.3 §2)
```
This is the one call that triggers the turn loop in A.3. Because it's non-streaming, the response arrives only once the *entire* turn (including multi-round tool calls) has resolved. The frontend shows a "thinking…" indicator between request and response.

### A.2.5 Clear conversation

```
DELETE /agents/{id}/messages
  → 200 { "cleared": true }        // deletes rows, agent intact (§5.4)
```
The backend performs the clear unconditionally and returns 200 — it enforces no "are you sure?" handshake. Any confirmation dialog is purely the frontend's choice, and per the current design neither clear nor delete-agent prompts.

### A.2.6 API keys

```
GET /keys
  → 200 { "openrouter": "set" | "unset", "tavily": "set" | "unset" }
        // presence only — the key value is NEVER returned

PUT /keys
  body: { "openrouter": "sk-...", "tavily": "tvly-..." }  // either or both
  → 200 { "openrouter": "set", "tavily": "set" }
```
Writes go to the `api_keys` table. Note the file/env source still wins on precedence at sidecar startup (PRD Decision #17); `GET /keys` reflects the *effective* resolved state so the UI can show "already configured via file" honestly.

### A.2.7 Uniform error envelope

Every non-2xx response, regardless of endpoint, returns:
```json
{
  "error": {
    "kind": "bad_api_key | model_error | offline | not_found | bad_request",
    "message": "human-readable, safe to show the user",
    "detail": "optional extra context, may be null"
  }
}
```
The envelope covers failures that abort a request or a turn. PRD §6 / §6.1 name **four** runtime failure modes the app must handle: bad/missing API key, model call failure, tool execution failure, and offline. **Three of those four map to an envelope `kind`** — `bad_api_key`, `model_error`, and `offline` — because they abort the turn. The **fourth, tool execution failure, is deliberately *not* an envelope kind**: it never aborts the turn (recoverable failures return a tool-result string; an unexpected crash is caught, logged, and handed back to the model as a safe string — see the note below and §6.1). So the four failure modes are all *logged* (§6.1), but only three are *enveloped*.

The envelope's two remaining kinds — `not_found` and `bad_request` — are not runtime failure modes at all: they're protocol-level HTTP errors (a 404 for an unknown id, a 400 for a malformed body) that any REST endpoint can return. That gives the five `kind` values above: three from the runtime failure modes plus two protocol-level ones.

The frontend renders one error component and switches copy on `kind`. `message` is always safe to display (no secrets, no raw stack traces — those go to the DEBUG log per §6.1).

Note that **tool execution failure is *not* in this list.** A failing tool no longer surfaces as an error envelope: recoverable tool failures are returned to the model as a tool-result string and the model responds to the user within an ordinary successful (200) turn; an unexpected tool crash is caught, logged (§6.1), and likewise handed back to the model as a safe string (Appendix B.5). Tool execution failure remains one of the four *logged* failure modes in §6.1, but it is not an enveloped, turn-aborting `kind`.

---

## A.3 Agent Turn / Tool-Calling Loop

This is what `POST /agents/{id}/messages` executes server-side. It is the piece the PRD describes in parts but never as a sequence.

### A.3.1 Preconditions
- Load the agent by id (404 if missing).
- Resolve the OpenRouter key (fail early with `bad_api_key` if unresolved).
- Build the `tools` array to send to the LLM **only from this agent's assigned tool list** — unassigned tool schemas are never serialized (PRD G4 isolation; DEBUG log records exactly what was serialized, §6.1).
- Note the agent's `workspace_folder`; it's threaded into every file-tool handler invocation this turn as the sandbox root (PRD §5.3). It is *not* resolved/validated here — a missing or invalid workspace surfaces per file-tool call as an error string returned to the model (A.3.3 §6), not as a precondition failure that aborts the turn (a turn may legitimately use non-file tools too).

### A.3.2 The loop (pseudocode)

```
def handle_turn(agent, user_text):
    persist Message(role="user", content=user_text)

    # load_conversation rebuilds the provider-shaped messages array from the DB.
    # For assistant/tool rows it replays message_json VERBATIM (full object,
    # incl. reasoning/reasoning_details, unmodified + in original order — §5.5).
    # For user rows it emits {role, content}. This preserved reasoning is what
    # lets reasoning models continue across tool rounds.
    messages = load_conversation(agent)      # includes the new user msg
    tool_defs = serialize_tools(agent.tools) # ISOLATION: assigned tools only
    ctx = ExecutionContext(workspace_folder=agent.workspace_folder, agent_id=agent.id)
    new_rows  = []

    while True:
        # --- one LLM round-trip (non-streaming) ---
        resp = call_openrouter(
            model      = agent.model_id,
            system     = agent.description,   # system prompt
            messages   = messages,
            tools      = tool_defs,
        )
        # network / model failures raise -> caught below, mapped to envelope

        assistant_msg = resp.choices[0].message   # the FULL raw message object

        if assistant_msg has tool_calls:
            # Persist the WHOLE raw message: content + tool_calls + any
            # reasoning/reasoning_details go into message_json verbatim
            # (denormalize content into the content column for the UI).
            persist Message(role="assistant",
                            content=assistant_msg.content,
                            message_json=assistant_msg)   # stored as-is
            # Append the raw message to the replay array so the NEXT round
            # sees the model's own reasoning + tool_calls unmodified:
            messages.append(assistant_msg)
            new_rows.append(that assistant msg)

            for call in assistant_msg.tool_calls:
                # result is ALWAYS a str, fed back to the model as the tool result.
                if call.name not in agent.tools:      # defense in depth
                    result = "Error: tool not assigned to this agent"
                else:
                    # NOTE: `args` here is the validated pydantic model instance.
                    # The concrete call site (Appendix B.5) validates call.arguments
                    # (a JSON-encoded string from the provider) via
                    # tool.args_model.model_validate_json(...) inside a try/except that
                    # maps ValidationError -> "Error: invalid tool arguments" and
                    # catches any unexpected raise -> logged crash + safe string.
                    # A straight-from-this-pseudocode implementation MUST include
                    # that validation/except wrapper — see B.5.
                    result = registry[call.name].handler(
                        args,                              # validated pydantic model
                        ctx,                               # ExecutionContext: per-agent
                    )                                      # sandbox root + agent_id.
                    # Handlers return a str. Recoverable failures come back as an
                    # error string the model may recover from or explain; an
                    # unexpected raise is caught (see B.5), logged as a crash, and
                    # replaced with a safe string — the turn is never aborted.
                    # A file call with workspace=None (or a path escaping it)
                    # returns an error string the model sees, not a raised exception.

                tool_msg = {role: "tool", tool_call_id: call.id, content: result}
                persist Message(role="tool", content=result, message_json=tool_msg)
                messages.append(tool_msg)          # replay array
                new_rows.append(that tool msg)

            continue          # loop back: model sees tool results, may call again

        else:
            # no tool calls -> this is the final assistant answer.
            # Still persist the full message (may carry reasoning even with no
            # tool call) so a later turn replays it intact.
            persist Message(role="assistant",
                            content=assistant_msg.content,
                            message_json=assistant_msg)
            new_rows.append(that assistant msg)
            return new_rows    # <- the array returned by POST /messages
```

### A.3.3 Points that are easy to get wrong (call them out to the assistant)

1. **Multi-round is the default, not the exception.** The model can call a tool, see the result, then call another tool before answering. The `while True` loop with `continue` handles this; a single-pass implementation is a bug. (A sane max-iterations guard — e.g. 5 — prevents runaway loops; exceeding it returns a `model_error` envelope.)
2. **Tool errors are data, not exceptions.** A failing tool (bad path, Tavily down) returns an error string that is fed back to the model as a tool result, so the model can apologize or retry. A handler raises only for a genuine bug; that raise is caught at the call site (Appendix B.5), logged with a full traceback (§6.1), and replaced with a safe string — it does **not** abort the turn either. Only turn-level *unrecoverable* failures (unresolved model key, model API down, offline) become an error envelope that aborts the turn (A.2.7). A tool failing is never an error envelope and never aborts the turn.
3. **Isolation is enforced twice.** Once by only serializing assigned tools into `tool_defs` (the real enforcement, G4), and again by the `call.name not in agent.tools` guard before executing (defense in depth in case the model hallucinates a tool name).
4. **Persist as you go.** Each row (user, assistant-with-tool-calls, tool result, final assistant) is written to SQLite as it's produced, so a mid-turn crash leaves a coherent partial history rather than losing everything.
5. **Return only the new rows.** `POST /messages` returns just the rows this turn produced; the frontend already has prior history from `GET /messages`. (It *may* re-fetch instead — but returning the delta avoids a second round-trip.)
6. **File tools re-check the sandbox at execution time, against the calling agent's own workspace.** The loop passes `agent.workspace_folder` into each handler; every file handler resolves the requested path and verifies it's inside *that* root *inside the handler* (PRD §5.3), not upstream — the loop doesn't police tool internals. Two consequences: (a) the sandbox root is per-agent, so the same tool code enforces a different boundary depending on who's calling; and (b) if `workspace_folder` is `null` (or the path escapes the root), the handler returns an error string the model sees — it does not raise or fall back to any default directory.
7. **Store and replay the whole message; never cherry-pick fields.** Assistant/tool rows persist the full raw provider message in `message_json` (PRD §5.5), and `load_conversation` replays those objects **verbatim and in original order** — no re-serialization, reordering, or dropping of `reasoning`/`reasoning_details`. Reasoning-capable models (the curated Poolside Laguna models) reason before and between tool calls and expect prior reasoning blocks fed back to continue; OpenRouter requires the reasoning-block sequence to match the original outputs exactly. Rebuilding messages from just `role`/`content`/`tool_calls` silently drops reasoning and **degrades these models with no error raised** — the worst kind of bug because nothing surfaces it.

---

## A.4 What this appendix intentionally leaves open

- Exact Mantine component choices and view layout — implementation detail, not contract.
- SQLite access style (raw `sqlite3` vs. a thin wrapper) — internal to the sidecar.
- The curated model list contents — a data file, documented in the README per PRD §5.2.

These are safe to leave to the build because they don't cross the frontend↔sidecar seam and don't affect the turn loop.
