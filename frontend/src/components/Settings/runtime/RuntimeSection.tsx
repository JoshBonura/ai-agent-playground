// frontend/src/components/Settings/runtime/RuntimeSection.tsx
import { useEffect, useMemo, useState } from "react";
import {
  getRuntimeStatus,
  installRuntime,
  switchRuntime,
  getRuntimeCatalog,
  installFromCloudflare,
  type RuntimeStatus,
  type RuntimeCatalog,
} from "../../../api/runtime";

// tiny PATCH helper (avoids pulling your global http wrapper)
async function patchJSON<T = any>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(txt || `PATCH ${url} failed (${res.status})`);
  }
  return (await res.json().catch(() => ({}))) as T;
}

type Overrides = {
  runtime?: {
    preferred_backend?: string;
    allow_fallback?: boolean;
  };
};

function semverCmp(a: string, b: string) {
  const pa = a.replace(/^v/i, "").split(".").map((n) => parseInt(n, 10) || 0);
  const pb = b.replace(/^v/i, "").split(".").map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const da = pa[i] ?? 0, db = pb[i] ?? 0;
    if (da !== db) return da - db;
  }
  return 0;
}

export default function RuntimeSection() {
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  const [catalog, setCatalog] = useState<RuntimeCatalog | null>(null);
  const [preferredBackend, setPreferredBackend] = useState<string | null>(null);
  const [busy, setBusy] = useState<string>("");
  const [msg, setMsg] = useState<string>("");

  async function refresh() {
    setMsg("");
    try {
      const [s, o] = await Promise.all([
        getRuntimeStatus(),
        fetch("/api/settings/overrides")
          .then(async (r) => (r.ok ? r.json() : ({} as Overrides)))
          .catch(() => ({} as Overrides)),
      ]);
      setStatus(s);
      setPreferredBackend(o.runtime?.preferred_backend ?? null);

      try {
        const c = await getRuntimeCatalog();
        setCatalog(c);
      } catch (e: any) {
        console.error("[Runtime] catalog fetch failed:", e);
        setCatalog(null);
        setMsg(String(e?.message || "Catalog fetch failed"));
      }
    } catch (e: any) {
      console.error("[Runtime] status/overrides fetch failed:", e);
      setMsg(String(e?.message || "Runtime status fetch failed"));
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  const installed = useMemo(() => status?.installed ?? [], [status]);
  const current = status?.info?.backend ?? null;
  const currentVersion = status?.active?.version ?? null;

  const osTok = useMemo<"win" | "linux" | "mac" | null>(() => {
    if (!status) return null;
    if (status.platform === "windows") return "win";
    if (status.platform === "linux") return "linux";
    if (status.platform === "mac") return "mac";
    return null;
  }, [status]);

  // backend -> latest version available for THIS OS (from catalog)
  const latestByBackend = useMemo(() => {
    if (!catalog || !osTok) return {} as Record<string, string>;
    const out: Record<string, string> = {};
    const backends = new Set<string>();
    for (const x of catalog.builds ?? []) {
      if (x.os === osTok) backends.add(x.backend);
    }
    for (const b of backends) {
      const builds = (catalog.builds || []).filter((x) => x.os === osTok && x.backend === b);
      const latest = builds.reduce<string | null>(
        (acc, x) => (!acc ? x.version : semverCmp(x.version, acc) > 0 ? x.version : acc),
        null
      );
      if (latest) out[b] = latest;
    }
    return out;
  }, [catalog, osTok]);

  // Available to install = (status.allowed ∪ catalog.availableForOS) \ installed
  const missing = useMemo(() => {
    const installedSet = new Set(installed);
    const allowed = status?.allowed ?? [];
    const catalogBackends = new Set<string>();
    if (catalog && osTok) {
      for (const b of catalog.builds ?? []) {
        if (b.os === osTok) catalogBackends.add(b.backend);
      }
    }
    const universe = new Set<string>([...allowed, ...catalogBackends]);
    return Array.from(universe).filter((b) => !installedSet.has(b));
  }, [installed, status, catalog, osTok]);

  async function onSwitch(b: string) {
    setBusy(`switch:${b}`);
    setMsg("");
    try {
      await switchRuntime(b);
      setMsg(`Using ${b.toUpperCase()}`);
    } catch (e: any) {
      setMsg(e?.response?.data?.detail || e?.message || "Failed to start");
    } finally {
      setBusy("");
      void refresh();
    }
  }

  async function onInstall(b: string) {
    setBusy(`install:${b}`);
    setMsg("");
    try {
      await installRuntime(b);
      setMsg(`Installed ${b.toUpperCase()} from local wheels`);
    } catch (e: any) {
      setMsg(e?.response?.data?.detail || e?.message || "Install failed");
    } finally {
      setBusy("");
      void refresh();
    }
  }

  async function onInstallFromCF(b: string) {
    setBusy(`cf:${b}`);
    setMsg("");
    try {
      const v = latestByBackend[b];
      if (!v) throw new Error(`No version available for ${b.toUpperCase()}`);
      await installFromCloudflare(b, v, true);
      setMsg(`Installed ${b.toUpperCase()} ${v} from Cloudflare`);
    } catch (e: any) {
      setMsg(e?.response?.data?.detail || e?.message || "Cloudflare install failed");
    } finally {
      setBusy("");
      void refresh();
    }
  }

  async function onMakeDefault(b: string) {
    setBusy(`default:${b}`);
    setMsg("");
    try {
      await patchJSON("/api/settings/overrides", {
        runtime: { preferred_backend: b, allow_fallback: false },
      });
      setPreferredBackend(b); // optimistic
      setMsg(`Pinned ${b.toUpperCase()} as default`);
    } catch (e: any) {
      setMsg(e?.response?.data?.detail || e?.message || "Failed to save preference");
    } finally {
      setBusy("");
      void refresh();
    }
  }

  const isBusy = (k: string) => busy === k || busy.startsWith(k + ":");

  return (
    <section className="flex-1 min-w-0 flex flex-col">
      <header className="px-5 py-4 border-b">
        <div className="text-base font-semibold">Runtime</div>
        {status && (
          <div className="text-xs text-gray-600 mt-1">
            Platform: <b>{status.platform}</b> · Running: <b>{status.running ? "yes" : "no"}</b>
            {status.running && current ? (
              <>
                {" "}· Backend: <b>{current.toUpperCase()}</b>
                {currentVersion ? <> · Version: <b>{currentVersion}</b></> : null}
                {status.info?.port ? <> · Port: <b>{status.info.port}</b></> : null}
              </>
            ) : null}
          </div>
        )}
        {catalog && (
          <div className="text-[11px] text-gray-400 mt-0.5">
            catalog schema {catalog.schema} · builds={catalog.builds?.length ?? 0}
          </div>
        )}
      </header>

      <div className="p-5 space-y-6">
        {!status ? (
          <div className="text-sm text-gray-500">Loading…</div>
        ) : (
          <>
            {/* Installed */}
            <div className="rounded-2xl border p-4">
              <div className="font-semibold mb-3">Installed</div>
              {installed.length === 0 && (
                <div className="text-sm text-gray-500">No runtimes installed.</div>
              )}
              <div className="flex flex-col gap-2">
                {installed.map((b) => {
                  const active = current === b;
                  const isDefault = preferredBackend === b;
                  const latest = latestByBackend[b];

                  return (
                    <div key={b} className="flex items-center justify-between border rounded px-3 py-2">
                      <div className="text-sm">
                        {b.toUpperCase()} {active ? "· Active" : ""} {isDefault ? " · Default" : ""}
                        {latest ? (
                          <span className="ml-2 text-xs text-gray-500">Latest available: {latest}</span>
                        ) : null}
                      </div>
                      <div className="flex items-center gap-2">
                        {/* Always show CF button when a latest exists (even if not active) */}
                        {latest ? (
                          <button
                            onClick={() => onInstallFromCF(b)}
                            disabled={busy !== ""}
                            className="text-xs px-3 py-1.5 rounded border hover:bg-gray-50"
                            title={
                              active
                                ? `Update ${b.toUpperCase()} to ${latest}`
                                : `Install ${b.toUpperCase()} ${latest} from Cloudflare`
                            }
                          >
                            {isBusy(`cf:${b}`)
                              ? (active ? "Updating…" : "Fetching…")
                              : (active ? `Update to ${latest}` : `Install ${latest}`)}
                          </button>
                        ) : null}

                        <button
                          onClick={() => onSwitch(b)}
                          disabled={busy !== "" || active}
                          className={`text-xs px-3 py-1.5 rounded border ${
                            active ? "bg-black text-white" : "hover:bg-gray-50"
                          }`}
                          title={active ? "Currently active" : `Switch to ${b.toUpperCase()}`}
                        >
                          {isBusy(`switch:${b}`) ? "Switching…" : active ? "Active" : "Switch"}
                        </button>

                        <button
                          onClick={() => onMakeDefault(b)}
                          disabled={busy !== "" || isDefault}
                          className={`text-xs px-3 py-1.5 rounded border ${
                            isDefault ? "bg-gray-200 text-gray-500 cursor-not-allowed" : "hover:bg-gray-50"
                          }`}
                          title={isDefault ? "Already default" : `Pin ${b.toUpperCase()} as default`}
                        >
                          {isBusy(`default:${b}`) ? "Saving…" : isDefault ? "Default" : "Make default"}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Available to install */}
            {missing.length > 0 && (
              <div className="rounded-2xl border p-4">
                <div className="font-semibold mb-3">Available to install</div>
                <div className="text-xs text-gray-500 mb-2">
                  Only options compatible with your OS are shown.
                </div>
                <div className="flex flex-col gap-2">
                  {missing.map((b) => {
                    const latest = latestByBackend[b];
                    return (
                      <div key={b} className="flex items-center justify-between border rounded px-3 py-2">
                        <div className="text-sm">
                          {b.toUpperCase()}{" "}
                          {latest ? (
                            <span className="ml-2 text-xs text-gray-500">Latest available: {latest}</span>
                          ) : null}
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => onInstall(b)}
                            disabled={busy !== ""}
                            className="text-xs px-3 py-1.5 rounded border hover:bg-gray-50"
                            title={`Install from local wheels for ${b.toUpperCase()}`}
                          >
                            {isBusy(`install:${b}`) ? "Installing…" : "Install (local)"}
                          </button>
                          {latest ? (
                            <button
                              onClick={() => onInstallFromCF(b)}
                              disabled={busy !== ""}
                              className="text-xs px-3 py-1.5 rounded border hover:bg-gray-50"
                              title={`Download ${b.toUpperCase()} ${latest} from Cloudflare and install`}
                            >
                              {isBusy(`cf:${b}`) ? "Fetching…" : "Install from Cloudflare"}
                            </button>
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {msg && <div className="text-xs text-gray-700">{msg}</div>}
          </>
        )}
      </div>
    </section>
  );
}
