// Prevents an extra console window on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{SocketAddr, TcpStream};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{Manager, RunEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Holds the spawned sidecar so we can terminate it when the app exits.
struct SidecarChild(Mutex<Option<CommandChild>>);

/// Lightweight liveness probe used by the frontend placeholder: is the sidecar
/// listening on its fixed port? A TCP connect is enough to prove Tauri spawned
/// it; real HTTP calls from the webview come in Phase 2.
#[tauri::command]
fn sidecar_reachable() -> bool {
    let addr: SocketAddr = "127.0.0.1:8765".parse().expect("valid addr");
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(SidecarChild(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![sidecar_reachable])
        .setup(|app| {
            // externalBin "binaries/agent-backend" -> sidecar("agent-backend").
            let sidecar = app.shell().sidecar("agent-backend")?;
            let (mut rx, child) = sidecar.spawn()?;
            app.state::<SidecarChild>()
                .0
                .lock()
                .unwrap()
                .replace(child);

            // Drain the sidecar's stdout/stderr into our own stderr so its
            // DEBUG log surfaces during `tauri dev`.
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(bytes) | CommandEvent::Stderr(bytes) => {
                            eprint!("[sidecar] {}", String::from_utf8_lossy(&bytes));
                        }
                        _ => {}
                    }
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            // Terminate the sidecar on app exit (spawn/lifecycle ownership,
            // PRD §5.0 / Decision #11).
            if let RunEvent::Exit = event {
                if let Some(child) = app_handle.state::<SidecarChild>().0.lock().unwrap().take() {
                    kill_sidecar_tree(&child);
                    let _ = child.kill();
                }
            }
        });
}

/// Kill the sidecar *and its children*. PyInstaller one-file spawns a bootloader
/// process that extracts and runs the real Python process as a child; killing
/// only the direct child (`CommandChild::kill`) orphans that grandchild, which
/// keeps holding port 8765. A tree kill by PID takes the whole thing down.
#[cfg(windows)]
fn kill_sidecar_tree(child: &CommandChild) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    let _ = std::process::Command::new("taskkill")
        .args(["/F", "/T", "/PID", &child.pid().to_string()])
        .creation_flags(CREATE_NO_WINDOW)
        .status();
}

#[cfg(not(windows))]
fn kill_sidecar_tree(_child: &CommandChild) {}
