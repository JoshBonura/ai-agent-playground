export const API_BASE = (import.meta.env.VITE_API_URL || "/api").trim();

export function buildUrl(path: string) {
  if (/^https?:\/\//i.test(path)) return path;
  const base = API_BASE.replace(/\/+$/, "");
  const p = (path.startsWith("/") ? path : `/${path}`).replace(/\/{2,}/g, "/");
  if (base && p.startsWith(base + "/")) return p;
  return `${base}${p}`;
}

type JSONValue = unknown;

export class HttpError extends Error {
  status: number;
  body?: string;
  constructor(status: number, message: string, body?: string) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function buildHeaders(init: RequestInit = {}) {
  const headers = new Headers(init.headers || {});
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (!headers.has("Content-Type") && typeof init.body === "string") {
    try { JSON.parse(init.body); headers.set("Content-Type", "application/json"); } catch {}
  }
  return headers;
}

async function doFetch(path: string, init: RequestInit = {}, timeoutMs = 30000) {
  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const headers = await buildHeaders(init);
    const res = await fetch(buildUrl(path), {
      ...init,
      headers,
      signal: controller.signal,
      credentials: "include",
    });
    return res;
  } finally {
    clearTimeout(t);
  }
}

export async function requestRaw(path: string, init: RequestInit = {}, timeoutMs = 30000): Promise<Response> {
  return await doFetch(path, init, timeoutMs);
}

export async function request<T = JSONValue>(path: string, init: RequestInit = {}, timeoutMs = 30000): Promise<T> {
  const res = await requestRaw(path, init, timeoutMs);
  const text = await res.text().catch(() => "");
  if (!res.ok) {
    let msg = res.statusText || "Request failed";
    try {
      const parsed = text ? JSON.parse(text) : undefined;
      msg = (parsed?.detail || parsed?.message || msg) as string;
    } catch {}
    throw new HttpError(res.status, `HTTP ${res.status} – ${msg}`, text);
  }
  if (!text) return undefined as unknown as T;
  try { return JSON.parse(text) as T; } catch { return text as unknown as T; }
}

export const getJSON = <T = JSONValue>(path: string, init: RequestInit = {}) =>
  request<T>(path, { ...init, method: "GET" });

export const delJSON = <T = JSONValue>(path: string, init: RequestInit = {}) =>
  request<T>(path, { ...init, method: "DELETE" });

export const postJSON = <T = JSONValue>(path: string, body: unknown, init: RequestInit = {}) =>
  request<T>(path, {
    ...init,
    method: "POST",
    headers: { ...(init.headers || {}), "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });

export const putJSON = <T = JSONValue>(path: string, body: unknown, init: RequestInit = {}) =>
  request<T>(path, {
    ...init,
    method: "PUT",
    headers: { ...(init.headers || {}), "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });

  // frontend/src/file_read/services/http.ts
export const postJSONWithCreds = <T = unknown>(path: string, body: unknown, init: RequestInit = {}) =>
  request<T>(path, {
    ...init,
    method: "POST",
    credentials: "include",
    headers: { ...(init.headers || {}), "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });

