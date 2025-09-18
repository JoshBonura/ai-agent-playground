import { CheckCircle2, X } from "lucide-react";
import ModelPickerList from "./ModelPickerList";
import WorkerAdvancedPanel from "./WorkerAdvancedPanel";
import type { ModelFile } from "../../api/models";
import type { SortDir, SortKey, WorkerRow } from "./useModelPicker";
import type { Dispatch, SetStateAction } from "react";
import type { LlamaKwargs } from "../../api/modelWorkers";

type Props = {
  open: boolean;
  onClose: () => void;

  // list + data
  loading: boolean;
  err: string | null;
  models: ModelFile[];
  workers: WorkerRow[];
  activeWorkerId: string | null;

  cpuPct: number | null | undefined;
  ramUsed: number | null | undefined;
  ramTotal: number | null | undefined;
  vramUsed: number | null;
  vramTotal: number | null;
  gpuNames: string[];

  hasReadyActiveWorker: boolean;
  activeWorkerName: string | null;

  // list controls
  query: string;
  sortKey: SortKey;
  sortDir: SortDir;
  busyPath: string | null;
  setQuery: Dispatch<SetStateAction<string>>;
  setSortKey: Dispatch<SetStateAction<SortKey>>;
  setSortDir: Dispatch<SetStateAction<SortDir>>;

  // advanced worker args
  advOpen: boolean;
  setAdvOpen: (b: boolean) => void;
  adv: LlamaKwargs;
  setAdv: (next: LlamaKwargs) => void;
  advRemember: boolean;
  setAdvRemember: (b: boolean) => void;

  // actions
  onLoad: (m: ModelFile) => void;    // Load = spawn
  onKillWorker: (id: string) => void;
  onActivateWorker: (id: string) => void;
};

export default function ModelPickerView(p: Props) {
  if (!p.open) return null;

  const vramLabel = `${fmtGB(p.vramUsed)} / ${fmtGB(p.vramTotal)}${
    p.gpuNames.length ? ` (${p.gpuNames.join(", ")})` : ""
  }`;

  return (
    <div className="fixed inset-0 z-[60] bg-black/40 flex items-start justify-center p-3">
      <div className="w-full max-w-3xl mt-8 rounded-2xl overflow-hidden bg-white shadow-xl border">
        {/* Header */}
        <div className="p-3 border-b bg-gray-50/60 flex items-center justify-between">
          <div className="font-medium text-sm">Select a model to load</div>
          <button
            onClick={p.onClose}
            className="inline-flex items-center gap-2 text-sm px-3 py-2 rounded-lg border hover:bg-gray-50"
            title="Close (Esc)"
          >
            <X className="w-4 h-4" />
            Close
          </button>
        </div>

        {/* Ready via worker banner */}
        {p.hasReadyActiveWorker && (
          <div className="px-3 pt-3">
            <div className="rounded-lg border bg-emerald-50 text-emerald-900 flex items-center justify-between p-3">
              <div className="flex items-center gap-2 min-w-0">
                <CheckCircle2 className="w-4 h-4 shrink-0" />
                <div className="text-sm truncate">
                  <b>Active worker ready</b>
                  {p.activeWorkerName ? <>: <span className="truncate align-middle">{p.activeWorkerName}</span></> : null}
                </div>
              </div>
              <button
                className="text-xs px-3 py-1.5 rounded border border-emerald-300 hover:bg-emerald-100"
                onClick={p.onClose}
                title="Close and start chatting using the active worker"
              >
                Use active worker
              </button>
            </div>
          </div>
        )}

        {/* Resource bar + Advanced toggle */}
        <div className="px-3 py-2 border-b text-xs flex items-center justify-between bg-gray-50/60">
          <div className="flex items-center gap-4">
            <span>CPU:&nbsp;<b>{p.cpuPct != null ? `${p.cpuPct}%` : "—"}</b></span>
            <span>RAM:&nbsp;<b>{fmtGB(p.ramUsed)} / {fmtGB(p.ramTotal)}</b></span>
            <span>VRAM:&nbsp;<b>{vramLabel}</b></span>
          </div>
          <button
            className="text-[11px] px-2 py-1 rounded border hover:bg-gray-100"
            onClick={() => p.setAdvOpen(!p.advOpen)}
            title="Show advanced worker settings"
          >
            {p.advOpen ? "Hide advanced" : "Advanced…"}
          </button>
        </div>

        {/* Advanced worker settings */}
        {p.advOpen && (
          <WorkerAdvancedPanel
            modelKey={null}
            value={p.adv}
            onChange={p.setAdv}
            remember={p.advRemember}
            setRemember={p.setAdvRemember}
          />
        )}

        {/* Workers list */}
        <div className="px-3 py-2 border-b">
          <div className="text-xs font-medium mb-2">Workers</div>
          <div className="space-y-2">
            {p.workers
              .filter((w) => w.status !== "stopped")
              .map((w) => {
                const h = w.health;
                const title = h?.model || w.model_path.split(/[\\/]/).pop() || w.model_path;
                const isActive = w.id === p.activeWorkerId;
                return (
                  <div key={w.id} className="rounded-lg border p-3 flex items-center justify-between bg-violet-50/40">
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate" title={title}>{title}</div>
                      <div className="text-xs text-gray-600">
                        ctx={h?.n_ctx ?? "—"} · gpuLayers={h?.n_gpu_layers ?? "—"} · batch={h?.n_batch ?? "—"} · port={w.port}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {isActive ? (
                        <span className="text-[10px] px-2 py-1 rounded-full bg-emerald-100 text-emerald-700 border border-emerald-200">active</span>
                      ) : (
                        <button
                          onClick={() => p.onActivateWorker(w.id)}
                          className="text-xs px-3 py-1.5 rounded border hover:bg-gray-100"
                          title="Make this the default worker"
                        >
                          Activate
                        </button>
                      )}
                      <button
                        onClick={() => p.onKillWorker(w.id)}
                        className="text-xs px-3 py-1.5 rounded border hover:bg-gray-100"
                        title="Stop worker (frees VRAM)"
                      >
                        Eject
                      </button>
                    </div>
                  </div>
                );
              })}
            {p.workers.filter((w) => w.status !== "stopped").length === 0 && (
              <div className="text-xs text-gray-600">Nothing loaded.</div>
            )}
          </div>
        </div>

        {/* Model list (Load spawns) */}
        <ModelPickerList
          loading={p.loading}
          err={p.err}
          models={p.models}
          query={p.query}
          setQuery={p.setQuery}
          sortKey={p.sortKey}
          setSortKey={p.setSortKey}
          sortDir={p.sortDir}
          setSortDir={p.setSortDir}
          busyPath={p.busyPath}
          onLoad={p.onLoad}
          onClose={p.onClose}
        />

        <div className="px-3 py-2 border-t text-[11px] text-gray-500">
          Press <b>Esc</b> to close · <b>Enter</b> loads the first filtered
        </div>
      </div>
    </div>
  );
}

function fmtGB(n?: number | null) {
  if (n == null) return "—";
  return (n / 1024 ** 3).toFixed(2) + " GB";
}
