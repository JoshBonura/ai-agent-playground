// frontend/src/components/ModelPicker/ModelPicker.tsx
import { useEffect, useState } from "react";
import { useModelPicker } from "./useModelPicker";
import ModelPickerView from "./ModelPickerView";
import type { LlamaKwargs } from "../../api/modelWorkers";
import type { ModelFile } from "../../api/models";

export default function ModelPicker({
  open,
  onClose,
  onLoaded,
}: {
  open: boolean;
  onClose: () => void;
  onLoaded?: () => void;
}) {
  // Centralized data, workers, and basic load action
  const s = useModelPicker(open, onLoaded, onClose);

  // --- Local state for the per-row advanced panel (UI-only bridge) ---
  const [expandedPath, setExpandedPath] = useState<string | null>(null);
  const [advDraft, setAdvDraft] = useState<LlamaKwargs>({});
  const [rememberAdv, setRememberAdv] = useState<boolean>(false);

  // Reset inline advanced panel when the modal closes
  useEffect(() => {
    if (!open) {
      setExpandedPath(null);
      // keep advDraft/rememberAdv so settings persist across open/close
    }
  }, [open]);

  // If/when your hook supports advanced kwargs, call that here.
  async function handleLoadAdvanced(m: ModelFile) {
    await s.handleLoad(m); // current behavior: load with defaults
    onLoaded?.();
    onClose();
  }

  const cpuPct = s.res?.cpuPct;
  const ramUsed = s.res?.ram?.used ?? null;
  const ramTotal = s.res?.ram?.total ?? null;
  const gpuNames = s.res?.gpus?.map((g) => g.name) ?? [];

  return (
    <ModelPickerView
      open={open}
      onClose={onClose}
      // state
      loading={s.loading}
      err={s.err}
      models={s.models}
      workers={s.workers}
      activeWorkerId={s.activeWorkerId}
      // resources
      cpuPct={cpuPct}
      ramUsed={ramUsed}
      ramTotal={ramTotal}
      vramUsed={s.vram.used}
      vramTotal={s.vram.total}
      gpuNames={gpuNames}
      // active worker banner
      hasReadyActiveWorker={s.hasReadyActiveWorker}
      activeWorkerName={s.activeWorkerName}
      // list controls
      query={s.query}
      setQuery={s.setQuery}
      sortKey={s.sortKey}
      setSortKey={s.setSortKey}
      sortDir={s.sortDir}
      setSortDir={s.setSortDir}
      busyPaths={s.busyPaths}  
      // per-row inline Advanced state
      expandedPath={expandedPath}
      setExpandedPath={setExpandedPath}
      advDraft={advDraft}
      setAdvDraft={setAdvDraft}
      rememberAdv={rememberAdv}
      setRememberAdv={setRememberAdv}
      // actions
      onLoad={s.handleLoad}               // quick load (defaults)
      onLoadAdvanced={handleLoadAdvanced} // load using advDraft (hook wiring later)
      onKillWorker={s.handleKillWorker}
      onActivateWorker={s.handleActivateWorker}
    />
  );
}
