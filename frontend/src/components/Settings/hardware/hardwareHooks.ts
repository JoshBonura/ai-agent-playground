import { useEffect, useMemo, useRef, useState} from "react";
import { getResources, type Resources } from "../../../api/system";

/* ---------------- helpers (exported) ---------------- */
export function fmtBytes(n?: number | null) {
  if (!Number.isFinite(n as number)) return "—";
  const gb = (n as number) / 1024 ** 3;
  return gb.toFixed(2) + " GB";
}

export function compatLabel(status?: string) {
  switch ((status || "").toLowerCase()) {
    case "compatible": return { text: "✓ Compatible", cls: "text-green-500" };
    case "incompatible": return { text: "✕ Not compatible", cls: "text-red-500" };
    default: return { text: "Compatibility unknown", cls: "text-gray-400" };
  }
}

export function isCpuCompatible(cpu?: Resources["cpu"]): boolean {
  if (!cpu) return false;
  const arch = (cpu.arch || "").toLowerCase();
  const flags = (cpu.isa || []).map(f => f.toLowerCase());
  const has = (f: string) => flags.includes(f.toLowerCase());
  if (arch === "x86_64" || arch === "amd64" || arch === "x64") {
    return has("avx") || has("avx2");
  }
  if (arch === "arm64" || arch === "aarch64") {
    return has("neon");
  }
  return false;
}

export function readCpuPct(s: Resources | null): number | null {
  const v = (s as any)?.cpuPct ?? null;
  return Number.isFinite(v as number) ? (v as number) : null;
}

export function truthy(v: unknown): boolean {
  if (typeof v === "boolean") return v;
  if (typeof v === "number") return v !== 0;
  if (typeof v === "string") {
    const t = v.trim().toLowerCase();
    return t === "true" || t === "1" || t === "yes";
  }
  return false;
}

export function chooseBestBackend(hasCUDA: boolean, hasMetal: boolean, hasHip: boolean) {
  if (hasCUDA) return "cuda";
  if (hasMetal) return "metal";
  if (hasHip) return "hip";
  return "cpu";
}

/* ---------------- main hook ---------------- */
export function useSystemResources({
  effective,
  overrides,
  saveOverrides,
}: {
  effective: Record<string, any> | null;
  overrides: Record<string, any> | null;
  saveOverrides: (obj: Record<string, any>, method?: "patch" | "put") => Promise<any>;
}) {
  const [snap, setSnap] = useState<Resources | null>(null);
  const [copied, setCopied] = useState(false);
  const [gpuChanged, setGpuChanged] = useState(false);
  const [isInteractingUntil, setIsInteractingUntil] = useState(0);
  const gpuBoxRef = useRef<HTMLDivElement | null>(null);

  // Poll resources (with “suppress while interacting”)
  useEffect(() => {
    const onPointer = () => setIsInteractingUntil(Date.now() + 400);
    window.addEventListener("pointerdown", onPointer, { passive: true });
    window.addEventListener("wheel", onPointer, { passive: true });
    return () => {
      window.removeEventListener("pointerdown", onPointer);
      window.removeEventListener("wheel", onPointer);
    };
  }, []);

  useEffect(() => {
    let alive = true;
    let t: number | null = null;
    const tick = async () => {
      try {
        const res = await getResources();
        const now = Date.now();
        const suppress = now < isInteractingUntil;
        if (!suppress) {
          if (alive) setSnap(res);

        }
      } catch (e) {

      }
      if (alive) t = window.setTimeout(tick, 2000);
    };
    tick();
    return () => {
      alive = false;
      if (t) window.clearTimeout(t);
    };
  }, [isInteractingUntil]);

  // Copy current system JSON
  async function copyResourcesJSON() {
    try {
      const res = await fetch("/api/system/resources");
      const data = await res.json();
      await navigator.clipboard.writeText(JSON.stringify(data, null, 2));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      if (snap) {
        try {
          await navigator.clipboard.writeText(JSON.stringify(snap, null, 2));
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1200);
        } catch {}
      }
    }
  }

  // Derived
  const gpus = snap?.gpus ?? [];
  const gpuTotal = useMemo(() => gpus.reduce((s, g) => s + (g.total || 0), 0), [gpus]);
  const gpuUsed  = useMemo(() => gpus.reduce((s, g) => s + (g.used  || 0), 0), [gpus]);

  const ramTotal = (snap as any)?.ram?.total ?? (snap as any)?.ram?.totalBytes ?? null;
  const ramUsed  = (snap as any)?.ram?.used  ?? (snap as any)?.ram?.usedBytes ?? null;

  const comboUsed = (ramUsed ?? 0) + (gpuUsed ?? 0);
  const cpuPct = readCpuPct(snap);

  const hasCUDA = !!(
    truthy((snap as any)?.caps?.cuda) ||
    String((snap as any)?.gpuSource || "").toLowerCase() === "nvidia-smi" ||
    gpus.some((g: any) => /nvidia|geforce|rtx|gtx/i.test(g.name ?? ""))
  );
  const hasMetal = !!(snap as any)?.caps?.metal;
  const hasHip   = !!(snap as any)?.caps?.hip;

  const storedBackend: string | undefined =
    (overrides?.hw_backend as string) ?? (effective?.hw_backend as string) ?? undefined;

  useEffect(() => {
    if (!storedBackend && snap) void saveOverrides({ hw_backend: "auto" }, "patch");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storedBackend, !!snap]);

  const curBackend = (storedBackend as string | undefined) ?? "auto";
  const predictedAuto = chooseBestBackend(hasCUDA, hasMetal, hasHip);
  const isEffectivelyCPU = curBackend === "cpu" || (curBackend === "auto" && predictedAuto === "cpu");

  const curKV: boolean =
    (overrides?.gpu_offload_kv as boolean) ??
    (effective?.gpu_offload_kv as boolean) ??
    true;

  const curLimitDedicated: boolean =
    (overrides?.gpu_limit_offload_dedicated as boolean) ??
    (effective?.gpu_limit_offload_dedicated as boolean) ??
    false;

  const DEFAULTS = { BACKEND: "auto", KV: true, LIMIT_DEDICATED: false };
  const isDefaultGPUSettings =
    curBackend === DEFAULTS.BACKEND &&
    curKV === DEFAULTS.KV &&
    curLimitDedicated === DEFAULTS.LIMIT_DEDICATED;

  const curGuardrailsMode: string =
    (overrides?.hw_guardrails_mode as string) ??
    (effective?.hw_guardrails_mode as string) ??
    effective?.worker_default?.guardrail?.mode ??
    "balanced";

  const curGuardrailsGB: number =
    (overrides?.hw_guardrails_custom_gb as number) ??
    (effective?.hw_guardrails_custom_gb as number) ??
    (effective?.worker_default?.guardrail?.custom_gb as number) ??
    6;

  const curAutoFit: boolean =
    (overrides?.hw_guardrails_autofit as boolean) ??
    (effective?.hw_guardrails_autofit as boolean) ??
    true;

  // Setters
  async function setAutoFit(next: boolean) {
    await saveOverrides({ hw_guardrails_autofit: next }, "patch");
  }

  async function setBackend(next: string) {
    setGpuChanged(true);
    const patch: Record<string, any> = {
      hw_backend: next,
      worker_default: { accel: next, n_gpu_layers: null },
      hw_n_gpu_layers: null,
    };
    await saveOverrides(patch, "patch");
  }

  async function setKV(next: boolean) {
    setGpuChanged(true); 
    await saveOverrides({ gpu_offload_kv: next }, "patch");
  }

  async function setLimitDedicated(next: boolean) {
    setGpuChanged(true);                    
    await saveOverrides({ gpu_limit_offload_dedicated: next }, "patch");

  }

  async function setGuardrailsMode(next: string) {
    await saveOverrides({ hw_guardrails_mode: next }, "patch");
  }

  async function setGuardrailsGB(next: number) {
    if (!Number.isFinite(next) || next <= 0) return;
    await saveOverrides({ hw_guardrails_custom_gb: Math.round(next) }, "patch");
  }

  async function resetGPUToDefault() {
    setGpuChanged(true);
    await saveOverrides(
      { hw_backend: null, gpu_offload_kv: null, gpu_limit_offload_dedicated: null },
      "patch",
    );
  }

  return {
    // state
    snap, copied, gpuChanged, gpuBoxRef,
    // derived
    gpus, gpuTotal, comboUsed, cpuPct, hasCUDA, hasMetal, hasHip,
    ramTotal, curBackend, isEffectivelyCPU, curKV, curLimitDedicated,
    isDefaultGPUSettings, curGuardrailsMode, curGuardrailsGB, curAutoFit,
    // actions
    copyResourcesJSON,
    setAutoFit, setBackend, setKV, setLimitDedicated, setGuardrailsMode, setGuardrailsGB,
    resetGPUToDefault,
  };
}
