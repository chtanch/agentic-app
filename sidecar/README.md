# agent_backend — Python sidecar

The Flask sidecar that holds all agent/tool logic. Binds
`127.0.0.1:8765`. The Tauri shell spawns it; the frontend talks to it over
the REST contract in [Appendix A](../docs/PRD-Appendix-A-Architecture-and-Interfaces.md) §A.2.

## Requirements
- [uv](https://docs.astral.sh/uv/) (manages Python — pinned to 3.12 via `.python-version`)

## Develop
```powershell
uv sync                 # create .venv, install deps
uv run pytest           # run the test suite
uv run python -m agent_backend   # run the sidecar (Ctrl+C to stop)
```
Health check: `curl http://127.0.0.1:8765/health` → `{"ok": true}`.

## Models
OpenRouter models can be added to the predefined list by updating [models.json](src/agent_backend/data/models.json).
The only required fields are "id" and "label".

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
