import { getJSON } from "../services/http";

export type Resources = {
  os?: string;                 // raw platform string
  osFamily?: string;           // "Windows" | "macOS" | "Linux" | etc.
  cpuPct: number | null;
  cpu: {
    name?: string;
    arch?: string;
    isa?: string[];
    compat?: { status: "compatible" | "incompatible" | "unknown"; reason?: string };            
  };
  ram: { total: number | null; used: number | null; free: number | null };
  vram: { total: number | null; used: number | null };
  gpus: { index: number; name: string; total: number; used: number; free: number }[];
  caps?: { cpu?: boolean; cuda?: boolean; metal?: boolean; hip?: boolean };
  gpuSource?: string;

};

// Server shape (what your backend now returns)
type ServerResources = {
  cpu?: {
    countPhysical?: number;
    countLogical?: number;
    percent?: number;
    name?: string;
    arch?: string;
    isa?: string[];
    compat?: { status: "compatible" | "incompatible" | "unknown"; reason?: string };
  };
  ram?: {
    totalBytes?: number;
    availableBytes?: number;
    usedBytes?: number;
    percent?: number;
  };
  gpus?: {
    index: number;
    name: string;
    memoryTotalBytes: number;
    memoryUsedBytes: number;
    memoryFreeBytes: number;
    utilPercent: number | null;
  }[];
  platform?: string;
  gpuSource?: string;
  osFamily?: string;
  caps?: { cpu?: boolean | string | number; cuda?: boolean | string | number; metal?: boolean; hip?: boolean };
};

function normalizeResources(s: ServerResources): Resources {
  const toBool = (v: unknown): boolean => {
    if (typeof v === "boolean") return v;
    if (typeof v === "number") return v !== 0;
    if (typeof v === "string") {
      const t = v.trim().toLowerCase();
      return t === "true" || t === "1" || t === "yes";
    }
    return false;
  };

  const cpuPct = s?.cpu?.percent ?? null;

  const ramTotal = s?.ram?.totalBytes ?? null;
  const ramUsed  = s?.ram?.usedBytes ?? null;
  const ramFree  = s?.ram?.availableBytes ?? null;

  const gpus = (s?.gpus ?? []).map(g => ({
    index: g.index,
    name: g.name,
    total: g.memoryTotalBytes,
    used:  g.memoryUsedBytes,
    free:  g.memoryFreeBytes,
  }));

  const vramTotal = gpus.reduce((acc, g) => acc + (g.total || 0), 0) || null;
  const vramUsed  = gpus.reduce((acc, g) => acc + (g.used  || 0), 0) || null;

  return {
    os: s.platform,
    osFamily: s.osFamily ?? undefined,
    cpuPct,
    cpu: {
      name: s?.cpu?.name,
      arch: s?.cpu?.arch,
      isa: s?.cpu?.isa ?? [],
      compat: s?.cpu?.compat,
    },
    ram: { total: ramTotal, used: ramUsed, free: ramFree },
    vram: { total: vramTotal, used: vramUsed },
    gpus,
    caps: s.caps
      ? {
          cpu: toBool(s.caps.cpu),
          cuda: toBool(s.caps.cuda),
          metal: toBool(s.caps.metal),
          hip: toBool(s.caps.hip),
        }
      : undefined,
    gpuSource: s.gpuSource,
  };
}


export async function getResources(): Promise<Resources> {
  // IMPORTANT: include /api prefix
  const raw = await getJSON<ServerResources>("/api/system/resources");
  return normalizeResources(raw);
}

export type WorkerRow = {
  id: string;
  port: number;
  model_path: string;
  status: "loading" | "ready" | "stopped";
  health?: {
    ok: boolean;
    model: string;
    path: string;
    n_ctx: number;
    n_threads: number;
    n_gpu_layers: number;
    n_batch: number;
  } | null;
};

export const inspectWorkers = () =>
  getJSON<{ ok: boolean; workers: WorkerRow[]; active: string | null }>("/api/model-workers/inspect");
