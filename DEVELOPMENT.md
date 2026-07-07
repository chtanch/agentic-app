# Development — build & run

Developer notes for building and running the Windows Agentic Desktop App. This
covers the three parts of the stack and, importantly, the **build gotchas** that
are easy to trip over. For end-user setup, usage, and the disclosed
design-decisions / trade-offs, see **[README.md](README.md)** — this file is the
dev-facing counterpart.

## Architecture in one line
A **Tauri (Rust) shell** spawns a **Python Flask sidecar** (bundled as a
PyInstaller exe) and serves a **React + Mantine** webview that talks to the
sidecar over local REST at `http://127.0.0.1:8765`. See `docs/` for the full
spec.

```
src-tauri/   Rust shell — window + sidecar spawn/lifecycle only
sidecar/     Python backend (uv, src layout, package `agent_backend`)
frontend/    React + Mantine webview (Vite)
docs/        PRD + Appendix A (architecture/REST) + Appendix B (tools)
```

## Prerequisites (installed once, system-wide)
| Tool | Version used | Notes |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | 0.11+ | Manages Python; pins **3.12** via `sidecar/.python-version`. No separate Python install needed. |
| Node.js + npm | 24 / 11 | For the frontend and the Tauri CLI. |
| Rust (cargo, rustc) | 1.96 (min 1.77) | Compiles the Tauri shell. |
| [VS C++ Build Tools](https://visualstudio.microsoft.com/downloads/) + Windows SDK | VS 2022/2026, Win11 SDK (10.0.26100) | Rust's MSVC toolchain (`x86_64-pc-windows-msvc`) links the shell through these. Install the "Desktop development with C++" workload (or Build Tools for VS). |
| WebView2 Runtime | any current | Preinstalled on Windows 11. |

The **Tauri CLI** is a project dev-dependency (not global) — installed by the
root `npm install` below and invoked via `npm run tauri`.

## One-time setup
From the repo root:
```powershell
npm install                    # root: Tauri CLI
npm --prefix frontend install  # frontend: React + Vite
cd sidecar; uv sync; cd ..     # sidecar: Flask + pydantic (+ dev: pytest, pyinstaller)
```

## Run during development

### Backend only (fast iteration on the API)
```powershell
cd sidecar
uv run python -m agent_backend   # serves http://127.0.0.1:8765 ; Ctrl+C to stop
uv run pytest                    # run the test suite
```
Health check: `curl http://127.0.0.1:8765/health` → `{"ok": true}`.

### Frontend in the browser (fastest UI loop, no Rust build)
For iterating on the React UI against a running sidecar without compiling the
shell:
```powershell
cd sidecar; uv run python -m agent_backend   # terminal 1: sidecar
npm --prefix frontend run dev                 # terminal 2: Vite at http://localhost:5173
```
Open `http://localhost:5173` in a browser. The sidecar's CORS allowlist permits
`localhost`/`127.0.0.1` (any port) and the Tauri webview origins, so the same
`fetch`-based API client works in a plain browser and inside the Tauri window.

### Full app, live (hot-reload webview + Rust shell)
```powershell
npm run tauri -- dev
```
This runs Vite, compiles the shell in debug, opens the window, and spawns the
sidecar. `tauri dev` still spawns the **release** sidecar binary from
`src-tauri/binaries/` (see next section), so build that first if it's missing.

## Build the installable app

### Step 1 — build the sidecar exe and stage it (REQUIRED)
`src-tauri/binaries/*.exe` is a build artifact and is **git-ignored**, so it must
exist before `tauri build`. Rebuild it whenever the Python changes:
```powershell
cd sidecar
uv run pyinstaller --noconfirm --onefile --name agent-backend `
  --paths src --collect-data agent_backend `
  --collect-data tzdata --hidden-import tzdata `
  --distpath dist --workpath build --specpath build `
  packaging/sidecar_entry.py
```

```powershell
New-Item -ItemType Directory -Path ..\src-tauri\binaries -Force | Out-Null
# Stage it with the Rust target-triple suffix (get yours: `rustc --print host-tuple`)
Copy-Item dist\agent-backend.exe ..\src-tauri\binaries\agent-backend-x86_64-pc-windows-msvc.exe -Force
cd ..
```

### Step 2 — build the Tauri app + installer
```powershell
npm run tauri -- build
```
Outputs:
- App exe: `src-tauri\target\release\agentic-desktop.exe`
- Installer: `src-tauri\target\release\bundle\nsis\Agentic Desktop_0.1.0_x64-setup.exe`

The NSIS installer is configured `installMode: "currentUser"` (`bundle.windows.nsis`
in `tauri.conf.json`), so it installs per-user under
`%LOCALAPPDATA%\Agentic Desktop\` with **no UAC / admin prompt** — appropriate
for an unsigned local-first app. Bundle metadata (publisher, copyright,
description) is set in `bundle.*` and surfaces in the installer and the exe's
file properties.

## ⚠️ Gotchas (read before debugging a broken build)

1. **Cold-start delay (~5–8 s) on first launch after a build.** Windows Defender
   scans the new exe and PyInstaller one-file self-extracts, so the sidecar
   takes a few seconds to bind 8765. The window may briefly show
   **❌ not reachable**, then flip to **✅ reachable** (it polls every second).

2. **Stage the sidecar binary first** (Build step 1). Missing it makes
   `tauri build` fail with *"binary not found for target."*

3. **One instance at a time.** Port 8765 for sidecar server is hardcoded; if
   `agent-backend.exe` is leftover from a prior run, this prevents a new sidecar from binding.
   Kill the stray process first.

4. **Graceful close cleans up; force-kill can orphan.** Closing the window
   (X button) fires the shell's exit handler, which tree-kills the sidecar.
   *End Task* in Task Manager force-terminates the shell so that handler never
   runs — the sidecar can linger. (`--onefile` bootloader + extracted child is
   why two `agent-backend.exe` processes appear while running; that's normal.)

5. **Antivirus warning.** The exe/installer are unsigned, so Antivirus programs might prevent the app from running.

## Models
OpenRouter models can be added to the predefined list by updating [models.json](src/agent_backend/data/models.json) and restarting the backend.
The only required fields are "id" and "label".

## Data & log locations (Windows)
Everything is under `%APPDATA%\agentic-app\`:
- `app.db` — SQLite (agents, messages, api_keys)
- `logs\app_YYYYMMDD_HHMMSS.log` — one DEBUG log per run, no auto-cleanup
- `config.toml` — optional API-key file, read on each key lookup (not required).
  Flat keys, config file **wins** over the `api_keys` table (PRD §5.6):
  ```toml
  openrouter_key = "sk-or-v1-..."
  tavily_key     = "tvly-..."
  ```

Tests and throwaway runs can redirect all of this by setting the
`AGENT_BACKEND_DATA_DIR` environment variable.
