// frontend/src/components/ModelPicker/WorkerAdvancedPanel.tsx
import { useEffect, useMemo, useRef } from "react";
import { useI18n } from "../../i18n/i18n";
import type { LlamaKwargs } from "../../api/modelWorkers";
import type { ModelsCapabilities } from "../../api/models";

type Props = {
  modelKey?: string | null;
  value: LlamaKwargs;
  onChange: (next: LlamaKwargs) => void;
  remember: boolean;
  setRemember: (b: boolean) => void;
  caps?: ModelsCapabilities | null; // NEW
};

const KVTYPES = [
  "auto",
  "f32",
  "f16",
  "q8_0",
  "q4_0",
  "q4_1",
  "iq4_nl",
  "q5_0",
  "q5_1",
] as const;

/* ---------- helpers ---------- */
function toInt(n?: number) {
  return typeof n === "number" && Number.isFinite(n) ? Math.trunc(n) : undefined;
}
function parseNum(v: string): number | undefined {
  const t = v.trim();
  if (!t) return;
  const n = Number(t);
  return Number.isFinite(n) ? n : undefined;
}
function parseIntish(v: string): number | undefined {
  return toInt(parseNum(v));
}
function sanitizeKey(k: string) {
  const last = k.split(/[\\/]/).pop() || k;
  return encodeURIComponent(last.toLowerCase());
}

const QUANTIZED_V = new Set(["q8_0", "q4_0", "q4_1", "q5_0", "q5_1", "iq4_nl"]);
const isQuantizedV = (s?: string) => !!s && QUANTIZED_V.has(s.toLowerCase());

/* ---------- component ---------- */
export default function WorkerAdvancedPanel({
  modelKey,
  value,
  onChange,
  remember,
  setRemember,
  caps,
}: Props) {
  const { t } = useI18n();

  const storageKey = useMemo(
    () => `lm/adv/${modelKey ? sanitizeKey(modelKey) : "_default_"}`,
    [modelKey],
  );

  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) onChange({ ...value, ...(JSON.parse(raw) as LlamaKwargs) });
    } catch {
      /* ignore */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);

  // ---- caps-derived facts & smart placeholders ----
  const maxTokensEff = caps?.maxTokens?.effective ?? null;
  const maxTokensHdr = caps?.maxTokens?.header ?? null;
  const cpuThreads = caps?.cpu?.threads ?? null;
  const offloadLayers = caps?.gpu?.offloadLayers ?? null;
  const kvOff = caps?.gpu?.kvOffload ?? null;
  const accel = caps?.gpu?.accel ?? null;

  // Prefer effective value; use header as fallback if effective is null
  const nCtxPlaceholder =
    value.n_ctx != null
      ? undefined
      : (maxTokensEff ?? maxTokensHdr ?? undefined)?.toString();

  const nThreadsPlaceholder =
    value.n_threads != null ? undefined : (cpuThreads ?? undefined)?.toString();

  const nGpuLayersPlaceholder =
    value.n_gpu_layers != null
      ? undefined
      : (offloadLayers ?? undefined)?.toString();

  // ---- flash/quantized V guidance ----
  const needsFlashForV = isQuantizedV(value.type_v);

  const flashTitle =
    needsFlashForV && !value.flash_attn
      ? t("workerAdvanced.flash_attn.tip") +
        " — " +
        t("workerAdvanced.type_v.flashRequired")
      : t("workerAdvanced.flash_attn.tip");

  const typeVTitle =
    t("workerAdvanced.type_v.tip") +
    (needsFlashForV ? " — " + t("workerAdvanced.type_v.flashRequired") : "");

  const onTypeVChange = (v: string) => {
    const next = v === "auto" ? undefined : v;
    const patch: Partial<LlamaKwargs> = { type_v: next };
    if (isQuantizedV(next)) patch.flash_attn = true; // auto-enable
    set(patch);
  };

  const saveTimer = useRef<number | null>(null);
  useEffect(() => {
    if (!remember) return;
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      try {
        localStorage.setItem(storageKey, JSON.stringify(value || {}));
      } catch {}
    }, 250);
    return () => {
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
    };
  }, [remember, value, storageKey]);

  const set = (patch: Partial<LlamaKwargs>) => onChange({ ...value, ...patch });

  const onReset = () => {
    onChange({});
    try {
      localStorage.removeItem(storageKey);
    } catch {}
  };

  return (
    <div className="px-3 py-3 border-b grid grid-cols-1 md:grid-cols-2 gap-3 bg-gray-50/50">
      {/* --- live capabilities summary --- */}
      {caps && (
        <div className="md:col-span-2 -mt-1 -mb-1">
          <div className="flex flex-wrap gap-2 text-[11px] text-gray-700">
            <span className="px-2 py-1 rounded border bg-white/70">
              Max tokens:{" "}
              <strong>{maxTokensEff ?? maxTokensHdr ?? "?"}</strong>
              {maxTokensEff &&
                maxTokensHdr &&
                maxTokensEff !== maxTokensHdr && (
                  <span className="ml-1 text-gray-500">
                    (train: {maxTokensHdr})
                  </span>
                )}
            </span>
            <span className="px-2 py-1 rounded border bg-white/70">
              CPU threads: <strong>{cpuThreads ?? "?"}</strong>
            </span>
            <span className="px-2 py-1 rounded border bg-white/70">
              GPU offload layers: <strong>{offloadLayers ?? "?"}</strong>
              {typeof kvOff === "boolean" && (
                <span
                  className={`ml-2 px-1.5 py-0.5 rounded border ${
                    kvOff
                      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                      : "bg-gray-50 text-gray-600"
                  }`}
                >
                  KV {kvOff ? "on-GPU" : "on-CPU"}
                </span>
              )}
              {accel && <span className="ml-2 text-gray-500">({accel})</span>}
            </span>
          </div>
        </div>
      )}

      {/* --- tunables --- */}
      <Field
        id="adv-nctx"
        label={t("workerAdvanced.n_ctx.label")}
        placeholder={nCtxPlaceholder || "4096"}
        value={value.n_ctx?.toString() ?? ""}
        onChange={(s) => set({ n_ctx: parseIntish(s) })}
        title={t("workerAdvanced.n_ctx.tip")}
      />
      <Field
        id="adv-ngpulayers"
        label={t("workerAdvanced.n_gpu_layers.label")}
        placeholder={nGpuLayersPlaceholder || "36"}
        value={value.n_gpu_layers?.toString() ?? ""}
        onChange={(s) => set({ n_gpu_layers: parseIntish(s) })}
        title={t("workerAdvanced.n_gpu_layers.tip")}
      />
      <Field
        id="adv-nthreads"
        label={t("workerAdvanced.n_threads.label")}
        placeholder={nThreadsPlaceholder || "8"}
        value={value.n_threads?.toString() ?? ""}
        onChange={(s) => set({ n_threads: parseIntish(s) })}
        title={t("workerAdvanced.n_threads.tip")}
      />
      <Field
        id="adv-nbatch"
        label={t("workerAdvanced.n_batch.label")}
        placeholder="512"
        value={value.n_batch?.toString() ?? ""}
        onChange={(s) => set({ n_batch: parseIntish(s) })}
        title={t("workerAdvanced.n_batch.tip")}
      />

      <Field
        id="adv-ropebase"
        label={t("workerAdvanced.rope_freq_base.label")}
        placeholder={t("common.optional")}
        value={value.rope_freq_base?.toString() ?? ""}
        onChange={(s) => set({ rope_freq_base: parseNum(s) })}
        title={t("workerAdvanced.rope_freq_base.tip")}
      />
      <Field
        id="adv-ropescale"
        label={t("workerAdvanced.rope_freq_scale.label")}
        placeholder={t("common.optional")}
        value={value.rope_freq_scale?.toString() ?? ""}
        onChange={(s) => set({ rope_freq_scale: parseNum(s) })}
        title={t("workerAdvanced.rope_freq_scale.tip")}
      />

      <Toggle
        id="adv-flash"
        label={t("workerAdvanced.flash_attn.label")}
        title={flashTitle}
        checked={!!value.flash_attn}
        onChange={(b) => set({ flash_attn: b })}
      />
      <Toggle
        id="adv-mmap"
        label={t("workerAdvanced.use_mmap.label")}
        title={t("workerAdvanced.use_mmap.tip")}
        checked={!!value.use_mmap}
        onChange={(b) => set({ use_mmap: b })}
      />
      <Toggle
        id="adv-mlock"
        label={t("workerAdvanced.use_mlock.label")}
        title={t("workerAdvanced.use_mlock.tip")}
        checked={!!value.use_mlock}
        onChange={(b) => set({ use_mlock: b })}
      />
      <Toggle
        id="adv-kvoff"
        label={t("workerAdvanced.kv_offload.label")}
        title={t("workerAdvanced.kv_offload.tip")}
        checked={!!value.kv_offload}
        onChange={(b) => set({ kv_offload: b })}
      />

      <Field
        id="adv-seed"
        label={t("workerAdvanced.seed.label")}
        placeholder={t("common.optional")}
        value={value.seed?.toString() ?? ""}
        onChange={(s) => set({ seed: parseIntish(s) })}
        title={t("workerAdvanced.seed.tip")}
      />

      <Select
        id="adv-typek"
        label={t("workerAdvanced.type_k.label")}
        title={t("workerAdvanced.type_k.tip")}
        value={value.type_k ?? "auto"}
        onChange={(v) => set({ type_k: v === "auto" ? undefined : v })}
      />
      <Select
        id="adv-typev"
        label={t("workerAdvanced.type_v.label")}
        title={typeVTitle}
        value={value.type_v ?? "auto"}
        onChange={onTypeVChange}
      />

      {needsFlashForV && !value.flash_attn && (
        <div className="md:col-span-2 text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
          {t("workerAdvanced.type_v.flashRequired")} — {t("workerAdvanced.enableFlashHint")}
        </div>
      )}

      <div className="md:col-span-2 flex items-center justify-between pt-1">
        <label htmlFor="remember" className="text-xs flex items-center gap-2">
          <input
            id="remember"
            type="checkbox"
            className="mr-1"
            checked={remember}
            onChange={(e) => setRemember(e.target.checked)}
            title={t("workerAdvanced.remember")} // tooltip too
          />
          <span className="text-gray-700">{t("workerAdvanced.remember")}</span>
        </label>

        <button
          type="button"
          className="text-[11px] px-2 py-1 rounded border hover:bg-gray-100"
          onClick={onReset}
          title={t("workerAdvanced.reset.tip")}
        >
          {t("workerAdvanced.reset.label")}
        </button>
      </div>
    </div>
  );
}

/* ---------- tiny UI primitives ---------- */
function Field(props: {
  id: string;
  label: string;
  value: string;
  onChange: (s: string) => void;
  placeholder?: string;
  title?: string;
}) {
  return (
    <label htmlFor={props.id} className="text-xs block" title={props.title}>
      <div className="mb-1 text-gray-600">{props.label}</div>
      <input
        id={props.id}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        inputMode="numeric"
        className="w-full px-2 py-1.5 rounded border text-sm"
        placeholder={props.placeholder}
      />
    </label>
  );
}

function Toggle(props: {
  id: string;
  label: string;
  checked: boolean;
  onChange: (b: boolean) => void;
  title?: string;
}) {
  return (
    <label htmlFor={props.id} className="text-xs flex items-center gap-2" title={props.title}>
      <input
        id={props.id}
        type="checkbox"
        checked={props.checked}
        onChange={(e) => props.onChange(e.target.checked)}
      />
      <span className="text-gray-700">{props.label}</span>
    </label>
  );
}

function Select(props: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  title?: string;
}) {
  return (
    <label htmlFor={props.id} className="text-xs block" title={props.title}>
      <div className="mb-1 text-gray-600">{props.label}</div>
      <select
        id={props.id}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        className="w-full px-2 py-1.5 rounded border text-sm"
      >
        {KVTYPES.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    </label>
  );
}
