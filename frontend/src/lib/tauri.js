// Tauri-only helpers. The app runs in two environments: the packaged Tauri
// webview (where these native APIs exist) and the plain vite dev browser used
// for development/verification (where they don't). Everything here degrades
// gracefully so the dev browser stays fully usable — the workspace path can
// always be typed by hand; the native picker is a convenience on top.

/** True when running inside the Tauri webview (v2 sets `window.isTauri`). */
export function isTauri() {
  return typeof window !== "undefined" &&
    (window.isTauri === true || "__TAURI_INTERNALS__" in window);
}

/**
 * Open the OS native folder picker and return the chosen absolute path, or
 * null if cancelled / unavailable. Only works inside Tauri (needs the dialog
 * plugin); returns null everywhere else so callers fall back to text entry.
 */
export async function pickDirectory(defaultPath) {
  if (!isTauri()) return null;
  try {
    // Dynamic import so the dev-browser bundle never evaluates the plugin
    // (its IPC calls would throw outside Tauri).
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({
      directory: true,
      multiple: false,
      defaultPath: defaultPath || undefined,
    });
    return typeof selected === "string" ? selected : null;
  } catch {
    return null;
  }
}
