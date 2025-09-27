// vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8001", changeOrigin: true },
    },
  },
  build: {
    minify: true,              // use esbuild (default)
    sourcemap: false,
    chunkSizeWarningLimit: 1000,
  },
  esbuild: {
    drop: ["console", "debugger"], // <-- equivalent to the Terser compress flags
  },
});
