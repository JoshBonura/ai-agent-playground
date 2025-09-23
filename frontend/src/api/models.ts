// frontend/src/api/models.ts
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
  // backend also returns worker (we don't use it here but keep it flexible)
  worker?: any;
};

const BASE = "/api/models";

/* ----------------------- tiny cache helpers ----------------------- */

type CacheShape = {
  etag: string | null;
  data: ModelsResponse | null;
  ts: number;
};

const CACHE_KEY = "lm/models-cache-v1";
let _mem: CacheShape = { etag: null, data: null, ts: 0 };

function traceId() {
  return `trc_${Math.random().toString(36).slice(2)}_${Date.now()}`;
}


function readStore(): CacheShape {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (raw) return JSON.parse(raw) as CacheShape;
  } catch {}
  return { etag: null, data: null, ts: 0 };
}
function writeStore(next: CacheShape) {
  _mem = next;
  try {
    sessionStorage.setItem(CACHE_KEY, JSON.stringify(next));
  } catch {}
}

function getCache(): CacheShape {
  // prefer memory; if empty, hydrate from sessionStorage
  if (!_mem.data) _mem = readStore();
  return _mem;
}

/** Synchronous peek so UI can paint instantly while fetch revalidates. */
export function peekModelsCache(): ModelsResponse | null {
  return getCache().data;
}

/* ----------------------- API ----------------------- */

type GetModelsOpts = {
  /** ask backend for fast listing (no GGUF header reads). Default true. */
  fast?: boolean;
};

/**
 * ETag-aware fetch. Sends If-None-Match; if 304, returns cached data.
 * If no cache present but 304 happens (should be rare), falls back to a no-ETag GET.
 */
export async function getModels(opts: GetModelsOpts = {}): Promise<ModelsResponse> {
  const fast = opts.fast ?? true;
  const cache = getCache();

  const headers: Record<string, string> = { Accept: "application/json" };
  if (cache.etag) headers["If-None-Match"] = cache.etag;

  // try ETag revalidation first
  let res = await fetch(`${BASE}?fast=${fast ? "true" : "false"}`, {
    credentials: "include",
    headers,
  });

  if (res.status === 304) {
    if (cache.data) return cache.data; // cache hit
    // extremely rare edge: 304 but we don't have cache -> retry without ETag
    res = await fetch(`${BASE}?fast=${fast ? "true" : "false"}`, {
      credentials: "include",
      headers: { Accept: "application/json" },
    });
  }

  if (!res.ok) throw new Error(`getModels ${res.status}`);

  const data = (await res.json()) as ModelsResponse;
  const etag = res.headers.get("ETag");

  // update cache
  writeStore({
    etag,
    data,
    ts: Date.now(),
  });

  return data;
}

// ✅ Define a body type that includes resetDefaults (kept for compatibility)
export type LoadBody = {
  modelPath: string;
  nCtx?: number;
  nThreads?: number;
  nGpuLayers?: number;
  nBatch?: number;
  ropeFreqBase?: number | null;
  ropeFreqScale?: number | null;
  resetDefaults?: boolean;
};



// Add this helper near the top or above loadModel:
function sanitizeLoadBody(body: LoadBody): LoadBody {
  // start clean copy
  const b: any = { ...body };

  // if caller asked to reset defaults, only send the two fields
  if (b.resetDefaults) {
    return { modelPath: b.modelPath, resetDefaults: true };
  }

  // 🔑 The important bit: never send the CPU-only sentinel
  if (b.nGpuLayers === 0 || b.nGpuLayers == null) delete b.nGpuLayers;

  // (nice-to-have) prune empty/invalid numeric knobs so server can infer sane defaults
  if (!Number.isFinite(b.nCtx)) delete b.nCtx;
  if (!Number.isFinite(b.nThreads)) delete b.nThreads;
  if (!Number.isFinite(b.nBatch)) delete b.nBatch;
  if (!Number.isFinite(b.ropeFreqBase)) delete b.ropeFreqBase;
  if (!Number.isFinite(b.ropeFreqScale)) delete b.ropeFreqScale;

  return b as LoadBody;
}


export async function loadModel(body: LoadBody) {
  const clean = sanitizeLoadBody(body);
  const tid = traceId();
  console.debug("[loadModel] X-Trace-Id=%s payload=", tid, clean);
  const res = await fetch(`${BASE}/load`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", "X-Trace-Id": tid },
    body: JSON.stringify(clean),
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

// --- Capabilities API ---
export type ModelsCapabilities = {
  ok: boolean;
  maxTokens: { header: number | null; effective: number | null };
  cpu: { threads: number | null };
  gpu: { offloadLayers: number | null; kvOffload: boolean | null; accel?: string | null };
  model: { path?: string | null; arch?: string | null; nLayersHeader?: number | null };
};

export async function getModelCapabilitiesForPath(modelPath: string): Promise<ModelsCapabilities> {
  const qs = new URLSearchParams({ modelPath }); // encodes backslashes on Windows
  const res = await fetch(`/api/models/capabilities?` + qs.toString(), { credentials: "include" });
  if (!res.ok) throw new Error(`capabilities ${res.status}`);
  return res.json();
}
