import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, X } from "lucide-react";
import { getModels, loadModel, unloadModel, type ModelFile } from "../../api/models";
import ModelPickerList from "./ModelPickerList";

type Props = {
  open: boolean;
  onClose: () => void;
  onLoaded?: () => void; // called after successful load/unload
};

export default function ModelPicker({ open, onClose, onLoaded }: Props) {
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [models, setModels] = useState<ModelFile[]>([]);

  // current model status (name/path only for header)
  const [currentLoaded, setCurrentLoaded] = useState<boolean>(false);
  const [currentPath, setCurrentPath] = useState<string | null>(null);

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

  // Fetch models list when opened
  useEffect(() => {
    if (!open) return;
    mountedRef.current = true;

    (async () => {
      try {
        setErr(null);
        setLoading(true);
        const data = await getModels(); // expects /api/models
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
    })();

    return () => {
      mountedRef.current = false;
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
        resetDefaults: !manual,               // ← separate field, with comma
        }); // POST /api/models/load
      onLoaded?.();
      onClose();
    } catch (e: any) {
      setErr(e?.message || "Failed to load model");
    } finally {
      setBusyPath(null);
    }
  }

  async function handleUnload() {
    if (busyPath) return;
    setBusyPath("__unload__");
    setErr(null);
    try {
      await unloadModel(); // POST /api/models/unload
      onLoaded?.();
      onClose();
    } catch (e: any) {
      setErr(e?.message || "Failed to unload model");
    } finally {
      setBusyPath(null);
    }
  }

  const loadedName = (currentPath || "").split(/[\\/]/).pop() || null;

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

        {/* Current + manual toggle + eject */}
        <div className="px-3 py-2 border-b flex items-center justify-between">
          <div className="text-xs text-gray-600">
            {currentLoaded ? (
              <span className="inline-flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                Loaded:&nbsp;
                <b className="truncate max-w-[36ch]" title={loadedName || undefined}>
                  {loadedName}
                </b>
              </span>
            ) : (
              <span className="inline-flex items-center gap-2">
                <AlertCircle className="w-4 h-4 text-gray-500" />
                No model loaded
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            <label className="inline-flex items-center gap-2 text-xs select-none cursor-pointer">
              <input
                type="checkbox"
                checked={manual}
                onChange={(e) => setManual(e.target.checked)}
              />
              <span>
                Manually choose load parameters{" "}
                <span className="text-gray-400">(Alt+L)</span>
              </span>
            </label>
            <button
              onClick={handleUnload}
              disabled={!currentLoaded || !!busyPath}
              className={`text-xs px-3 py-1.5 rounded border ${
                !currentLoaded || busyPath ? "opacity-60 cursor-not-allowed" : "hover:bg-gray-100"
              }`}
              title={currentLoaded ? "Unload current model" : "No model loaded"}
            >
              Eject
            </button>
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
          onClose={onClose}
        />

        <div className="px-3 py-2 border-t text-[11px] text-gray-500">
          Press <b>Esc</b> to close · <b>Enter</b> loads the first filtered
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
