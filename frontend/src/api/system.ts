// frontend/src/file_read/api/system.ts
import { getJSON } from "../services/http";

export type Resources = {
  os?: string; // optional (your backend returns 'platform' instead)
  cpuPct: number | null;
  ram: { total: number | null; used: number | null; free: number | null };
  vram: { total: number | null; used: number | null };// UI only needs total/used
  gpus: { index: number; name: string; total: number; used: number; free: number }[];
};

// Server shape (what your backend now returns)
type ServerResources = {
  cpu?: { countPhysical?: number; countLogical?: number; percent?: number };
  ram?: { totalBytes?: number; availableBytes?: number; usedBytes?: number; percent?: number };
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
};

function normalizeResources(s: ServerResources): Resources {
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
    os: s.platform,     // optional; your UI doesn’t really use it
    cpuPct,
    ram: { total: ramTotal, used: ramUsed, free: ramFree },
    vram: { total: vramTotal, used: vramUsed },
    gpus,
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
