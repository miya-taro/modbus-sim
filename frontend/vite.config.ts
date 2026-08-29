import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 開発時はバックエンド(既定 127.0.0.1:8000)へプロキシ。
// 本番は同一オリジン（バックエンドが dist を配信）なので相対パスで動く。
const BACKEND = process.env.MODBUS_BACKEND ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/ws": { target: BACKEND, ws: true, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
