import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const root = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  root: path.resolve(root, "frontend"),
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(root, "frontend/src") },
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/files": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: path.resolve(root, "dist"),
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
  },
});
