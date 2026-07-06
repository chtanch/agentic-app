import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite config for the Tauri webview bundle.
// Fixed dev port so tauri.conf.json `devUrl` matches; clearScreen off so
// Tauri's logs stay visible during `tauri dev`.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
