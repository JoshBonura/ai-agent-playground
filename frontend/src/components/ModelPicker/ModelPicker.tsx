// frontend/src/components/ModelPicker/ModelPicker.tsx
import { useEffect, useState } from "react";
import { useModelPicker } from "./useModelPicker";
import ModelPickerView from "./ModelPickerView";
import type { ModelFile } from "../../api/models";

export default function ModelPicker({ open, onClose, onLoaded }: {
  open: boolean;
  onClose: () => void;
  onLoaded?: () => void;
}) {
  const s = useModelPicker(open, onLoaded, onClose);

  const [expandedPath, setExpandedPath] = useState<string | null>(null);

  useEffect(() => {
    if (!open) setExpandedPath(null);
  }, [open]);

  async function handleLoadAdvanced(m: ModelFile) {
    // `s.adv` is already what the panel edits; just use the normal load
    await s.handleLoad(m);
    onLoaded?.();
    onClose();
  }

  return (
    <ModelPickerView
      open={open}
      onClose={onClose}
      // data
      loading={s.loading}
      err={s.err}
      models={s.models}
      workers={s.workers}
      activeWorkerId={s.activeWorkerId}
      cpuPct={s.res?.cpuPct}
      ramUsed={s.res?.ram?.used ?? null}
      ramTotal={s.res?.ram?.total ?? null}
      vramUsed={s.vram.used}
      vramTotal={s.vram.total}
      gpuNames={s.res?.gpus?.map(g => g.name) ?? []}
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

      // inline Advanced state — use the hook’s state directly
      expandedPath={expandedPath}
      setExpandedPath={setExpandedPath}
      advDraft={s.adv}
      setAdvDraft={s.setAdv}
      rememberAdv={s.advRemember}
      setRememberAdv={s.setAdvRemember}

      // actions
      onLoad={s.handleLoad}                 // quick load (defaults or whatever s.adv is)
      onLoadAdvanced={handleLoadAdvanced}   // same, just closes after
      onKillWorker={s.handleKillWorker}
      onActivateWorker={s.handleActivateWorker}
    />
  );
}
