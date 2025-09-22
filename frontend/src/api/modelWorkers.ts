import { getJSON, postJSON } from "../services/http";

export type WorkerHealth = {
  ok: boolean; model: string; path: string;
  n_ctx: number; n_threads: number; n_gpu_layers: number; n_batch: number;
} | null;

export type WorkerRow = {
  id: string;
  port: number;
  model_path: string;
  status: "loading" | "ready" | "stopped";
   health?: WorkerHealth; 
};

export type InspectResp = {
  ok: boolean;
  workers: WorkerRow[];
  active: string | null;
};

export type LlamaKwargs = {
  n_ctx?: number;
  n_threads?: number;
  n_gpu_layers?: number;
  n_batch?: number;
  rope_freq_base?: number;
  rope_freq_scale?: number;
  // toggles
  use_mmap?: boolean;
  use_mlock?: boolean;
  flash_attn?: boolean;
  kv_offload?: boolean;
  seed?: number;
  // cache quantization (experimental)
  type_k?: string; // e.g. "auto" | "f16" | "q8_0" | "q6_K" | "q4_0" ...
  type_v?: string;
};

export async function inspectWorkers(): Promise<InspectResp> {
  return getJSON("/api/model-workers/inspect");
}

export async function listWorkers(): Promise<InspectResp> {
  return inspectWorkers();
}

export async function spawnWorker(modelPath: string, llamaKwargs?: LlamaKwargs) {
  const tid = `trc_${Math.random().toString(36).slice(2)}_${Date.now()}`;
  const body = { modelPath, llamaKwargs: llamaKwargs || {} };
  console.debug("[spawnWorker] X-Trace-Id=%s payload=", tid, body);
  return postJSON("/api/model-workers/spawn", body, {
    headers: { "X-Trace-Id": tid },
  });
}


export async function activateWorker(id: string) {
  return postJSON(`/api/model-workers/activate/${encodeURIComponent(id)}`, {});
}

export async function killWorker(id: string) {
  return postJSON(`/api/model-workers/kill/${encodeURIComponent(id)}`, {});
}

export async function killAllWorkers() {
  return postJSON("/api/model-workers/kill-all", {});
}

export async function getActiveWorkerHealth(): Promise<any> {
  return getJSON("/api/aiw/health");
}
