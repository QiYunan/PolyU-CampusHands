import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";
import { parseAdditionalServerAllowedHosts } from "./src/viteAllowedHosts";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS");
  return {
    plugins: [react()],
    server: {
      strictPort: true,
      allowedHosts: parseAdditionalServerAllowedHosts(
        env.__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS,
      ),
      proxy: {
        "/api": "http://127.0.0.1:8000",
        "/ws": { target: "ws://127.0.0.1:8000", ws: true },
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test-setup.ts"],
    },
  };
});
