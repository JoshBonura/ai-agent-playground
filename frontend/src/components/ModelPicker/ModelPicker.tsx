import { useEffect, useRef, useState } from "react";
import { CheckCircle2, X } from "lucide-react";
import { getModels, loadModel, unloadModel, type ModelFile } from "../../api/models";
import ModelPickerList from "./ModelPickerList";
import { cancelModelLoad } from "../../api/models";
import { getJSON, postJSON } from "../../services/http";

// ✅ use the API's type + function (normalized shape)
import { getResources, type Resources as ApiResources } from "../../api/system";

type Props = {
  open: boolean;
  onClose: () => void;
  onLoaded?: () => void; // called after successful load/unload
};

/* ---------- local types for workers ---------- */

type WorkerHealth = {
  ok: boolean;
  model: string;
  path: string;
  n_ctx: number;
  n_threads: number;
  n_gpu_layers: number;
  n_batch: number;
} | null;

type WorkerRow = {
  id: string;
  port: number;
  model_path: string;
  status: "loading" | "ready" | "stopped";
  health?: WorkerHealth;
};

export default function ModelPicker({ open, onClose, onLoaded }: Props) {
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [models, setModels] = useState<ModelFile[]>([]);

  // current model status (name/path only for header)
  const [currentLoaded, setCurrentLoaded] = useState<boolean>(false);
  const [currentPath, setCurrentPath] = useState<string | null>(null);

  // workers + resources
  const [workers, setWorkers] = useState<WorkerRow[]>([]);
  const [activeWorkerId, setActiveWorkerId] = useState<string | null>(null);
  const [res, setRes] = useState<ApiResources | null>(null);

  // list UI state
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<"recency" | "size" | "name">("size");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [busyPath, setBusyPath] = useState<string | null>(null);

  // manual params
  const [manual, setManual] = useState(false);
  const [nCtx, setNCtx] = useState<string>("");
  const [nThreads, setNThreads] = useState<string>("");
  const [nGpuLayers, setNGpuLayers] = useState<string>("");
  const [nBatch, setNBatch] = useState<string>("");
  const [ropeFreqBase, setRopeFreqBase] = useState<string>("");
  const [ropeFreqScale, setRopeFreqScale] = useState<string>("");

  const mountedRef = useRef(false);

  // Initial fetch when opened + live polling for resources/workers/health
  useEffect(() => {
    if (!open) return;
    mountedRef.current = true;

    let alive = true;
    let t: any;

    const bootstrap = async () => {
      try {
        setErr(null);
        setLoading(true);
        const data = await getModels(); // GET /api/models (available + current + settings)
        if (!mountedRef.current) return;

        setModels(data.available || []);

        const cfg = (data.current?.config as any) || null;
        const path =
          (cfg?.config?.modelPath as string) ||
          (cfg?.modelPath as string) ||
          null;

        setCurrentPath(path);
        setCurrentLoaded(!!data.current?.loaded);
      } catch (e: any) {
        if (!mountedRef.current) return;
        setErr(e?.message || "Failed to load models");
      } finally {
        if (mountedRef.current) setLoading(false);
      }
    };

    const tick = async () => {
      try {
        // poll workers + resources while modal is open
        const [w, r] = await Promise.all([
          getJSON<{ ok: boolean; workers: WorkerRow[]; active: string | null }>("/api/model-workers/inspect"),
          getResources(), // ✅ normalized ApiResources
        ]);
        if (!alive) return;
        setWorkers(w?.workers ?? []);
        setActiveWorkerId(w?.active ?? null);

        // small smoothing to avoid CPU=0% flicker when instantaneous sample is idle
        setRes((prev) => ({
          ...(r || {}),
          cpuPct: r.cpuPct ?? prev?.cpuPct ?? null,
        }));
      } catch {
        if (!alive) return;
        setWorkers([]);
        setRes(null);
      } finally {
        t = setTimeout(tick, 30000);
      }
    };

    bootstrap().then(tick);

    return () => {
      mountedRef.current = false;
      clearTimeout(t);
      // keep UI state intact until next open
    };
  }, [open]);

  // Hotkey: Alt+L toggles manual panel (while modal open)
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.altKey && e.key.toLowerCase() === "l") {
        e.preventDefault();
        setManual((m) => !m);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  function parseNum(s: string): number | undefined {
    const t = s.trim();
    if (!t) return undefined;
    const v = Number(t);
    return Number.isFinite(v) ? v : undefined;
  }

  // Load into the single in-process runtime (mutually exclusive)
  async function handleLoad(m: ModelFile) {
    if (busyPath) return;
    setBusyPath(m.path);
    setErr(null);
    try {
      await loadModel({
        modelPath: m.path,
        nCtx: parseNum(nCtx),
        nThreads: parseNum(nThreads),
        nGpuLayers: parseNum(nGpuLayers),
        nBatch: parseNum(nBatch),
        ropeFreqBase: parseNum(ropeFreqBase) ?? null,
        ropeFreqScale: parseNum(ropeFreqScale) ?? null,
        resetDefaults: !manual,
      }); // POST /api/models/load (single-runtime)
      onLoaded?.();
      onClose();
    } catch (e: any) {
      setErr(e?.message || "Failed to load model");
    } finally {
      setBusyPath(null);
    }
  }

  // Spawn a parallel worker (lets you keep multiple models in VRAM—LM Studio style)
  async function handleSpawn(m: ModelFile) {
    if (busyPath) return;
    setBusyPath(`spawn:${m.path}`);
    setErr(null);
    try {
      await postJSON("/api/model-workers/spawn", { modelPath: m.path });
      onLoaded?.();
      // don't close — user may want to spawn more
    } catch (e: any) {
      setErr(e?.message || "Failed to spawn worker");
    } finally {
      setBusyPath(null);
    }
  }

  async function handleUnload() {
    if (busyPath) return;
    setBusyPath("__unload__");
    setErr(null);
    try {
      await unloadModel(); // POST /api/models/unload (single-runtime)
      onLoaded?.();
    } catch (e: any) {
      setErr(e?.message || "Failed to unload model");
    } finally {
      setBusyPath(null);
    }
  }

  async function handleCancelLoad() {
    try {
      await cancelModelLoad();
    } catch {
      // ignore
    } finally {
      setBusyPath(null);
      setErr(null);
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

  // NEW: activate a worker so the proxy targets it by default
  async function handleActivateWorker(id: string) {
    if (!id) return;
    try {
      await postJSON(`/api/model-workers/activate/${encodeURIComponent(id)}`, {});
      // refresh immediately so badge updates
      const w = await getJSON<{ ok: boolean; workers: WorkerRow[]; active: string | null }>(
        "/api/model-workers/inspect"
      );
      setWorkers(w?.workers ?? []);
      setActiveWorkerId(w?.active ?? null);
    } catch (e: any) {
      setErr(e?.message || "Failed to activate worker");
    }
  }

  const loadedName = (currentPath || "").split(/[\\/]/).pop() || null;

  // compute VRAM totals from normalized GPU list
  const vram = (() => {
    if (!res?.gpus?.length) return { used: null as number | null, total: null as number | null };
    const total = res.gpus.reduce((s, g) => s + (g.total || 0), 0);
    const used  = res.gpus.reduce((s, g) => s + (g.used  || 0), 0);
    return { used, total };
  })();

  // ---- Active worker readiness + label
  const activeWorker = workers.find((w) => w.id === activeWorkerId) || null;
  const hasReadyActiveWorker = !!activeWorkerId && !!activeWorker && activeWorker.status === "ready";
  const activeWorkerName =
    (activeWorker?.model_path || "").split(/[\\/]/).pop() ||
    activeWorker?.model_path ||
    null;

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[60] bg-black/40 flex items-start justify-center p-3">
      <div className="w-full max-w-3xl mt-8 rounded-2xl overflow-hidden bg-white shadow-xl border">
        {/* Header */}
        <div className="p-3 border-b bg-gray-50/60 flex items-center justify-between">
          <div className="font-medium text-sm">Select a model to load</div>
          <button
            onClick={onClose}
            className="inline-flex items-center gap-2 text-sm px-3 py-2 rounded-lg border hover:bg-gray-50"
            title="Close (Esc)"
          >
            <X className="w-4 h-4" />
            Close
          </button>
        </div>

        {/* Ready via worker banner */}
        {hasReadyActiveWorker && !currentLoaded && (
          <div className="px-3 pt-3">
            <div className="rounded-lg border bg-emerald-50 text-emerald-900 flex items-center justify-between p-3">
              <div className="flex items-center gap-2 min-w-0">
                <CheckCircle2 className="w-4 h-4 shrink-0" />
                <div className="text-sm truncate">
                  <b>Active worker ready</b>
                  {activeWorkerName ? (
                    <>
                      : <span className="truncate align-middle">{activeWorkerName}</span>
                    </>
                  ) : null}
                </div>
              </div>
              <button
                className="text-xs px-3 py-1.5 rounded border border-emerald-300 hover:bg-emerald-100"
                onClick={() => {
                  onLoaded?.();
                  onClose();
                }}
                title="Close and start chatting using the active worker"
              >
                Use active worker
              </button>
            </div>
          </div>
        )}

        {/* Resource bar (normalized fields) */}
        <div className="px-3 py-2 border-b text-xs flex items-center gap-4 bg-gray-50/60">
          <span>
            CPU:&nbsp;
            <b>{res?.cpuPct != null ? `${res.cpuPct}%` : "—"}</b>
          </span>
          <span>
            RAM:&nbsp;
            <b>{fmtGB(res?.ram?.used)} / {fmtGB(res?.ram?.total)}</b>
          </span>
          <span>
            VRAM:&nbsp;
            <b>
              {fmtGB(vram.used)} / {fmtGB(vram.total)}
              {res?.gpus?.length ? ` (${res.gpus.map((g) => g.name).join(", ")})` : ""}
            </b>
          </span>
        </div>

        {/* Currently Loaded (single runtime) + workers */}
        <div className="px-3 py-2 border-b">
          <div className="text-xs font-medium mb-2">Currently Loaded</div>
          <div className="space-y-2">
            {currentLoaded ? (
              <div className="rounded-lg border p-3 flex items-center justify-between bg-indigo-50/40">
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate" title={loadedName || undefined}>
                    {loadedName}
                  </div>
                  <div className="text-xs text-gray-600">
                    GGUF (main runtime)
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleUnload}
                    disabled={!!busyPath}
                    className={`text-xs px-3 py-1.5 rounded border ${busyPath ? "opacity-60 cursor-not-allowed" : "hover:bg-gray-100"}`}
                    title="Unload from main runtime"
                  >
                    Eject
                  </button>
                  {busyPath && (
                    <button
                      onClick={handleCancelLoad}
                      className="text-xs px-3 py-1.5 rounded border hover:bg-gray-100"
                      title="Cancel in-progress load"
                    >
                      Cancel load
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <div className="text-xs text-gray-600">Nothing in main runtime.</div>
            )}

            {/* Worker rows */}
            {workers
              .filter((w) => w.status !== "stopped")
              .map((w) => {
                const h = w.health;
                const title = (h?.model || w.model_path.split(/[\\/]/).pop() || w.model_path);
                const isActive = w.id === activeWorkerId;
                return (
                  <div key={w.id} className="rounded-lg border p-3 flex items-center justify-between bg-violet-50/40">
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate" title={title}>
                        {title}
                      </div>
                      <div className="text-xs text-gray-600">
                        ctx={h?.n_ctx ?? "—"} · gpuLayers={h?.n_gpu_layers ?? "—"} · batch={h?.n_batch ?? "—"} · port={w.port}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {isActive ? (
                        <span className="text-[10px] px-2 py-1 rounded-full bg-emerald-100 text-emerald-700 border border-emerald-200">
                          active
                        </span>
                      ) : (
                        <button
                          onClick={() => handleActivateWorker(w.id)}
                          className="text-xs px-3 py-1.5 rounded border hover:bg-gray-100"
                          title="Make this the default worker"
                        >
                          Activate
                        </button>
                      )}
                      <button
                        onClick={() => handleKillWorker(w.id)}
                        className="text-xs px-3 py-1.5 rounded border hover:bg-gray-100"
                        title="Stop worker (frees VRAM)"
                      >
                        Eject
                      </button>
                    </div>
                  </div>
                );
              })}
            {!currentLoaded && workers.filter((w) => w.status !== "stopped").length === 0 && (
              <div className="text-xs text-gray-600">Nothing loaded.</div>
            )}
          </div>
        </div>

        {/* Manual params */}
        {manual && (
          <div className="px-3 py-3 border-b grid grid-cols-2 gap-3 bg-gray-50/50">
            <NumberField label="Context (nCtx)" value={nCtx} setValue={setNCtx} placeholder="4096" />
            <NumberField label="Threads (nThreads)" value={nThreads} setValue={setNThreads} placeholder="8" />
            <NumberField label="GPU Layers (nGpuLayers)" value={nGpuLayers} setValue={setNGpuLayers} placeholder="40" />
            <NumberField label="Batch (nBatch)" value={nBatch} setValue={setNBatch} placeholder="256" />
            <NumberField label="ropeFreqBase" value={ropeFreqBase} setValue={setRopeFreqBase} placeholder="(optional)" />
            <NumberField label="ropeFreqScale" value={ropeFreqScale} setValue={setRopeFreqScale} placeholder="(optional)" />
          </div>
        )}

        {/* List + search/sort */}
        <ModelPickerList
          loading={loading}
          err={err}
          models={models}
          query={query}
          setQuery={setQuery}
          sortKey={sortKey}
          setSortKey={setSortKey}
          sortDir={sortDir}
          setSortDir={setSortDir}
          busyPath={busyPath}
          onLoad={handleLoad}
          onSpawn={handleSpawn}
          onClose={onClose}
        />

        <div className="px-3 py-2 border-t text-[11px] text-gray-500">
          Press <b>Esc</b> to close · <b>Enter</b> loads the first filtered
          {hasReadyActiveWorker && !currentLoaded ? (
            <>
              {" "}
              · Active worker is ready — you can close and start chatting.
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function NumberField({
  label,
  value,
  setValue,
  placeholder,
}: {
  label: string;
  value: string;
  setValue: (s: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="text-xs block">
      <div className="mb-1 text-gray-600">{label}</div>
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        inputMode="numeric"
        className="w-full px-2 py-1.5 rounded border text-sm"
        placeholder={placeholder}
      />
    </label>
  );
}

function fmtGB(n?: number | null) {
  if (n == null) return "—";
  return (n / (1024 ** 3)).toFixed(2) + " GB";
}
