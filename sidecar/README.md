# agent_backend — Python sidecar

The Flask sidecar that holds all agent/tool logic (PRD §5.0). Binds
`127.0.0.1:8765` only. The Tauri shell spawns it; the frontend talks to it over
the REST contract in Appendix A §A.2.

## Requirements
- [uv](https://docs.astral.sh/uv/) (manages Python — pinned to 3.12 via `.python-version`)

## Develop
```powershell
uv sync                 # create .venv, install deps
uv run pytest           # run the test suite
uv run python -m agent_backend   # run the sidecar (Ctrl+C to stop)
```
Health check: `GET http://127.0.0.1:8765/health` → `{"ok": true}`.

## Data locations (Windows)
Everything is stored under `%APPDATA%\agentic-app\`:
- `app.db` — SQLite (agents, messages, api_keys)
- `logs\app_YYYYMMDD_HHMMSS.log` — one DEBUG log per run, no auto-cleanup
- `config.toml` — optional API-key file (read at startup; not required)

Override the whole dir with the `AGENT_BACKEND_DATA_DIR` env var (used by tests).

## Package into a standalone exe (PyInstaller)
```powershell
uv run pyinstaller --noconfirm --onefile --name agent-backend `
  --paths src --collect-data agent_backend `
  --distpath dist --workpath build --specpath build `
  packaging/sidecar_entry.py
```
Produces `dist/agent-backend.exe`, which runs with no Python/uv installed. This
is the artifact the Tauri shell bundles as its sidecar binary (Phase 5).

## Phase 1 scope (implemented)
- `GET /health`, `GET /models` (A.2.8, `{id,label}` only)
- Agent CRUD: `GET/POST /agents`, `GET/PUT/DELETE /agents/{id}` (A.2.2)
- SQLite schema (§5.5) with FK cascade; uniform error envelope (A.2.7)

Chat / turn loop (A.3), tools (Appendix B), and keys (A.2.6) land in later phases.
