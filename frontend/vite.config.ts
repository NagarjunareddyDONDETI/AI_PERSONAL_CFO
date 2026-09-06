import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy /api to the FastAPI backend during development so the frontend can
// talk to the backend without CORS friction.
//
// Two deliberate choices below:
//
// 1. `host: true` listens on every interface, both IPv4 and IPv6. Vite's default
//    ("localhost") bound IPv6-only on this machine, so http://127.0.0.1:5173
//    refused connections while http://localhost:5173 worked — whether the app
//    loaded came down to how the client resolved "localhost".
//    NOTE: this also exposes the dev server on your local network. It is a dev
//    server for an app that handles bank statements, so on an untrusted network
//    change this to "127.0.0.1".
//
// 2. The proxy target is 127.0.0.1, not localhost. uvicorn binds IPv4 only, so
//    if Node resolved "localhost" to ::1 every /api call would fail with
//    ECONNREFUSED and the whole UI would look like the backend was down.
const API_TARGET = "http://127.0.0.1:8000";

const apiProxy = {
  "/api": {
    target: API_TARGET,
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api/, ""),
  },
};

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: apiProxy,
  },
  // `vite preview` serves the prebuilt dist/ (much lighter than the dev
  // server). Mirror the /api proxy so the static build can reach the backend.
  preview: {
    port: 5173,
    host: true,
    proxy: apiProxy,
  },
});
