import fs from "node:fs";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const frontendRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(frontendRoot, "..");
const runtimePath = path.join(repoRoot, ".tmp", "dev-runtime.json");

try {
  const runtime = JSON.parse(fs.readFileSync(runtimePath, "utf-8"));
  const backendUrl = String(runtime?.services?.backend?.url || "");
  if (backendUrl) {
    process.stdout.write(`Backend proxy target: ${backendUrl}\n`);
  }
} catch {
  // Backend can start later; the Vite proxy reads the runtime file per request.
}

const viteBinary = path.join(frontendRoot, "node_modules", ".bin", process.platform === "win32" ? "vite.cmd" : "vite");
const child = spawn(
  viteBinary,
  ["--host", "0.0.0.0", "--port", "3000"],
  {
    cwd: frontendRoot,
    stdio: "inherit",
    env: process.env,
  },
);

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});
