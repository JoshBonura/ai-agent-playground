// frontend/src/components/ModelPicker/ModelPickerView.tsx
import { CheckCircle2, X } from "lucide-react";
import ModelPickerList from "./ModelPickerList";
import type { ModelFile } from "../../api/models";
import type { SortDir, SortKey, WorkerRow } from "./useModelPicker";
import type { Dispatch, SetStateAction } from "react";
import type { LlamaKwargs } from "../../api/modelWorkers";
import { useI18n } from "../../i18n/i18n";

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
  /** per-row busy list */
  busyPaths: string[];
  setQuery: Dispatch<SetStateAction<string>>;
  setSortKey: Dispatch<SetStateAction<SortKey>>;
  setSortDir: Dispatch<SetStateAction<SortDir>>;

  // per-row inline advanced panel state
  expandedPath: string | null;
  setExpandedPath: Dispatch<SetStateAction<string | null>>;
  advDraft: LlamaKwargs;
  setAdvDraft: Dispatch<SetStateAction<LlamaKwargs>>;
  rememberAdv: boolean;
  setRememberAdv: (b: boolean) => void;

  // actions
  onLoad: (m: ModelFile) => void;
  onLoadAdvanced: (m: ModelFile) => void;
  onKillWorker: (id: string) => void;
  onActivateWorker: (id: string) => void;
};

export default function ModelPickerView(p: Props) {
  const { t } = useI18n();

  if (!p.open) return null;

  const vramLabel = `${fmtGB(p.vramUsed)} / ${fmtGB(p.vramTotal)}${
    p.gpuNames.length ? ` (${p.gpuNames.join(", ")})` : ""
  }`;

  return (
    <div className="fixed inset-0 z-[60] bg-black/40 flex items-start justify-center p-3">
      <div className="w-full max-w-3xl mt-8 rounded-2xl overflow-hidden bg-white shadow-xl border">
        {/* Header */}
        <div className="p-3 border-b bg-gray-50/60 flex items-center justify-between">
          <div className="font-medium text-sm">{t("modelPicker.header")}</div>
          <button
            onClick={p.onClose}
            className="inline-flex items-center gap-2 text-sm px-3 py-2 rounded-lg border hover:bg-gray-50"
            title={t("common.close")}
          >
            <X className="w-4 h-4" />
            {t("common.close")}
          </button>
        </div>

        {/* Ready via worker banner */}
        {p.hasReadyActiveWorker && (
          <div className="px-3 pt-3">
            <div className="rounded-lg border bg-emerald-50 text-emerald-900 flex items-center justify-between p-3">
              <div className="flex items-center gap-2 min-w-0">
                <CheckCircle2 className="w-4 h-4 shrink-0" />
                <div className="text-sm truncate">
                  <b>{t("modelPicker.active_ready")}</b>
                  {p.activeWorkerName ? (
                    <>
                      {t("modelPicker.ready_name_sep")}
                      <span className="truncate align-middle">{p.activeWorkerName}</span>
                    </>
                  ) : null}
                </div>
              </div>
              <button
                className="text-xs px-3 py-1.5 rounded border border-emerald-300 hover:bg-emerald-100"
                onClick={p.onClose}
                title={t("modelPicker.use_active")}
              >
                {t("modelPicker.use_active")}
              </button>
            </div>
          </div>
        )}

        {/* Resource bar */}
        <div className="px-3 py-2 border-b text-xs flex items-center gap-4 bg-gray-50/60">
          <span>
            {t("common.cpu")}:&nbsp;
            <b>{p.cpuPct != null ? `${p.cpuPct}%` : t("common.none")}</b>
          </span>
          <span>
            {t("common.ram")}:&nbsp;
            <b>
              {fmtGB(p.ramUsed)} / {fmtGB(p.ramTotal)}
            </b>
          </span>
          <span>
            {t("common.vram")}:&nbsp;
            <b>{vramLabel}</b>
          </span>
        </div>

        {/* Workers list */}
        <div className="px-3 py-2 border-b">
          <div className="text-xs font-medium mb-2">{t("modelPicker.workers_title")}</div>
          <div className="space-y-2">
            {p.workers
              .filter((w) => w.status !== "stopped")
              .map((w) => {
                const h = w.health;
                const title = h?.model || w.model_path.split(/[\\/]/).pop() || w.model_path;
                const isActive = w.id === p.activeWorkerId;
                const pct =
                  (h as any)?.progress && typeof (h as any).progress.pct === "number"
                    ? (h as any).progress.pct
                    : null;

                const isLoading = w.status === "loading";

                return (
                    <div
                    key={`${w.id}:${w.port}`}  // prevent duplicate-key warnings if a backend glitch repeats an id
                    className="rounded-lg border p-3 flex items-center justify-between bg-violet-50/40"
                    >
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate" title={title}>
                        {title}
                      </div>
                      <div className="text-xs text-gray-600">
                        ctx={h?.n_ctx ?? "—"} · gpuLayers={h?.n_gpu_layers ?? "—"} · batch={h?.n_batch ?? "—"} · port=
                        {w.port}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {/* Loading progress pill (if spawning/initializing) */}
                      {isLoading && (
                        <span className="text-[10px] px-2 py-1 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200">
                          {`Loading…${typeof pct === "number" ? ` ${pct}%` : ""}`}
                        </span>
                      )}
                      {/* Active/Activate — hide Activate while loading */}
                      {isActive ? (
                        <span className="text-[10px] px-2 py-1 rounded-full bg-emerald-100 text-emerald-700 border border-emerald-200">
                          {t("modelPicker.worker_active")}
                        </span>
                      ) : isLoading ? null : (
                        <button
                          onClick={() => p.onActivateWorker(w.id)}
                          className="text-xs px-3 py-1.5 rounded border hover:bg-gray-100"
                          title={t("modelPicker.worker_activate")}
                        >
                          {t("modelPicker.worker_activate")}
                        </button>
                      )}
                      {/* Eject */}
                      <button
                        onClick={() => {
                          // High-res click timing: complements useModelPicker kill:* logs
                          console.debug("[UI] Eject clicked", {
                            id: w.id,
                            status: w.status,
                            model_path: w.model_path,
                            tISO: new Date().toISOString(),
                            tMs: performance.now().toFixed(1),
                          });
                          p.onKillWorker(w.id);
                        }}
                        className="text-xs px-3 py-1.5 rounded border hover:bg-gray-100"
                        title={t("modelPicker.worker_eject_title")}
                      >
                        {t("modelPicker.worker_eject")}
                      </button>
                    </div>
                  </div>
                );
              })}
            {p.workers.filter((w) => w.status !== "stopped").length === 0 && (
              <div className="text-xs text-gray-600">{t("modelPicker.nothing_loaded")}</div>
            )}
          </div>
        </div>

        {/* Model list */}
        <ModelPickerList
          loading={p.loading}
          err={p.err}
          models={p.models}
          // ⬇️ removed `workers={p.workers}` — the list no longer needs it
          query={p.query}
          setQuery={p.setQuery}
          sortKey={p.sortKey}
          setSortKey={p.setSortKey}
          sortDir={p.sortDir}
          setSortDir={p.setSortDir}
          busyPaths={p.busyPaths}
          onLoad={p.onLoad}
          expandedPath={p.expandedPath}
          setExpandedPath={p.setExpandedPath}
          advDraft={p.advDraft}
          setAdvDraft={p.setAdvDraft}
          rememberAdv={p.rememberAdv}
          setRememberAdv={p.setRememberAdv}
          onLoadAdvanced={p.onLoadAdvanced}
          onClose={p.onClose}
        />

        <div className="px-3 py-2 border-t text-[11px] text-gray-500">
          {t("modelPicker.footer_hint")}
        </div>
      </div>
    </div>
  );
}

function fmtGB(n?: number | null) {
  if (n == null) return "—";
  return (n / 1024 ** 3).toFixed(2) + " GB";
}
