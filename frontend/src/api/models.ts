export type ModelFile = {
  path: string;
  sizeBytes: number;
  name: string;
  rel: string;
  ctxTrain?: number | null;
  // optional metadata your backend may return
  mtime?: number;
  arch?: string | null;
  paramsB?: number | null;
  quant?: string | null;
  format?: string | null;
};

export type ModelsResponse = {
  available: ModelFile[];
  current: { loaded: boolean; config?: any | null } | null;
  settings?: any;
};

const BASE = "/api/models";

export async function getModels(): Promise<ModelsResponse> {
  const res = await fetch(`${BASE}`, { credentials: "include" });
  if (!res.ok) throw new Error(`getModels ${res.status}`);
  return res.json();
}

// ✅ Define a body type that includes resetDefaults
export type LoadBody = {
  modelPath: string;
  nCtx?: number;
  nThreads?: number;
  nGpuLayers?: number;
  nBatch?: number;
  ropeFreqBase?: number | null;
  ropeFreqScale?: number | null;
  resetDefaults?: boolean; // ← NEW
};

export async function loadModel(body: LoadBody) {
  const res = await fetch(`${BASE}/load`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const j = await res.json().catch(() => null);
    const msg = (j && (j.error || j.detail)) || `loadModel ${res.status}`;
    throw new Error(msg);
  }
  return res.json();
}

export async function unloadModel() {
  const res = await fetch(`${BASE}/unload`, {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) throw new Error(`unloadModel ${res.status}`);
  return res.json();
}

export async function getModelHealth(): Promise<{ ok: boolean; loaded: boolean; config: any }> {
  const res = await fetch(`${BASE}/health`, { credentials: "include" });
  if (!res.ok) throw new Error(`health ${res.status}`);
  return res.json();
}

// (optional) convenience helper if you want a single call to reset to defaults:
export const loadModelWithDefaults = (modelPath: string) =>
  loadModel({ modelPath, resetDefaults: true });

export async function cancelModelLoad() {
  const res = await fetch(`/api/models/cancel-load`, {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) throw new Error(`cancelModelLoad ${res.status}`);
  return res.json();
}