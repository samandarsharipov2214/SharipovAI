import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

function safeProxyTarget(value: string | undefined): string {
  const candidate = value?.trim() || "http://127.0.0.1:8000";
  const parsed = new URL(candidate);

  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error("DEV_API_PROXY_TARGET must use http or https");
  }

  return parsed.origin;
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  return {
    plugins: [react(), tailwindcss()],
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": {
          target: safeProxyTarget(env.DEV_API_PROXY_TARGET),
          changeOrigin: false,
          secure: true,
        },
      },
    },
    preview: {
      host: "127.0.0.1",
      port: 4173,
      strictPort: true,
    },
    build: {
      target: "es2022",
      sourcemap: false,
      reportCompressedSize: true,
    },
  };
});
