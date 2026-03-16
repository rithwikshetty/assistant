import { defineConfig, type ViteDevServer } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";
import httpProxy from "http-proxy";
import type { IncomingMessage, ServerResponse } from "node:http";

const runtimeStatePath = path.resolve(__dirname, "..", ".tmp", "dev-runtime.json");
const alwaysProxyPrefixes = [
  "/admin",
  "/auth",
  "/conversations",
  "/feedback",
  "/files",
  "/preferences",
  "/redaction-list",
  "/skills",
  "/staged-files",
  "/tasks",
  "/users",
];

function readBackendProxyTarget(): string | null {
  try {
    const raw = fs.readFileSync(runtimeStatePath, "utf-8");
    const parsed = JSON.parse(raw);
    const backend = parsed?.services?.backend;
    if (!backend || typeof backend.url !== "string" || !backend.url.trim()) {
      return null;
    }
    return backend.url.replace(/\/+$/, "");
  } catch {
    return null;
  }
}

function writeFrontendRuntimePort(port: number): void {
  try {
    const existing = fs.existsSync(runtimeStatePath)
      ? JSON.parse(fs.readFileSync(runtimeStatePath, "utf-8"))
      : {};
    const next = {
      ...existing,
      services: {
        ...(existing?.services || {}),
        frontend: {
          port,
          url: `http://localhost:${port}`,
        },
      },
    };
    fs.mkdirSync(path.dirname(runtimeStatePath), { recursive: true });
    fs.writeFileSync(runtimeStatePath, `${JSON.stringify(next, null, 2)}\n`, "utf-8");
  } catch {
    // Dev runtime state is best-effort only.
  }
}

function requestAcceptsHtml(req: IncomingMessage): boolean {
  return req.method === "GET" && String(req.headers.accept || "").includes("text/html");
}

function shouldProxyHttpRequest(req: IncomingMessage): boolean {
  const requestUrl = req.url || "/";

  if (alwaysProxyPrefixes.some((prefix) => requestUrl === prefix || requestUrl.startsWith(`${prefix}/`))) {
    return true;
  }

  if (requestUrl === "/projects" || requestUrl.startsWith("/projects/")) {
    return req.method !== "GET" || !requestAcceptsHtml(req);
  }

  if (requestUrl === "/share" || requestUrl.startsWith("/share/")) {
    return req.method !== "GET" || !requestAcceptsHtml(req);
  }

  return false;
}

function shouldProxyWebSocketRequest(req: IncomingMessage): boolean {
  const requestUrl = req.url || "/";
  return requestUrl === "/conversations/ws" || requestUrl.startsWith("/conversations/ws?");
}

function writeProxyUnavailable(res: ServerResponse): void {
  if (res.headersSent) return;
  res.statusCode = 503;
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify({
    detail: "Backend is not available yet. Start `backend/scripts/run_dev.sh` in another terminal.",
  }));
}

function createDynamicBackendProxy() {
  return {
    name: "assistant-dev-backend-proxy",
    apply: "serve" as const,
    configureServer(server: ViteDevServer) {
      const proxy = httpProxy.createProxyServer({
        changeOrigin: true,
        ws: true,
        xfwd: true,
      });

      server.httpServer?.once("listening", () => {
        const address = server.httpServer?.address();
        if (address && typeof address === "object" && typeof address.port === "number") {
          writeFrontendRuntimePort(address.port);
        }
      });

      proxy.on("error", (_error, _req, res) => {
        if (res && "writableEnded" in res && !res.writableEnded) {
          writeProxyUnavailable(res as ServerResponse);
        }
      });

      server.middlewares.use((req, res, next) => {
        if (!shouldProxyHttpRequest(req)) {
          next();
          return;
        }

        const target = readBackendProxyTarget();
        if (!target) {
          writeProxyUnavailable(res);
          return;
        }

        proxy.web(req, res, { target });
      });

      server.httpServer?.on("upgrade", (req, socket, head) => {
        if (!shouldProxyWebSocketRequest(req)) {
          return;
        }

        const target = readBackendProxyTarget();
        if (!target) {
          socket.destroy();
          return;
        }

        proxy.ws(req, socket, head, { target });
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), createDynamicBackendProxy()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
  build: {
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;

          // Animation
          if (id.includes("framer-motion")) return "vendor-motion";

          // Drag and drop
          if (id.includes("@dnd-kit")) return "vendor-dnd";

          // Charts (recharts + d3)
          if (id.includes("recharts") || id.includes("/d3-")) return "vendor-charts";

          // Markdown rendering
          if (
            id.includes("react-markdown") ||
            id.includes("remark-gfm") ||
            id.includes("mdast") ||
            id.includes("micromark") ||
            id.includes("unist") ||
            id.includes("hast")
          ) {
            return "vendor-markdown";
          }

          // React core
          if (
            id.includes("/react/") ||
            id.includes("/react-dom/") ||
            id.includes("scheduler")
          ) {
            return "vendor-react";
          }

          // Radix UI primitives
          if (id.includes("@radix-ui")) return "vendor-radix";

          // Icons
          if (id.includes("@phosphor-icons")) return "vendor-icons";

          // React Router
          if (id.includes("react-router")) return "vendor-router";

          // React Query
          if (id.includes("@tanstack/react-query")) return "vendor-query";

          return undefined;
        },
      },
    },
  },
  server: {
    host: "0.0.0.0",
  },
  preview: {
    host: "0.0.0.0",
  },
});
