import { useModelPicker } from "./useModelPicker";
import ModelPickerView from "./ModelPickerView";

export default function ModelPicker({
  open,
  onClose,
  onLoaded,
}: {
  open: boolean;
  onClose: () => void;
  onLoaded?: () => void;
}) {
  const s = useModelPicker(open, onLoaded, onClose);

  const cpuPct = s.res?.cpuPct;
  const ramUsed = s.res?.ram?.used ?? null;
  const ramTotal = s.res?.ram?.total ?? null;
  const gpuNames = s.res?.gpus?.map((g) => g.name) ?? [];

  return (
    <ModelPickerView
      open={open}
      onClose={onClose}
      loading={s.loading}
      err={s.err}
      models={s.models}
      // no more main-runtime
      workers={s.workers}
      activeWorkerId={s.activeWorkerId}
      cpuPct={cpuPct}
      ramUsed={ramUsed}
      ramTotal={ramTotal}
      vramUsed={s.vram.used}
      vramTotal={s.vram.total}
      gpuNames={gpuNames}
      hasReadyActiveWorker={s.hasReadyActiveWorker}
      activeWorkerName={s.activeWorkerName}
      // list controls
      query={s.query}
      setQuery={s.setQuery}
      sortKey={s.sortKey}
      setSortKey={s.setSortKey}
      sortDir={s.sortDir}
      setSortDir={s.setSortDir}
      busyPath={s.busyPath}
      // advanced
      advOpen={s.advOpen}
      setAdvOpen={s.setAdvOpen}
      adv={s.adv}
      setAdv={s.setAdv}
      advRemember={s.advRemember}
      setAdvRemember={s.setAdvRemember}
      // actions
      onLoad={s.handleLoad}          // ← spawns a worker now
      onKillWorker={s.handleKillWorker}
      onActivateWorker={s.handleActivateWorker}
    />
  );
}
