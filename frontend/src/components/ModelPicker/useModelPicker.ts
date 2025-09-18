import { useEffect, useMemo, useRef, useState } from "react";
import { getModels, type ModelFile } from "../../api/models";
import { getJSON, postJSON } from "../../services/http";
import { getResources, type Resources as ApiResources } from "../../api/system";
import type { LlamaKwargs } from "../../api/modelWorkers";

export type WorkerHealth = {
  ok: boolean;
  model: string;
  path: string;
  n_ctx: number;
  n_threads: number;
  n_gpu_layers: number;
  n_batch: number;
} | null;

export type WorkerRow = {
  id: string;
  port: number;
  model_path: string;
  status: "loading" | "ready" | "stopped";
  health?: WorkerHealth;
};

export type SortKey = "recency" | "size" | "name";
export type SortDir = "asc" | "desc";

export function useModelPicker(open: boolean, onLoaded?: () => void, _onClose?: () => void) {
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [models, setModels] = useState<ModelFile[]>([]);

  const [workers, setWorkers] = useState<WorkerRow[]>([]);
  const [activeWorkerId, setActiveWorkerId] = useState<string | null>(null);
  const [res, setRes] = useState<ApiResources | null>(null);

  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("size");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [busyPath, setBusyPath] = useState<string | null>(null);

  // Advanced worker settings
  const [advOpen, setAdvOpen] = useState(false);
  const [adv, setAdv] = useState<LlamaKwargs>({});
  const [advRemember, setAdvRemember] = useState(true);

  const mountedRef = useRef(false);

  useEffect(() => {
    if (!open) return;
    mountedRef.current = true;

    let alive = true;
    let t: any = null;

    const bootstrap = async () => {
      try {
        setErr(null);
        setLoading(true);
        const data = await getModels();
        if (!mountedRef.current || !alive) return;
        setModels(data.available || []);
      } catch (e: any) {
        if (!mountedRef.current || !alive) return;
        setErr(e?.message || "Failed to load models");
      } finally {
        if (mountedRef.current && alive) setLoading(false);
      }
    };

    const tick = async () => {
      try {
        const [w, r] = await Promise.all([
          getJSON<{ ok: boolean; workers: WorkerRow[]; active: string | null }>("/api/model-workers/inspect"),
          getResources(),
        ]);
        if (!alive) return;
        setWorkers(w?.workers ?? []);
        setActiveWorkerId(w?.active ?? null);
        setRes((prev) => ({ ...(r || {}), cpuPct: r.cpuPct ?? prev?.cpuPct ?? null }));
      } catch {
        if (!alive) return;
        setWorkers([]);
        setRes(null);
      } finally {
        if (alive && mountedRef.current) t = setTimeout(tick, 30000);
      }
    };

    bootstrap().then(() => { if (alive) tick(); });

    return () => {
      alive = false;
      mountedRef.current = false;
      if (t) clearTimeout(t);
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

  // Load now spawns a worker with advanced kwargs
  async function handleLoad(m: ModelFile) {
    if (busyPath) return;
    setBusyPath(m.path);
    setErr(null);
    try {
      const payload: any = { modelPath: m.path };
      if (Object.keys(adv || {}).length) payload.llamaKwargs = adv;
      await postJSON("/api/model-workers/spawn", payload);
      onLoaded?.();
      // keep modal open so user can activate/see the worker; close if you prefer
      // onClose?.();
    } catch (e: any) {
      setErr(e?.message || "Failed to load model");
    } finally {
      setBusyPath(null);
    }
  }

  async function handleKillWorker(id: string) {
    if (!id) return;
    try {
      await postJSON(`/api/model-workers/kill/${encodeURIComponent(id)}`, {});
      onLoaded?.();
    } catch (e: any) {
      setErr(e?.message || "Failed to stop worker");
    }
  }

  async function handleActivateWorker(id: string) {
    if (!id) return;
    try {
      await postJSON(`/api/model-workers/activate/${encodeURIComponent(id)}`, {});
      const w = await getJSON<{ ok: boolean; workers: WorkerRow[]; active: string | null }>(
        "/api/model-workers/inspect",
      );
      setWorkers(w?.workers ?? []);
      setActiveWorkerId(w?.active ?? null);
    } catch (e: any) {
      setErr(e?.message || "Failed to activate worker");
    }
  }

  const vram = useMemo(() => {
    if (!res?.gpus?.length) return { used: null as number | null, total: null as number | null };
    const total = res.gpus.reduce((s, g) => s + (g.total || 0), 0);
    const used  = res.gpus.reduce((s, g) => s + (g.used  || 0), 0);
    return { used, total };
  }, [res?.gpus]);

  const activeWorker = workers.find((w) => w.id === activeWorkerId) || null;
  const hasReadyActiveWorker = !!activeWorkerId && !!activeWorker && activeWorker.status === "ready";
  const activeWorkerName =
    (activeWorker?.model_path || "").split(/[\\/]/).pop() ||
    activeWorker?.model_path ||
    null;

  return {
    loading, err, models,
    workers, activeWorkerId, res, vram,
    query, setQuery,
    sortKey, setSortKey,
    sortDir, setSortDir,
    busyPath,
    // advanced
    advOpen, setAdvOpen,
    adv, setAdv,
    advRemember, setAdvRemember,
    // computed
    hasReadyActiveWorker, activeWorkerName,
    // handlers
    handleLoad,
    handleKillWorker,
    handleActivateWorker,
  };
}
