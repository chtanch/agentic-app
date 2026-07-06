import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

// Placeholder view for the Phase 1 packaging spike. It proves the full chain
// works: Tauri spawned the Python sidecar, and it's listening on 127.0.0.1:8765.
// The real React + Mantine three-view UI is built in Phase 2 / Phase 4.
export default function App() {
  const [reachable, setReachable] = useState(null);

  useEffect(() => {
    let active = true;
    const check = async () => {
      try {
        const ok = await invoke("sidecar_reachable");
        if (active) setReachable(ok);
      } catch {
        if (active) setReachable(false);
      }
    };
    check();
    const id = setInterval(check, 1000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const status =
    reachable === null
      ? "checking…"
      : reachable
        ? "✅ reachable"
        : "❌ not reachable";

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "2rem", lineHeight: 1.5 }}>
      <h1>Agentic Desktop</h1>
      <p style={{ fontSize: "1.1rem" }}>
        Python sidecar on <code>127.0.0.1:8765</code>: <strong>{status}</strong>
      </p>
      <p style={{ color: "#888" }}>
        Phase 1 packaging spike — the Tauri shell spawns the bundled sidecar on
        launch and terminates it on exit. The real UI arrives in later phases.
      </p>
    </main>
  );
}
