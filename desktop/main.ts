// desktop/main.ts
import { app, BrowserWindow, Menu, shell } from "electron";
import * as http from "http";
import * as fs from "fs";
import * as path from "path";
import { spawn, spawnSync, ChildProcess } from "child_process";
let mainWin: BrowserWindow | null = null;
let backendProc: ChildProcess | null = null;
const gotLock = app.requestSingleInstanceLock();
import * as crypto from "crypto";

const MAIN_BUILD_MARK = "main.ts v3 – serialized backend start";
console.log("[MAIN MARK]", MAIN_BUILD_MARK, "pid=", process.pid);

/* -----------------------------------------------------------
   Paths & helpers
----------------------------------------------------------- */

function repoRoot() {
  // when packaged, app.getAppPath() points inside asar; ../ is app root
  return path.resolve(app.getAppPath(), "..");
}

function osToken(): "windows" | "linux" | "mac" {
  if (process.platform === "win32") return "windows";
  if (process.platform === "darwin") return "mac";
  return "linux";
}

function ext(name: string) {
  return process.platform === "win32" ? `${name}.exe` : name;
}

function wheelsRoot(): string {
  return app.isPackaged
    ? path.join(process.resourcesPath, "runtime", "wheels")
    : path.join(repoRoot(), "ext", "wheels");
}

function requirementsRoot(): string {
  return app.isPackaged
    ? path.join(process.resourcesPath, "runtime", "requirements")
    : path.join(repoRoot(), "ext", "requirements");
}

function provisionerPath(): string {
  return path.join(process.resourcesPath, ext("localmind-provisioner"));
}

function backendBinaryPath(): string {
  const single = path.join(process.resourcesPath, ext("localmind-backend")); // onefile
  const dirExe = path.join(
    process.resourcesPath,
    "localmind-backend",
    ext("localmind-backend")
  ); // onedir
  return fs.existsSync(dirExe) ? dirExe : single;
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

function provisionedPythonPath(): string | null {
  const user = app.getPath("userData");
  const osTok = osToken();
  const backends = wantedBackends(); // e.g. ["cpu","cuda"] on Windows
  for (const b of backends) {
    const py =
      process.platform === "win32"
        ? path.join(user, ".runtime", "venvs", osTok, b, ".venv", "Scripts", "python.exe")
        : path.join(user, ".runtime", "venvs", osTok, b, ".venv", "bin", "python");
    if (fs.existsSync(py)) return py;
  }
  return null;
}

function backendCommand(): { cmd: string; args: string[] } {
  if (app.isPackaged) {
    // ✅ Use the frozen backend — no Python/venv/provision needed for base
    return { cmd: backendBinaryPath(), args: [] };
  } else {
    // dev mode: run with your repo Python
    const script = path.join(repoRoot(), "run_backend.py");
    const py = pickPython()[0];
    if (!py) throw new Error("No Python found for dev mode. Set LOCALMIND_PYTHON.");
    return { cmd: py, args: [script] };
  }
}

// NOTE: tighter search for ports.json: packaged -> userData only; dev -> broader
function readPortsJson(): number | null {
  const roots = app.isPackaged
    ? [app.getPath("userData")]
    : [
        repoRoot(),
        path.resolve(__dirname, ".."),
        path.resolve(__dirname, "..", ".."),
        process.env.LOCALMIND_DATA_DIR || "",
        app.getPath("userData"),
      ];
  for (const root of roots.filter(Boolean)) {
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

async function probePort(p: number, ms = 500): Promise<boolean> {
  const url = `http://127.0.0.1:${p}/openapi.json`;
  return new Promise((resolve) => {
    const req = http.get(url, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.setTimeout(ms, () => {
      req.destroy();
      resolve(false);
    });
    req.on("error", () => resolve(false));
  });
}

/* 🌟 NEW: verify it’s actually *our* backend by hitting /info */
async function probeOwnBackend(p: number, ms = 500): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get(`http://127.0.0.1:${p}/info`, (res) => {
      let raw = "";
      res.setEncoding("utf8");
      res.on("data", (c) => (raw += c));
      res.on("end", () => {
        try {
          const j = JSON.parse(raw);
          resolve(!!j && typeof j.port === "number" && typeof j.ip === "string");
        } catch {
          resolve(false);
        }
      });
    });
    req.setTimeout(ms, () => { req.destroy(); resolve(false); });
    req.on("error", () => resolve(false));
  });
}

/* -----------------------------------------------------------
   First-run provisioning (offline)
----------------------------------------------------------- */

function wantedBackends(): string[] {
  if (process.platform === "win32") return ["cpu", "cuda"]; // no vulkan
  if (process.platform === "darwin") return ["cpu", "metal"];
  return ["cpu", "cuda", "rocm"]; // linux (adjust as your wheels allow)
}

// Stamp lives at: <userData>/.runtime/venvs/<os>/<backend>/.runtime.json
function stampPathFor(backend: string): string {
  return path.join(
    app.getPath("userData"),
    ".runtime",
    "venvs",
    osToken(),
    backend,
    ".runtime.json"
  );
}

function needsProvision(): boolean {
  const missing = wantedBackends().filter((b) => !fs.existsSync(stampPathFor(b)));
  if (missing.length) {
    console.log("[provision] missing stamps for:", missing.join(", "));
  } else {
    console.log("[provision] all stamps found");
  }
  return missing.length > 0;
}

function runProvisionerOnce(): void {
  const prov = provisionerPath();
  if (!fs.existsSync(prov)) {
    // In dev, you may not have a packaged provisioner; skip quietly
    console.log("[provision] provisioner not found (dev mode?):", prov);
    return;
  }

  const env = {
    ...process.env,
    PYTHONUNBUFFERED: "1",
    PYTHONIOENCODING: "utf-8",
    PYTHONUTF8: "1",

    // where FastAPI will read/write ports.json etc.
    LOCALMIND_DATA_DIR: app.getPath("userData"),

    // point FastAPI to the packaged frontend
    LM_FRONTEND_DIST: app.isPackaged
      ? path.join(process.resourcesPath, "frontend", "dist")
      : path.join(repoRoot(), "frontend", "dist"),

    // offline installer inputs (used by provisioner and ext.common)
    LM_WHEELS_ROOT: wheelsRoot(),
    LM_REQUIREMENTS_ROOT: requirementsRoot(),

    // ✅ tell provisioner which backends to create venvs for
    LM_PROVISION_BACKENDS: wantedBackends().join(","),

    // logs
    LOG_RUNTIME_DEBUG: process.env.LOG_RUNTIME_DEBUG || "1",
    
    LM_WORKER_LOG_FILE:
      process.env.LM_WORKER_LOG_FILE ||
      path.join(app.getPath("temp"), "localmind-worker.log"),
  };

  console.log("[provision] starting once");
  console.log("  wheels:", env.LM_WHEELS_ROOT);
  console.log("  reqs  :", env.LM_REQUIREMENTS_ROOT);
  console.log("  data  :", env.LOCALMIND_DATA_DIR);
  console.log("  list  :", env.LM_PROVISION_BACKENDS);

  const res = spawnSync(prov, [], { env, stdio: "inherit" });
  if (res.error) {
    console.warn("[provision] spawn error:", res.error);
  } else if (typeof res.status === "number" && res.status !== 0) {
    console.warn("[provision] non-zero exit code:", res.status);
  } else {
    console.log("[provision] completed");
  }
}

async function maybeProvisionOnFirstRun(): Promise<void> {
  if (needsProvision()) {
    runProvisionerOnce();
  }
}

/* -----------------------------------------------------------
   Backend lifecycle (idempotent + serialized)
----------------------------------------------------------- */

let starting: Promise<void> | null = null;

async function isHealthyFromPorts(): Promise<number | null> {
  const p = readPortsJson();
  // 🌟 tweak: verify both /openapi.json AND /info
  if (p && (await probePort(p)) && (await probeOwnBackend(p))) return p;
  return null;
}

async function startBackend(): Promise<void> {
  if (backendProc) return;
  // If another instance is already serving (or a prior run left it up), don't spawn
  if (await isHealthyFromPorts()) return;

  const { cmd, args } = backendCommand();
  const root = repoRoot();

  // Build env as a plain string map so we can add custom keys safely
  const env = { ...process.env } as Record<string, string>;

  env.PYTHONUNBUFFERED = "1";
  env.PYTHONIOENCODING = "utf-8";
  env.PYTHONUTF8 = "1";

  // runtime data dir (ports.json, dbs, etc.)
  env.LOCALMIND_DATA_DIR = app.getPath("userData");

  // where the backend will serve the SPA from
  env.LM_FRONTEND_DIST = app.isPackaged
    ? path.join(process.resourcesPath, "frontend", "dist")
    : path.join(root, "frontend", "dist");

  // still useful for any runtime-side logic
  env.LM_WHEELS_ROOT = wheelsRoot();
  env.LM_REQUIREMENTS_ROOT = requirementsRoot();

  // ensure imports resolve to bundled packages in packaged mode
  env.PYTHONPATH = app.isPackaged ? process.resourcesPath : repoRoot();

  env.LOG_RUNTIME_DEBUG = process.env.LOG_RUNTIME_DEBUG || "1";
  env.LM_WORKER_LOG_FILE =
    process.env.LM_WORKER_LOG_FILE ||
    path.join(app.getPath("temp"), "localmind-worker.log");

  // Correlate one true server boot + identify Electron as the real parent
  env.LM_BOOT_ID =
    (crypto as any).randomUUID?.() ||
    Math.random().toString(36).slice(2);
  env.LM_PARENT_PID = String(process.pid);

  const front = env.LM_FRONTEND_DIST || "";
  if (!fs.existsSync(front)) {
    console.warn("[boot] LM_FRONTEND_DIST missing:", front);
  }

  console.log("[boot] starting backend:", cmd, args.join(" "));
  console.log("[boot] LM_BOOT_ID", env.LM_BOOT_ID, "LM_PARENT_PID", env.LM_PARENT_PID);

  const proc = spawn(cmd, args, { cwd: root, env, stdio: ["ignore", "pipe", "pipe"] });

  backendProc = proc;
  proc.stdout?.on("data", (b) => console.log("[py]", String(b).trim()));
  proc.stderr?.on("data", (b) => console.warn("[py err]", String(b).trim()));
  proc.on("exit", (code, sig) => {
    console.warn("[py exit]", code, sig);
    backendProc = null;
  });
}

async function waitForHealthy(timeoutMs = 120000): Promise<number> {
  const t0 = Date.now();
  let lastPort: number | null = null;
  while (Date.now() - t0 < timeoutMs) {
    const p = readPortsJson();
    if (p) {
      lastPort = p;
      if (await probePort(p)) return p;
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  if (lastPort && (await probePort(lastPort))) return lastPort;
  throw new Error("Backend did not become healthy in time.");
}

// Serialize + idempotent
async function ensureBackend(): Promise<void> {
  // quick success if already healthy
  if (await isHealthyFromPorts()) return;

  if (starting) {
    await starting;
    return;
  }

  starting = (async () => {
    // close tiny race window
    if (await isHealthyFromPorts()) return;
    await startBackend();
    await waitForHealthy();
  })();

  try {
    await starting;
  } finally {
    starting = null;
  }
}

async function waitForHealthyPort(): Promise<number> {
  await ensureBackend();
  return await waitForHealthy();
}

/* 🌟 NEW: graceful stop (then fallback to kill) */
async function stopBackendGracefully(timeoutMs = 3000) {
  try {
    const port = await isHealthyFromPorts();
    if (port) {
      await new Promise<void>((resolve) => {
        const req = http.request(
          { host: "127.0.0.1", port, path: "/api/runtime/stop", method: "POST" },
          (res) => {
            res.resume();
            resolve();
          }
        );
        req.on("error", () => resolve());
        req.end();
      });
      const t0 = Date.now();
      while (Date.now() - t0 < timeoutMs) {
        if (!(await probePort(port))) break;
        await new Promise((r) => setTimeout(r, 150));
      }
    }
  } catch {}
  try {
    if (backendProc) {
      backendProc.kill();
      backendProc = null;
    }
  } catch {}
}

/* -----------------------------------------------------------
   Licensing deeplink helper
----------------------------------------------------------- */

function sendToFastAPI(port: number, license: string) {
  const data = JSON.stringify({ license });
  const req = http.request(
    {
      host: "127.0.0.1",
      port,
      path: "/api/license/apply", // fixed path to match backend routes
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(data),
      },
    },
    (res) => {
      res.resume();
    }
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

/* -----------------------------------------------------------
   Licenses menu
----------------------------------------------------------- */

async function openLicenses() {
  const txt = path.join(process.resourcesPath, "licenses", "LICENSES-THIRD-PARTY.txt");
  const npm = path.join(process.resourcesPath, "licenses", "LICENSES-NPM.json");
  try {
    await shell.openPath(txt);
  } catch {}
  try {
    await shell.openPath(npm);
  } catch {}
}

function setAppMenu() {
  const template: Electron.MenuItemConstructorOptions[] = [];

  if (process.platform === "darwin") {
    template.push({
      label: app.name,
      submenu: [
        { role: "about" },
        { type: "separator" },
        { label: "Licenses…", click: () => openLicenses() },
        { type: "separator" },
        { role: "quit" },
      ],
    });
  }

  template.push({
    label: "Help",
    submenu: [
      { label: "Licenses…", click: () => openLicenses() },
      { type: "separator" },
      { role: "toggleDevTools" },
    ],
  });

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}

/* -----------------------------------------------------------
   Window boot
----------------------------------------------------------- */

async function loadWithRetry(
  win: BrowserWindow,
  url: string,
  timeoutMs = 120000
): Promise<void> {
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

// Make unhandled rejections visible in logs (helps debugging white screens)
process.on("unhandledRejection", (err) => {
  console.error("[unhandledRejection]", err);
});

if (!gotLock) {
  app.quit();
} else {
  // IMPORTANT: provision BEFORE we even think about the backend/UI
  async function ensureProvisioned() {
    try {
      await maybeProvisionOnFirstRun();
    } catch (e) {
      console.warn("[provision] error:", e);
    }
  }

  // Cached port resolver — caches the PROMISE to prevent double-start
  const getPortOnce = (() => {
    let portPromise: Promise<number> | null = null;
    return async () => {
      if (portPromise) return portPromise;
      portPromise = (async () => {
        await ensureProvisioned();
        await ensureBackend(); // serialized + idempotent
        const p = await waitForHealthy();
        return p;
      })();
      return portPromise;
    };
  })();

  const handleDeepLink = makeDeepLinkHandler(getPortOnce);

  app.on("second-instance", async (_evt, argv) => {
    const deeplink = argv.find(
      (a) => typeof a === "string" && a.startsWith("localmind://")
    );
    if (deeplink) await handleDeepLink(deeplink);
    if (mainWin) {
      if (mainWin.isMinimized()) mainWin.restore();
      mainWin.focus();
    }
  });

  app.whenReady().then(async () => {
    setAppMenu();

    mainWin = new BrowserWindow({ width: 1200, height: 800 });
    if (!app.isPackaged) {
      mainWin.webContents.openDevTools({ mode: "detach" });
    }
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

    // Ensure provision occurs before backend wait (prevents loops / white screen)
    await ensureProvisioned();

    const port = await getPortOnce();
    const url = `http://127.0.0.1:${port}/`;
    await loadWithRetry(mainWin, url, 120000).catch(async () => {
      try {
        await mainWin!.loadURL(`${url}docs`);
      } catch {
        if (mainWin) mainWin.loadURL("about:blank");
      }
    });
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });

  /* 🌟 NEW: graceful stop on quit */
  app.on("before-quit", (e) => {
    e.preventDefault();
    stopBackendGracefully(2500).finally(() => app.exit(0));
  });

  // Keep your old fallback too (in case before-quit doesn't fire):
  app.on("will-quit", () => {
    if (backendProc) {
      try {
        backendProc.kill();
      } catch {}
    }
  });
}
