import { getJSON, postJSON } from "../services/http";

export type WorkerRow = {
  id: string;
  port: number;
  model_path: string;
  status: "loading" | "ready" | "stopped";
};

export type InspectResp = {
  ok: boolean;
  workers: WorkerRow[];
  active: string | null;
  // server may also include a "system" snapshot; we don't require it here
};

export async function inspectWorkers(): Promise<InspectResp> {
  return getJSON("/api/model-workers/inspect");
}

export async function listWorkers(): Promise<InspectResp> {
  return inspectWorkers();
}

export async function spawnWorker(modelPath: string) {
  return postJSON("/api/model-workers/spawn", { modelPath });
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

// Active worker health via proxy (requires auth; your http helpers should attach it)
export async function getActiveWorkerHealth(): Promise<any> {
  return getJSON("/api/aiw/health");
}
