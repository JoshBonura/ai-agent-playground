import { useEffect, useMemo, useRef } from "react";
import type { LlamaKwargs } from "../../api/modelWorkers";

type Props = {
  /** Name or full path (used to key per-model remembered settings) */
  modelKey?: string | null;
  value: LlamaKwargs;
  onChange: (next: LlamaKwargs) => void;
  remember: boolean;
  setRemember: (b: boolean) => void;
};

const KVTYPES = ["auto", "f16", "q8_0", "q6_K", "q5_K", "q4_K", "q4_0", "q3_K"] as const;

/* ---------- helpers ---------- */

function toInt(n?: number) {
  return typeof n === "number" && Number.isFinite(n) ? Math.trunc(n) : undefined;
}

function parseNum(v: string): number | undefined {
  const t = v.trim();
  if (!t) return undefined;
  const n = Number(t);
  return Number.isFinite(n) ? n : undefined;
}

function parseIntish(v: string): number | undefined {
  const n = parseNum(v);
  return toInt(n);
}

function sanitizeKey(k: string) {
  // keep it readable but safe for localStorage keys
  const last = k.split(/[\\/]/).pop() || k;
  return encodeURIComponent(last.toLowerCase());
}

/* ---------- component ---------- */

export default function WorkerAdvancedPanel({
  modelKey,
  value,
  onChange,
  remember,
  setRemember,
}: Props) {
  // stable storage key per model (falls back to a generic bucket)
  const storageKey = useMemo(
    () => `lm/adv/${modelKey ? sanitizeKey(modelKey) : "_default_"}`,
    [modelKey],
  );

  // one-time load from storage (merge into current value)
  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) {
        const saved = JSON.parse(raw) as LlamaKwargs;
        onChange({ ...value, ...saved });
      }
    } catch {
      /* ignore */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);

  // debounced persistence to storage whenever value/remember flips on
  const saveTimer = useRef<number | null>(null);
  useEffect(() => {
    if (!remember) return;
    try {
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
      saveTimer.current = window.setTimeout(() => {
        try {
          localStorage.setItem(storageKey, JSON.stringify(value || {}));
        } catch {
          /* ignore */
        }
      }, 250);
    } catch {
      /* ignore */
    }
    return () => {
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
    };
  }, [remember, value, storageKey]);

  const set = (patch: Partial<LlamaKwargs>) => onChange({ ...value, ...patch });

  const onReset = () => {
    set({});
    try {
      localStorage.removeItem(storageKey);
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="px-3 py-3 border-b grid grid-cols-1 md:grid-cols-2 gap-3 bg-gray-50/50">
      <Field
        id="adv-nctx"
        label="Context length (n_ctx)"
        placeholder="4096"
        value={value.n_ctx?.toString() ?? ""}
        onChange={(s) => set({ n_ctx: parseIntish(s) })}
        title="Maximum prompt+generation tokens the model can attend to"
      />
      <Field
        id="adv-ngpulayers"
        label="GPU offload layers (n_gpu_layers)"
        placeholder="36"
        value={value.n_gpu_layers?.toString() ?? ""}
        onChange={(s) => set({ n_gpu_layers: parseIntish(s) })}
        title="Number of transformer layers to offload to GPU (set 0 for CPU-only)"
      />
      <Field
        id="adv-nthreads"
        label="CPU threads (n_threads)"
        placeholder="8"
        value={value.n_threads?.toString() ?? ""}
        onChange={(s) => set({ n_threads: parseIntish(s) })}
        title="Thread pool size for CPU work"
      />
      <Field
        id="adv-nbatch"
        label="Eval batch size (n_batch)"
        placeholder="512"
        value={value.n_batch?.toString() ?? ""}
        onChange={(s) => set({ n_batch: parseIntish(s) })}
        title="Bigger can be faster but needs more RAM/VRAM"
      />

      <Field
        id="adv-ropebase"
        label="RoPE freq base"
        placeholder="(optional)"
        value={value.rope_freq_base?.toString() ?? ""}
        onChange={(s) => set({ rope_freq_base: parseNum(s) })}
        title="Adjusts RoPE base frequency (advanced)"
      />
      <Field
        id="adv-ropescale"
        label="RoPE freq scale"
        placeholder="(optional)"
        value={value.rope_freq_scale?.toString() ?? ""}
        onChange={(s) => set({ rope_freq_scale: parseNum(s) })}
        title="Adjusts RoPE scaling factor (advanced)"
      />

      <Toggle
        id="adv-flash"
        label="Flash attention"
        checked={!!value.flash_attn}
        onChange={(b) => set({ flash_attn: b })}
      />
      <Toggle
        id="adv-mmap"
        label="Try mmap()"
        checked={!!value.use_mmap}
        onChange={(b) => set({ use_mmap: b })}
      />
      <Toggle
        id="adv-mlock"
        label="Use mlock()"
        checked={!!value.use_mlock}
        onChange={(b) => set({ use_mlock: b })}
      />
      <Toggle
        id="adv-kvoff"
        label="Offload KV cache to GPU"
        checked={!!value.kv_offload}
        onChange={(b) => set({ kv_offload: b })}
      />

      <Field
        id="adv-seed"
        label="Seed"
        placeholder="(optional)"
        value={value.seed?.toString() ?? ""}
        onChange={(s) => set({ seed: parseIntish(s) })}
        title="Fixed seed for reproducibility"
      />

      <Select
        id="adv-typek"
        label="K cache quantization"
        value={value.type_k ?? "auto"}
        onChange={(v) => set({ type_k: v === "auto" ? undefined : v })}
      />
      <Select
        id="adv-typev"
        label="V cache quantization"
        value={value.type_v ?? "auto"}
        onChange={(v) => set({ type_v: v === "auto" ? undefined : v })}
      />

      <div className="md:col-span-2 flex items-center justify-between pt-1">
        <label htmlFor="remember" className="text-xs flex items-center gap-2">
          <input
            id="remember"
            type="checkbox"
            className="mr-1"
            checked={remember}
            onChange={(e) => setRemember(e.target.checked)}
          />
          <span className="text-gray-700">Remember settings for this model</span>
        </label>

        <button
          type="button"
          className="text-[11px] px-2 py-1 rounded border hover:bg-gray-100"
          onClick={onReset}
          title="Clear all advanced overrides for this model"
        >
          Reset
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
    <label htmlFor={props.id} className="text-xs block">
      <div className="mb-1 text-gray-600">{props.label}</div>
      <input
        id={props.id}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        inputMode="numeric"
        className="w-full px-2 py-1.5 rounded border text-sm"
        placeholder={props.placeholder}
        title={props.title}
      />
    </label>
  );
}

function Toggle(props: {
  id: string;
  label: string;
  checked: boolean;
  onChange: (b: boolean) => void;
}) {
  return (
    <label htmlFor={props.id} className="text-xs flex items-center gap-2">
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
}) {
  return (
    <label htmlFor={props.id} className="text-xs block">
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
