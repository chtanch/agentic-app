# PRD — Windows Agentic Desktop Application

**Version:** v0.91

---

## 1. Overview

Build a native Windows desktop application that lets a user create, configure, and chat with multiple independent AI agents. Each agent has its own identity (name, system prompt), its own LLM (an OpenRouter model — free-tier models recommended by default to keep demoing cost-free), and its own set of tools. The app must persist all state across restarts and ship as an installable Windows `.exe`, with source on GitHub.

The agent/tool logic runs as a **Python sidecar** spawned by the Tauri shell and reached over local REST; the frontend is a deliberately minimal **React + Mantine** UI. This should be built as a genuinely well-architected local desktop app: clean, independent agent and tool abstractions; reliable state persistence; careful error handling; and documentation that clearly records the design decisions and trade-offs made along the way.

## 2. Goals

- G1: A user can create N agents, each with an independent name, system prompt, model, and tool set.
- G2: Changing one agent's config (model, tools, prompt) never affects another agent.
- G3: A user can chat with any agent; tool invocations are visually distinguishable from normal assistant text.
- G4: An agent can only ever invoke tools explicitly assigned to it
- G5: All state (agents, tool assignments, conversation history, API keys) survives an app restart.
- G6: The app installs and runs as a native Windows application.

## 3. Non-Goals

- Multi-user accounts / auth — this is a single local user application.
- Cloud sync of state — local persistence only.
- Mobile/macOS/Linux builds — Windows only, per spec.
- Editing/branching within a conversation (e.g., edit a past message and regenerate) — out of scope.
- Multiple conversations per agent — each agent has exactly one conversation. The user can clear an agent's conversation when a task is done (see §5.4), which resets it to empty; there is no conversation-list, switcher, rename, or title UI.
- Multi-agent group chats (multiple agents in one conversation) — spec asks for chatting with agents individually.
- User-facing UI for custom model IDs or alternative (non-OpenRouter) providers — v1 ships one curated list against one provider. The model-config *shape* accommodates this later (see §5.2) at no cost, but no UI is built for it now.
- MCP tool support — v1 builds no MCP client or MCP-backed tools. The tool registry happens to be handler-agnostic (see §5.3), so a non-local tool source is an additive registry entry later, but nothing is built toward MCP.

## 4. Target User

A single local user who wants to stand up several purpose-built agents (e.g., "Research Assistant" with web search, "File Organizer" with file tools, "Math Helper" with calculator) and interact with them independently.

## 5. Functional Requirements

### 5.0 Application Architecture

- **Agent loop runs as a Python sidecar.** The Tauri shell is Rust, but all agent/tool-calling logic is implemented in Python and bundled as a **sidecar process** that Tauri spawns on launch and manages the lifecycle of (spawn on start, terminate on exit).
- **Frontend ↔ sidecar over local REST.** The React frontend communicates with the sidecar via local HTTP REST calls, non-streaming request/response (matching Decision #4). This keeps the Rust surface minimal (spawn + lifecycle only) and puts the core logic in Python.
- **Sidecar binds to `127.0.0.1` only** (never `0.0.0.0`). The local API holds the user's API keys and exposes file tools; localhost-only binding ensures no other device on the network can reach it. Set explicitly, not left to a framework default.

### 5.1 Agent Management
- Create / edit / delete agents.
- Each agent config: `name`, `description` (used as system prompt), `model` (OpenRouter model id — free-tier recommended by default), `tools[]` (subset of the tool registry, saved when the agent is created/edited), `workspace_folder` (the per-agent root that file tools are sandboxed to — see §5.3).
- Agent list is the home/landing view.
- Deleting an agent cascades to messages (enforced by the DB, see §5.5).

### 5.2 Model Selection
- Model is chosen from a curated list of OpenRouter models, **all confirmed to support native tool/function calling**.
- Model choice is stored per-agent; editing agent A's model must not affect agent B.
- Model-config shape: model configuration is stored as a small object `{base_url, api_key_provider, model_id}` rather than a bare model-ID string — the same three axes as the OpenAI-compatible `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL` triple, except the key axis holds a *provider name* rather than the secret. This costs nothing over hardcoding OpenRouter (the LLM client wrapper just takes `base_url`/`api_key`/`model_id` as parameters), and makes a future custom-model-ID input or alternate-provider seam additive rather than a rewrite. `api_key_provider` is a provider reference (e.g. `"openrouter"`); the sidecar resolves it to the literal key against the `api_keys` table / file-env precedence (Decision #17) at call time, so the secret stays single-sourced (Decision #13) and is never duplicated into per-agent config.

### 5.3 Tool System
Minimum tool set:

| Tool                | Behavior                                                                                                  |
| ------------------- | --------------------------------------------------------------------------------------------------------- |
| Web Search          | Query via Tavily API (**requires its own API key**), return summarized/linked results                     |
| File Search         | Find files by name/pattern, scoped to the agent's own workspace folder                                     |
| File Read           | Read file contents, scoped to the agent's workspace folder                                                 |
| File Edit           | Overwrite file contents (full-file overwrite only, no partial patch/diff). Scoped to the agent's workspace folder |
| Calculator          | Evaluate a math expression via a safe expression evaluator (no raw `eval`)                                |
| Current Date & Time | Return current date/time, ideally timezone-aware                                                          |
|                     |                                                                                                           |

- File Search/Read/Edit are sandboxed to the **agent's own workspace folder** — a per-agent root the user sets in the agent editor (§5.4), not the full filesystem and not a single app-wide folder. Each agent stores its own `workspace_folder`; changing agent A's workspace never affects agent B (mirrors the model/tool isolation in G2). Enforced in the tool handler itself — the handler is passed the calling agent's workspace root, resolves the requested path, and verifies it stays inside that root — not just hidden in the UI.
- If an agent that has file tools assigned has no `workspace_folder` set, its file-tool calls fail by returning an error string ("no workspace folder configured for this agent") fed back to the model, rather than falling back to any default directory. The editor marks the workspace field as required whenever a file tool is checked.
- File Edit is destructive by design (full-file overwrite — simpler schema than patch/diff) with no undo in v1.
- **Tool registry is a handler-agnostic abstraction.** Each tool is a registry entry `{name, description, input_schema, handler}`, where `handler` is "something that takes validated args (plus a small execution context) and returns a result." The execution context carries the calling agent's `workspace_folder` so file handlers know their sandbox root; non-file handlers simply ignore it, keeping the interface uniform. In v1 every handler is a local Python function. This is what "dynamic tool registration" is scored on — a new tool is registered in one place, no other code changes. Because the interface is handler-agnostic rather than "a local Python function," a future non-local tool source is an additive registry entry, but none is built in v1.
- Tool isolation: each agent's assigned tool set is saved when the agent is created/edited. On each of that agent's turns, the sidecar builds the `tools` array sent to the LLM *only* from that agent's assigned-tool list — unassigned tool schemas are never serialized into the API request. Enforced agent-side, not in the UI. (DEBUG logging records the serialized tool defs per request, so isolation can be verified from the logs.)

### 5.4 Chat Experience
- Data model: `Agent (1) → Message (many)` — **one conversation per agent.** Messages hang directly off the agent; there is no conversation table.
- Conversation reset: the user can clear an agent's conversation when a task is complete, deleting that agent's messages and leaving the agent itself intact.
- **UI is deliberately minimal — three views only**:
  1. **Agent list (home):** list of agents, "New Agent" button, edit/delete per agent. Clicking an agent opens its chat.
  2. **Agent editor:** a plain form — name, description (system prompt) textarea, model dropdown (curated list), a checkbox per tool (the checkboxes are the tool assignment), and a **workspace folder** input (a text field for the path plus a native folder-picker button) that sets the root the agent's file tools are sandboxed to. The workspace field is per-agent and only relevant when file tools are assigned.
  3. **Chat view:** message history, input box, send button, tool-call cards, and a "Clear conversation" action.
  Plus a small **settings view** (one text input per provider) for entering API keys — see §5.6; keys can alternatively be supplied via a config file, so the app is usable even without this screen.
- Assistant text responses render as normal chat bubbles (read straight from the message `content` column — no parsing needed).
- Tool calls render as a visually distinct collapsible card (tool name, input args, output/result, status). Because chat is non-streaming, the whole turn (including completed tool calls and results) arrives at once — cards render as already-resolved static elements, with no "running" animation state to manage.
- Non-streaming (request/response) — user sends a message, sees a "thinking…" indicator, then the full assistant reply (including any tool-call cards) appears once ready.
- **Frontend stack:** React + Mantine component library — ready-made form inputs, buttons, checkboxes, and `Card` (tool calls) with near-zero custom CSS.

### 5.5 Persistence
Single **SQLite** database is the sole persistence layer (no split JSON/DB store — one coherent data layer, with foreign keys enforcing integrity, e.g. deleting an agent cascades to its messages).

Must survive app restart: all agents + last-saved config; conversation history per agent; API key(s) if entered.

Schema (v1):

```sql
CREATE TABLE agents (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    description       TEXT NOT NULL,           -- system prompt
    model_config_json TEXT NOT NULL,           -- {base_url, api_key_provider, model_id};
                                               --   api_key_provider is a provider name (e.g.
                                               --   "openrouter"), resolved to the literal key
                                               --   against api_keys at call time

    tools_json        TEXT NOT NULL,           -- ["web_search","calculator", ...]
    workspace_folder  TEXT,                     -- nullable; per-agent file-tool sandbox root (§5.3)
    created_at        TEXT NOT NULL
);

CREATE TABLE messages (
    id              INTEGER PRIMARY KEY,
    agent_id        INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,             -- system | user | assistant | tool
    content         TEXT,                      -- plain text for the bubble (denormalized from message_json)
    message_json    TEXT,                      -- nullable; the FULL raw provider message object,
                                               -- stored verbatim (tool_calls, reasoning/reasoning_details,
                                               -- and any other provider fields). Source of truth for
                                               -- what gets replayed to the LLM. See §5.5 design notes.
    created_at      TEXT NOT NULL
);

CREATE INDEX idx_messages_agent ON messages(agent_id, id);

CREATE TABLE api_keys (
    provider TEXT PRIMARY KEY,                 -- 'openrouter' | 'tavily'
    key      TEXT NOT NULL                     -- plaintext (disclosed in README)
);
```

Operations:
- Clear conversation: `DELETE FROM messages WHERE agent_id = ?;`
- Delete agent: `DELETE FROM agents WHERE id = ?;` (cascade removes messages)

Design notes:
- `role` and `content` are their own plain-text columns for parse-free UI reads and to keep options open (e.g. querying/counting by role). They are **denormalized** copies: for assistant/tool rows they duplicate information also present inside `message_json`. This duplication is intentional and accepted — the UI reads the flat columns without parsing JSON, while `message_json` remains the source of truth for replay.
- `message_json` stores the **entire raw provider message object verbatim** (for assistant rows: `content`, `tool_calls`, and any `reasoning`/`reasoning_details` the model returned; for tool rows: the tool result message). Storing the whole message — rather than cherry-picking `tool_calls` into its own column — is what lets the turn loop replay reasoning blocks back to the LLM **unmodified and in original order**, which reasoning-capable models (including the curated Poolside Laguna models) require to continue reasoning across tool-call rounds. Picking out individual fields would silently drop reasoning on the DB round-trip and degrade those models with no error raised. `message_json` is nullable: plain `user` rows can leave it null and rely on `content` alone.
- **Replay rule:** when rebuilding the conversation to send to the provider, assistant/tool rows are reconstructed from `message_json` as-is (no re-serialization, reordering, or field normalization); `user` rows are `{role, content}`. See Appendix A §A.3.2.
- The `idx_messages_agent` index on `(agent_id, id)` keeps history loads and clears fast and gives correct chronological ordering without sorting on `created_at`.

### 5.6 API Key Input
Keys (OpenRouter, Tavily) can be supplied two independent ways, and the app is fully usable through either alone:

- **Config file**, read by the sidecar on startup. A self-contained path for demos and development: drop the keys in a hardcoded config file (e.g. `%APPDATA%/<app>/config.toml`), and the app runs without touching the UI.
- **Settings UI** — a minimal settings view (one text input per provider + save), writing to the `api_keys` table. 
- **Startup precedence (sidecar-side):** on start, the sidecar resolves each key by checking the config file first, then the `api_keys` table, loading whichever it finds into memory. **File wins** when both are present, so dropping a key in the file always takes effect regardless of DB state. 

## 6. Non-Functional Requirements

- **Installability:** Tauri build produces a Windows installer/.exe (NSIS or MSI via `tauri build`). The Python sidecar is bundled (e.g. PyInstaller) so the `.exe` runs standalone; a packaging spike belongs early in the build (see §8).
- **Error handling:** invalid/missing API key, model call failure, tool execution failure, and offline states must all surface a clear, non-crashing message — tool failures via the model's reply (§6.1), the rest via the A.2.7 error envelope.
- **Code quality / maintainability:** agent and tool abstractions should be easy to extend (new tool = register it in one place; new agent = pure data, no code change).
- **Documentation:** README with setup, build instructions, and design decisions and trade-offs

### 6.1 Logging & Debugging
- Python stdlib `logging` in the sidecar (no new dependency).
- **A new log file is created on every sidecar start/restart**, named with a startup timestamp (e.g. `app_YYYYMMDD_HHMMSS.log`) in a known location (e.g. `%APPDATA%/<appname>/logs/`). Timestamped names sort chronologically. **Log directory documented in the README.**
- **No automatic cleanup of old logs** — each run leaves its file behind. Acceptable for a single-user local app; the README notes the user can clear the folder if desired.
- **Logging is hardcoded at DEBUG**
  - Routine lifecycle breadcrumbs (agent created, conversation started, LLM call made, tool ran successfully).
  - **Full LLM traffic:** per request, the model id, message array, and serialized tool definitions (doubles as the tool-isolation audit trail); per response, the completion including tool calls.
  - The four failure modes (bad/missing API key, model call failure, tool execution failure, offline), logged with traceback (`logger.exception` / `exc_info=True`) **plus correlation context** (which agent / tool). Note these are *logging* categories, not all error-envelope kinds: three of them (bad key, model failure, offline) surface to the user as the A.2.7 error envelope, but a **tool execution failure does not abort the turn or produce an envelope** — a recoverable tool failure is returned to the model as a tool-result string, and an unexpected tool crash is caught and logged here (full traceback + which agent/tool) before the model is handed a safe string (Appendix B.5). The crash log is the *only* place a tool crash is distinguished from a recoverable tool failure.
- **README disclosure:** logs are local-only and, because logging runs at DEBUG, may contain conversation content and file data read by tools.


## 7. Decisions Log

| #   | Question                         | Decision                                                                                                                              | Rationale                                                                                                                                                                                                                                       |
| --- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Tool-calling mechanism           | Native OpenRouter/OpenAI-style function calling                                                                                       | Less code than a model-agnostic ReAct loop; acceptable trade-off given 1-week timeline. Requires curating the model list to tool-capable models.                                                                                                |
| 2   | Web Search implementation        | Tavily API (own API key)                                                                                                              | Clean JSON results, LLM-friendly, less implementation risk than HTML scraping — and key persistence is being built anyway for OpenRouter.                                                                                                       |
| 3   | File tool scope                  | Sandboxed to a per-agent, user-chosen workspace folder (set in the agent editor)                                                      | Safety: File Edit can overwrite arbitrary files; unrestricted access is an unnecessary risk for a small added-setup cost. Per-agent (vs. one app-wide root) keeps agents isolated (G2) — a "Work Files" and a "Personal" agent can't reach into each other's folders — for the cost of one extra form field.                                                                     |
| 4   | Streaming vs. non-streaming chat | Non-streaming (request/response, with a "thinking…" indicator)                                                                        | Removes the highest-risk piece of the build (SSE + tool-calling state machine) under a 1-week timeline, at an acceptable UX cost.                                                                                                               |
| 5   | API key storage                  | Plaintext local storage (SQLite), disclosed in README                                                                                 | Simplicity given timeline; explicitly named as a known limitation rather than a hidden gap.                                                                                                                                                     |
| 6   | Model list source                | Static curated list (tool-calling-capable models; free-tier recommended by default, not hard-restricted)                              | Required by decision #1; avoids runtime capability-detection complexity while not artificially blocking non-free models.                                                                                                                        |
| 7   | File Edit semantics              | Full-file overwrite, no backup, no undo in v1                                                                                         | Simplest thing that meets the requirement; destructiveness disclosed in the README.                                                                                                                                                             |
| 8   | Calculator safety                | Safe expression evaluator (not raw `eval`)                                                                                            | Not really a question — a requirement, noted so it isn't missed.                                                                                                                                                                                |
| 9   | Conversation structure           | One conversation per agent (`Agent → Message`); user can clear it to reset                                                            | Matches the assignment's singular "conversation history" at the lowest schema and UI cost; no conversation table, switcher, or titles.                                                                                                          |
| 10  | Model config shape               | Store model config as `{base_url, api_key_provider, model_id}` (same axes as OpenAI-compatible `OPENAI_BASE_URL`/`OPENAI_API_KEY`/`OPENAI_MODEL`, but the key axis names a *provider* resolved at call time, not the literal secret) | Costs nothing over hardcoding OpenRouter (constructor params), and makes a future custom-ID or alternate-provider seam additive. Naming the field `api_key_provider` (a reference, not the secret) keeps it obvious that the key stays single-sourced (Decision #13). No v1 UI impact.                                                                                               |
| 11  | Where the agent loop runs        | Python sidecar process, spawned by Tauri, talking to the React frontend over local REST; sidecar bound to `127.0.0.1` only            | Puts core agent logic in Python (strength) and keeps the Rust surface to spawn/lifecycle; localhost binding prevents other network devices reaching the key-holding, file-tool-bearing local API.                                               |
| 12  | Frontend framework & library     | React + Mantine; three-view UI (agent list, agent editor, chat)                                                                       | More coding-assistant support than SolidJS; Mantine gives batteries-included form/card/modal components with minimal CSS for a low-frontend-familiarity build.                                                                                  |
| 13  | Single persistence layer         | One SQLite DB for agents, messages, and API keys (no separate JSON config store)                                                      | One coherent data layer; FKs + cascade delete enforce integrity that split stores can't. Tool assignments stored as a JSON list in an `agents` column.                                                                                          |
| 14  | Messages table shape             | `role` + plain-text `content` as own (denormalized) columns for UI reads; nullable `message_json` storing the **full raw provider message verbatim** (tool_calls + reasoning/reasoning_details + any provider fields) | Parse-free UI reads and by-role optionality from the flat columns; storing the *entire* message (not just tool_calls) lets the turn loop replay reasoning blocks unmodified/in-order, which reasoning models (e.g. Poolside Laguna) require across tool rounds — cherry-picking fields would silently drop reasoning on the DB round-trip. `role`/`content` duplicating data inside `message_json` is an accepted trade for parse-free rendering. |
| 15  | Tool registry extensibility      | Handler-agnostic tool interface `{name, description, input_schema, handler}`; v1 handlers are all local functions                     | Earns "dynamic tool registration" on the rubric (new tool = one registry entry); as a side effect a future non-local tool source is additive, but nothing is built toward it in v1.                                                             |
| 16  | Logging                          | Python `logging`; new timestamped log file per sidecar start (no cleanup); hardcoded at DEBUG (no toggle); keys never logged          | Serves the error-handling rubric; fresh file per run is easy to reason about per session; DEBUG LLM traffic aids debugging and audits tool isolation; hardcoding DEBUG drops the toggle machinery.                                              |
| 17  | API key input                    | Two independent sources — config file (read at startup) **and** a minimal settings UI — with the config file winning on precedence | The config file is a self-contained demo/dev path; UI keeps the app self-contained for non-file users. Independent paths mean neither source is a single point of failure. File-wins keeps a dropped-in file key authoritative regardless of DB state. |

**Constraint:** delivery timeline is **1 week**. This has already informed several of the decisions above (favoring simpler, lower-risk implementations) and should continue to inform scope trade-offs during architecture and build.

## 8. Suggested Build Phases (high-level, for later scoping)

Backend-heavy phases play to strengths; a small frontend↔sidecar round-trip is pulled early to de-risk the weakest area, and the sidecar-packaging path is spiked before it's on the critical path.

1. **Backend skeleton + packaging spike:** Python sidecar with agent CRUD + SQLite persistence (agents + messages schema), bound to `127.0.0.1`; logging in place. In parallel, a timeboxed spike confirming the Python sidecar bundles into a Tauri `.exe` (PyInstaller + `tauri build`).
2. **OpenRouter integration + first frontend round-trip:** single agent, non-streaming chat, no tools. Stand up a trivial React (Mantine) view that calls the sidecar end-to-end, so integration pain surfaces now, not in Phase 4.
3. **Tool registry + isolation + the 6 tools** (native function-calling loop), with the handler-agnostic registry and per-agent tool serialization.
4. **Frontend build-out:** agent list, agent editor (form + tool checkboxes), chat view with tool-call cards and "Clear conversation."
5. **Packaging:** finalize Tauri build → installable `.exe` (spike from Phase 1 hardened).
6. **Hardening:** error states for all four failure modes, README (incl. disclosed trade-offs: plaintext keys, config-file/env key source with file-wins precedence, destructive File Edit, logs-may-contain-content at DEBUG, no log cleanup), demo video.
