# Agentic Desktop

A local-first Windows desktop app for building and chatting with your own AI
**agents**. Each agent is a named configuration — a system prompt, a model, and
a set of tools it's allowed to use — that you talk to in a simple chat window.
Agents can do math, look up the current date/time, search the web, and read,
search, and edit files inside a folder you choose.

Everything runs on your machine: the app is a small desktop shell around a local
backend bound to `127.0.0.1` only. Your conversations, agents, and API keys live
in a local database on your PC; nothing is sent anywhere except the model
provider (OpenRouter) and, if you enable web search, the search provider
(Tavily).

> **Build target:** this is a v1 delivered under a one-week timeline. Several
> deliberate simplicity/safety trade-offs are documented in
> [Design decisions & trade-offs](DESIGN_DECISIONS) — please
> read that section before relying on the app.

---

## Install & run

1. Run the installer, `Agentic Desktop_0.1.0_x64-setup.exe`.
   - It installs **per-user** under `%LOCALAPPDATA%\Agentic Desktop\` — no admin
     rights and **no UAC prompt**.
   - The app is **unsigned**, so Windows SmartScreen may warn "unknown
     publisher." Choose **More info → Run anyway**. (Code signing is out of
     scope for v1.)
2. Launch **Agentic Desktop** from the Start menu.
3. On first launch the window shows **"Starting the local backend…"** for a few
   seconds while the bundled backend starts and binds its port (Windows Defender
   scans the new executable on first run, which adds a one-time delay). It
   clears automatically once the backend is ready.

To build from source instead, see **[DEVELOPMENT.md](DEVELOPMENT.md)**.

---

## Getting started

### 1. Add your API keys

Open **⚙ Settings** (bottom of the agent list) and paste your keys:

| Key | Needed for | Get one at |
| --- | --- | --- |
| **OpenRouter** | All chat (required) | <https://openrouter.ai/keys> |
| **Tavily** | The Web Search tool (optional) | <https://tavily.com> |

Settings shows **presence only** ("set" / "unset") — key values are never
displayed back to you once saved.

The curated model list includes free-tier options, so you can try the app on a
free OpenRouter key. (Free models are rate-limited by the provider; see
[Failure states](#failure-states).)

### 2. Create an agent

Click **New**, then fill in:

- **Name** — how it appears in the sidebar.
- **System prompt** — the agent's standing instructions (optional).
- **Model** — pick from the curated, tool-calling-capable list.
- **Tools** — check any of the six the agent may use (see below).
- **Workspace folder** — a folder the file tools are sandboxed to. **Required if
  you enable any file tool**; the file tools can only see inside this folder.

Click **Save** and the agent appears in the sidebar. Use the ✎ / ✕ icons to edit
or delete it.

### 3. The six tools

| Tool | What it does |
| --- | --- |
| **Calculator** | Evaluates arithmetic expressions (safe evaluator, not raw `eval`). |
| **Current date/time** | Returns the current date/time, optionally for a named time zone. |
| **Web search** | Searches the web via Tavily (needs the Tavily key). |
| **File search** | Finds files by name/pattern inside the workspace folder. |
| **File read** | Reads a file inside the workspace folder. |
| **File edit** | **Overwrites** a file inside the workspace folder (see the warning under trade-offs). |

Each agent only ever sees the tools you assigned it — agents are isolated from
each other, and the file tools can never reach outside that agent's workspace
folder.

### 4. Chat

Select an agent and type in the box (**Enter** to send, **Shift+Enter** for a
newline). Chat is **non-streaming**: the whole turn — the agent's reply plus any
tool calls it made — arrives at once, after a **"thinking…"** indicator.

When an agent uses a tool, a collapsible **tool-call card** appears in the
transcript showing the tool name, the arguments it used, and the result (with an
**ok** / **error** badge). Click a card to expand it.

**Clear conversation** wipes that agent's history so you can start fresh. Each
agent has exactly one ongoing conversation.

---

## Failure states

The app is designed to **never crash on an error** — every failure surfaces as a
clear, readable message. There are four failure modes:

| What you'll see | What it means | What to do |
| --- | --- | --- |
| **API key problem** | No OpenRouter key is set, or the provider rejected it. | Add/fix the key in **⚙ Settings** (or `config.toml`). |
| **Model error** | The model provider returned an error, an empty/invalid response, or the agent hit the tool-round limit. | Retry; if it persists, try a different model. Free-tier models are rate-limited and surface here as HTTP 429. |
| **Offline** | The backend couldn't reach the model provider (no internet / DNS / timeout), or the local backend itself isn't reachable. | Check your internet connection. |
| **Tool error** | A tool call failed (bad arguments, a file outside the workspace, a network hiccup in search, etc.). | Shown **inside the tool-call card** as a red **error** badge — it does **not** stop the turn. The agent sees the error and can recover or explain it. |

Your typed message is preserved on error, so you can just press **Send** again
without retyping.

---

## Data & log locations

Everything the app stores lives under **`%APPDATA%\agentic-app\`**:

| Path | What it is |
| --- | --- |
| `app.db` | SQLite database — agents, conversations, and API keys. |
| `logs\app_YYYYMMDD_HHMMSS.log` | One DEBUG log per app start; **no auto-cleanup**. |
| `config.toml` | Optional API-key file (see trade-offs above). Not required. |

To reset the app completely, close it and delete the `%APPDATA%\agentic-app\`
folder. To clear old logs, delete files in its `logs\` subfolder.

---

## For developers

Architecture, build steps, and build gotchas are in
**[DEVELOPMENT.md](DEVELOPMENT.md)**. In one line: a **Tauri (Rust) shell**
spawns a bundled **Python Flask sidecar** and serves a **React + Mantine**
webview that talks to the sidecar over local REST at `http://127.0.0.1:8765`.
The full product spec lives in `docs/`.
