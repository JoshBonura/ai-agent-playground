// desktop/main.ts
import { app, BrowserWindow } from "electron";
import * as http from "http";
import * as fs from "fs";
import * as path from "path";
import { spawn, ChildProcess } from "child_process";

let mainWin: BrowserWindow | null = null;
let backendProc: ChildProcess | null = null;
const gotLock = app.requestSingleInstanceLock();

function repoRoot() {
  return path.resolve(app.getAppPath(), "..");
}

function readPortsJson(): number | null {
  const roots = [
    repoRoot(),
    path.resolve(__dirname, ".."),
    path.resolve(__dirname, "..", ".."),
    process.env.LOCALMIND_DATA_DIR || "",
    app.getPath("userData"),
  ].filter(Boolean);
  for (const root of roots) {
    try {
      const p = path.join(root, ".runtime", "ports.json");
      const raw = fs.readFileSync(p, "utf-8");
      const j = JSON.parse(raw);
      const n = Number(j.api_port);
      if (Number.isFinite(n)) return n;
    } catch {}
  }
  return null;
}

async function probePort(p: number, ms = 400): Promise<boolean> {
  const url = `http://127.0.0.1:${p}/openapi.json`;
  return new Promise((resolve) => {
    const req = http.get(url, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.setTimeout(ms, () => { req.destroy(); resolve(false); });
    req.on("error", () => resolve(false));
  });
}

function pickPython(): string[] {
  const root = repoRoot();
  const win = process.platform === "win32";
  const candidates = [
    process.env.LOCALMIND_PYTHON || "",
    path.join(root, ".venv", win ? "Scripts\\python.exe" : "bin/python"),
    win ? "py" : "python3",
    "python",
  ].filter(Boolean);
  return candidates;
}

async function startBackend(): Promise<void> {
  if (backendProc) return;
  const root = repoRoot();
  const script = path.join(root, "run_backend.py");
  for (const cmd of pickPython()) {
    try {
      const proc = spawn(cmd, [script], {
        cwd: root,
        env: {
          ...process.env,
          PYTHONUNBUFFERED: "1",
          PYTHONIOENCODING: "utf-8",
          PYTHONUTF8: "1",
          LOCALMIND_DATA_DIR: app.getPath("userData"),
        },
        stdio: ["ignore", "pipe", "pipe"],
      });
      backendProc = proc;
      proc.stdout?.on("data", (b) => console.log("[py]", String(b).trim()));
      proc.stderr?.on("data", (b) => console.warn("[py err]", String(b).trim()));
      proc.on("exit", (code, sig) => console.warn("[py exit]", code, sig));
      return;
    } catch {}
  }
  throw new Error("Could not start Python. Set LOCALMIND_PYTHON or create .venv.");
}

async function waitForHealthy(timeoutMs = 60000): Promise<number> {
  const t0 = Date.now();
  let lastPort: number | null = null;
  while (Date.now() - t0 < timeoutMs) {
    const p = readPortsJson();
    if (p) {
      lastPort = p;
      if (await probePort(p)) return p;
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  if (lastPort && (await probePort(lastPort))) return lastPort;
  throw new Error("Backend did not become healthy in time.");
}

async function waitForHealthyPort(): Promise<number> {
  await startBackend();
  return await waitForHealthy();
}

function sendToFastAPI(port: number, license: string) {
  const data = JSON.stringify({ license });
  const req = http.request(
    {
      host: "127.0.0.1",
      port,
      path: "/license/apply",
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(data)
      }
    },
    (res) => { res.resume(); }
  );
  req.on("error", (err) => console.error("FastAPI error", err));
  req.write(data);
  req.end();
}

function makeDeepLinkHandler(getPort: () => Promise<number>) {
  return async (url: string) => {
    try {
      const u = new URL(url);
      if (u.host === "activate") {
        const lic = u.searchParams.get("license") || "";
        if (lic.startsWith("LM1.")) {
          const port = await getPort();
          sendToFastAPI(port, lic);
        }
      }
    } catch (err) {
      console.error("Deep link error:", err);
    }
  };
}

async function loadWithRetry(win: BrowserWindow, url: string, timeoutMs = 60000): Promise<void> {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      await win.loadURL(url);
      return;
    } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  await win.loadURL("about:blank");
}

app.disableHardwareAcceleration();

if (!gotLock) {
  app.quit();
} else {
  const getPortOnce = (() => {
    let cached: number | null = null;
    return async () => {
      if (cached) return cached;
      cached = await waitForHealthyPort();
      return cached;
    };
  })();
  const handleDeepLink = makeDeepLinkHandler(getPortOnce);

  app.on("second-instance", async (_evt, argv) => {
    const deeplink = argv.find((a) => typeof a === "string" && a.startsWith("localmind://"));
    if (deeplink) await handleDeepLink(deeplink);
    if (mainWin) { if (mainWin.isMinimized()) mainWin.restore(); mainWin.focus(); }
  });

  app.whenReady().then(async () => {
    mainWin = new BrowserWindow({ width: 1200, height: 800 });
    mainWin.webContents.openDevTools({ mode: "detach" });
    mainWin.webContents.on("did-fail-load", (_e, code, desc, url) => {
      console.error("[renderer did-fail-load]", code, desc, url);
    });
    mainWin.webContents.on("console-message", (_e, level, message) => {
      console.log("[renderer]", level, message);
    });
    app.setAsDefaultProtocolClient("localmind");
    app.on("open-url", async (event, url) => {
      event.preventDefault();
      await handleDeepLink(url);
    });
    const port = await getPortOnce();
    const url = `http://127.0.0.1:${port}/`;
    await loadWithRetry(mainWin, url, 60000).catch(async () => {
      try { await mainWin!.loadURL(`${url}docs`); } catch { if (mainWin) mainWin.loadURL("about:blank"); }
    });
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });

  app.on("will-quit", () => {
    if (backendProc) {
      try { backendProc.kill(); } catch {}
    }
  });
}
