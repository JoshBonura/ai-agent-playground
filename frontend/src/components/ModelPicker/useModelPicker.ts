// frontend/src/components/ModelPicker/useModelPicker.ts
import { useEffect, useMemo, useRef, useState } from "react";
import { getModels, peekModelsCache, type ModelFile } from "../../api/models";
import { getJSON, postJSON } from "../../services/http";
import { getResources, type Resources as ApiResources } from "../../api/system";
import type { LlamaKwargs } from "../../api/modelWorkers";

export type WorkerHealth =
  | {
      ok: boolean;
      model: string;
      path: string;
      n_ctx: number;
      n_threads: number;
      n_gpu_layers: number;
      n_batch: number;
      progress?: { pct: number };
    }
  | null;

export type WorkerRow = {
  id: string;
  port: number;
  model_path: string;
  status: "loading" | "ready" | "stopped";
  health?: WorkerHealth;
};

export type SortKey = "recency" | "size" | "name";
export type SortDir = "asc" | "desc";

// Track busy per model path, optionally with the worker id once we have it
type BusyMap = Record<string, { id?: string }>;
type SpawnResult = { ok?: boolean; worker?: { id?: string } };

// ---- timing helpers ----
const nowIso = () => new Date().toISOString();
const nowMs = () => performance.now().toFixed(1);

export function useModelPicker(
  open: boolean,
  onLoaded?: () => void,
  _onClose?: () => void,
) {
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [models, setModels] = useState<ModelFile[]>([]);

  const [workers, setWorkers] = useState<WorkerRow[]>([]);
  const [activeWorkerId, setActiveWorkerId] = useState<string | null>(null);
  const [res, setRes] = useState<ApiResources | null>(null);

  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("size");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // ✅ per-row busy
  const [busy, setBusy] = useState<BusyMap>({});

  // Advanced worker settings
  const [advOpen, setAdvOpen] = useState(false);
  const [adv, setAdv] = useState<LlamaKwargs>({});
  const [advRemember, setAdvRemember] = useState(true);

  const isTempId = (id: string) => id.startsWith("temp-");
  const mountedRef = useRef(false);
  const pollTimer = useRef<number | null>(null);
  const burstTimer = useRef<number | null>(null);

  // ✅ track workers that should auto-activate when they become ready
  const pendingActivateRef = useRef<Set<string>>(new Set());

async function fetchInspectAndResources() {
  try {
    const [w, r] = await Promise.all([
      getJSON<{ ok: boolean; workers: WorkerRow[]; active: string | null }>(
        "/api/model-workers/inspect",
      ),
      getResources(),
    ]);

    // Update resources first
    setRes((prev) => ({
      ...(r || {}),
      cpuPct: r?.cpuPct ?? prev?.cpuPct ?? null,
    }));

    // Track active id from server
    setActiveWorkerId(w?.active ?? null);

    // Merge server workers with any local optimistic (temp) rows that the server doesn't know about yet
    setWorkers((prev) => {
      const server = w?.workers ?? [];

      // Fast path: if no previous local ghosts, just use server list
      const hasLocalGhost = prev.some(
        (lw) => lw.status === "loading" && lw.id.startsWith("temp-"),
      );
      if (!hasLocalGhost) return server;

      // Index server by id and by model_path
      const byId = new Map(server.map((x) => [x.id, x]));
      const byPath = new Map(server.map((x) => [x.model_path, x]));

      // Start with server list
      const merged: WorkerRow[] = server.slice();

      // Re-attach any optimistic temp rows that aren't represented on the server yet
      for (const lw of prev) {
        const isGhost = lw.status === "loading" && lw.id.startsWith("temp-");
        if (!isGhost) continue;

        // If server already has either the same id (rare) or the same model_path (normal), skip the ghost
        if (byId.has(lw.id)) continue;
        if (byPath.has(lw.model_path)) continue;

        // Keep ghost visible at the top so the user sees immediate feedback
        merged.unshift(lw);
      }

      return merged;
    });
  } catch {
    // Keep previous workers state (including ghosts) if this poll failed
    setRes(null);
  }
}

  // Regular slow-ish poll
  useEffect(() => {
    if (!open) return;
    let alive = true;

    const tick = async () => {
      if (!alive) return;
      await fetchInspectAndResources();
      if (!alive) return;
      pollTimer.current = window.setTimeout(tick, 30000);
    };

    tick();

    return () => {
      alive = false;
      if (pollTimer.current) window.clearTimeout(pollTimer.current);
      pollTimer.current = null;
    };
  }, [open]);

  // Burst poll (1s * 15) after each spawn to update the row quickly
  function startBurstPoll() {
    let count = 0;
    const run = async () => {
      await fetchInspectAndResources();
      count += 1;
      if (count < 15) {
        burstTimer.current = window.setTimeout(run, 1000);
      } else {
        burstTimer.current = null;
      }
    };
    if (burstTimer.current) window.clearTimeout(burstTimer.current);
    run();
  }

  useEffect(() => {
    if (!open) return;
    mountedRef.current = true;

    let alive = true;

    const bootstrap = async () => {
      try {
        setErr(null);

        // 1) Paint from cache immediately if available
        const cached = peekModelsCache();
        if (cached?.available?.length) {
          setModels(cached.available);
          setLoading(false);
        } else {
          setLoading(true);
        }

        // 2) ETag revalidation (fast listing on server)
        const data = await getModels({ fast: true });
        if (!mountedRef.current || !alive) return;
        setModels(data.available || []);
      } catch (e: any) {
        if (!mountedRef.current || !alive) return;
        setErr(e?.message || "Failed to load models");
      } finally {
        if (mountedRef.current && alive) setLoading(false);
      }
    };

    bootstrap();

    return () => {
      alive = false;
      mountedRef.current = false;
      if (burstTimer.current) window.clearTimeout(burstTimer.current);
    };
  }, [open]);

  // Hotkey: Alt+A toggles advanced panel
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.altKey && e.key.toLowerCase() === "a") {
        e.preventDefault();
        setAdvOpen((s) => !s);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // ✅ Remove busy rows when their worker transitions off "loading"
  useEffect(() => {
    if (!workers.length) return;
    setBusy((prev) => {
      const next: BusyMap = { ...prev };
      for (const [path, meta] of Object.entries(prev)) {
        const w = workers.find((ww) =>
          meta.id ? ww.id === meta.id : ww.model_path === path,
        );
        if (w && w.status !== "loading") {
          delete next[path];
        }
      }
      return next;
    });
  }, [workers]);

  // Helper: optimistic insert so the Workers section shows immediately
function upsertWorkerLoadingRow(modelPath: string, id?: string) {
  const ghostId = id || `temp-${Math.random().toString(36).slice(2)}`;
  console.debug("[UI] upsertWorkerLoadingRow", {
    modelPath,
    id: ghostId,
    real: !!id,
    tISO: nowIso(),
    tMs: nowMs(),
  });

  setWorkers((prev) => {
    // If a loading row for this path already exists, optionally upgrade it with the real id
    const existingIdx = prev.findIndex(
      (w) => w.model_path === modelPath && w.status === "loading",
    );

    if (existingIdx !== -1) {
      // If we’ve received a real id and the existing one is a temp, upgrade it
      if (id && prev[existingIdx].id.startsWith("temp-")) {
        const next = prev.slice();
        next[existingIdx] = { ...next[existingIdx], id };
        return next;
      }
      // Otherwise keep current state
      return prev;
    }

    // If we’re adding with a real id but it already exists in the list, keep as-is
    if (id && prev.some((w) => w.id === id)) return prev;

    // Insert a new ghost row at the top
    const ghost: WorkerRow = {
      id: ghostId,
      port: 0,
      model_path: modelPath,
      status: "loading",
      health: null,
    };
    return [ghost, ...prev];
  });
}

  // ✅ Load spawns a worker and returns immediately; UI stays responsive
  async function handleLoad(m: ModelFile) {
    if (busy[m.path]) return; // already loading this one
    setErr(null);
    setBusy((b) => ({ ...b, [m.path]: {} }));

    const tClick = performance.now();
    console.info("[UI] spawn:click", { path: m.path, tISO: nowIso(), tMs: nowMs() });

    // Show a loading row right away
    upsertWorkerLoadingRow(m.path);

    const tSend = performance.now();
    console.info("[UI] spawn:send", {
      path: m.path,
      dtMsFromClick: (tSend - tClick).toFixed(1),
      tISO: nowIso(),
      tMs: nowMs(),
    });

    // Fire-and-forget spawn; don't block the UI
    void postJSON<SpawnResult>("/api/model-workers/spawn", {
      modelPath: m.path,
      ...(Object.keys(adv || {}).length ? { llamaKwargs: adv } : {}),
    })
      .then((resp) => {
        const tRecv = performance.now();
        console.info("[UI] spawn:recv", {
          path: m.path,
          status: "ok",
          msTotal: (tRecv - tClick).toFixed(1),
          msNet: (tRecv - tSend).toFixed(1),
          tISO: nowIso(),
          tMs: nowMs(),
        });

        const id = resp.worker?.id;
        console.debug("[UI] /spawn returned", { id, path: m.path, resp });
        if (id) {
            // Track busy with the real id
            setBusy((b) => ({ ...b, [m.path]: { id } }));

            // Immediately upgrade any ghost row for this path to the real id
            setWorkers((prev) => {
                const idx = prev.findIndex(
                (w) => w.model_path === m.path && w.status === "loading",
                );
                if (idx !== -1) {
                const next = prev.slice();
                next[idx] = { ...next[idx], id };
                return next;
                }
                // If no ghost exists (edge), insert a loading row with the real id
                return [
                { id, port: 0, model_path: m.path, status: "loading", health: null },
                ...prev,
                ];
            });

            // Auto-activate once ready
            pendingActivateRef.current.add(id);
            }
        onLoaded?.();
        startBurstPoll();
      })
      .catch((e: any) => {
        const tFail = performance.now();
        console.warn("[UI] spawn:recv", {
          path: m.path,
          status: "error",
          msTotal: (tFail - tClick).toFixed(1),
          msNet: (tFail - tSend).toFixed(1),
          tISO: nowIso(),
          tMs: nowMs(),
          err: e?.message,
        });

        setErr(e?.message || "Failed to load model");
        setBusy((b) => {
          const { [m.path]: _omit, ...rest } = b;
          return rest;
        });
        // remove any ghost row for this path
        setWorkers((prev) =>
          prev.filter(
            (w) => !(w.model_path === m.path && w.status === "loading"),
          ),
        );
      });
  }

  // Auto-activate exactly once when a pending worker flips to ready
    useEffect(() => {
    if (!workers.length) return;
    setBusy((prev) => {
        const next: BusyMap = { ...prev };
        for (const [path, meta] of Object.entries(prev)) {
        const w = workers.find((ww) =>
            meta.id ? ww.id === meta.id : ww.model_path === path,
        );
        if (w && w.status !== "loading") {
            delete next[path];
        }
        }
        return next;
    });
    }, [workers]);

  async function handleKillWorker(id: string) {
    if (!id) return;

    const tClick = performance.now();
    console.info("[UI] kill:click", { id, tISO: nowIso(), tMs: nowMs() });

    // If it's a temp row, kill-by-path (true backend kill or queued kill-on-spawn)
    if (isTempId(id)) {
      const row = workers.find((w) => w.id === id);
      const modelPath = row?.model_path;
      if (!modelPath) return;

      const tSend = performance.now();
      console.info("[UI] kill-by-path:send", {
        modelPath,
        includeReady: true,
        waitMs: 2000,
        dtMsFromClick: (tSend - tClick).toFixed(1),
        tISO: nowIso(),
        tMs: nowMs(),
      });

      try {
        await postJSON("/api/model-workers/kill-by-path", {
          modelPath,
          includeReady: false, // or false if you only want to cancel loading
          waitMs: 2000, // catch just-started spawns
        });

        const tRecv = performance.now();
        console.info("[UI] kill-by-path:recv", {
          modelPath,
          msTotal: (tRecv - tClick).toFixed(1),
          msNet: (tRecv - tSend).toFixed(1),
          tISO: nowIso(),
          tMs: nowMs(),
        });

        // Optimistically remove the ghost row
        setWorkers((prev) => prev.filter((w) => w.id !== id));
        // Clear busy state for that path so user can try again
        setBusy((b) => {
          const { [modelPath]: _omit, ...rest } = b;
          return rest;
        });
      } catch (e: any) {
        const tFail = performance.now();
        console.warn("[UI] kill-by-path:recv", {
          modelPath,
          status: "error",
          msTotal: (tFail - tClick).toFixed(1),
          tISO: nowIso(),
          tMs: nowMs(),
          err: e?.message,
        });
        setErr(e?.message || "Failed to stop worker");
      }
      return;
    }

    // Real id: existing behavior
    const tSend = performance.now();
    console.info("[UI] kill:send", {
      id,
      dtMsFromClick: (tSend - tClick).toFixed(1),
      tISO: nowIso(),
      tMs: nowMs(),
    });

    try {
      await postJSON(`/api/model-workers/kill/${encodeURIComponent(id)}`, {});
      const tRecv = performance.now();
      console.info("[UI] kill:recv", {
        id,
        msTotal: (tRecv - tClick).toFixed(1),
        msNet: (tRecv - tSend).toFixed(1),
        tISO: nowIso(),
        tMs: nowMs(),
      });
      onLoaded?.();
      startBurstPoll();
    } catch (e: any) {
      const tFail = performance.now();
      console.warn("[UI] kill:recv", {
        id,
        status: "error",
        msTotal: (tFail - tClick).toFixed(1),
        tISO: nowIso(),
        tMs: nowMs(),
        err: e?.message,
      });
      setErr(e?.message || "Failed to stop worker");
    }
  }

  async function handleActivateWorker(id: string) {
    if (!id) return;
    try {
      await postJSON(
        `/api/model-workers/activate/${encodeURIComponent(id)}`,
        {},
      );
      const w = await getJSON<{
        ok: boolean;
        workers: WorkerRow[];
        active: string | null;
      }>("/api/model-workers/inspect");
      setWorkers(w?.workers ?? []);
      setActiveWorkerId(w?.active ?? null);
    } catch (e: any) {
      setErr(e?.message || "Failed to activate worker");
    }
  }

  const vram = useMemo(() => {
    if (!res?.gpus?.length)
      return { used: null as number | null, total: null as number | null };
    const total = res.gpus.reduce((s, g) => s + (g.total || 0), 0);
    const used = res.gpus.reduce((s, g) => s + (g.used || 0), 0);
    return { used, total };
  }, [res?.gpus]);

  const activeWorker =
    workers.find((w) => w.id === activeWorkerId) || null;
  const hasReadyActiveWorker =
    !!activeWorkerId && !!activeWorker && activeWorker.status === "ready";
  const activeWorkerName =
    (activeWorker?.model_path || "").split(/[\\/]/).pop() ||
    activeWorker?.model_path ||
    null;

  return {
    loading,
    err,
    models,
    workers,
    activeWorkerId,
    res,
    vram,
    query,
    setQuery,
    sortKey,
    setSortKey,
    sortDir,
    setSortDir,
    // ✅ expose per-row busy
    busyPaths: Object.keys(busy),

    // advanced
    advOpen,
    setAdvOpen,
    adv,
    setAdv,
    advRemember,
    setAdvRemember,

    // computed
    hasReadyActiveWorker,
    activeWorkerName,

    // handlers
    handleLoad,
    handleKillWorker,
    handleActivateWorker,
  };
}
