export const API_BASE = import.meta.env.VITE_API_URL || "";

function buildUrl(path: string) {
  const base = API_BASE.replace(/\/$/, "");
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(buildUrl(path), init);
  const text = await res.text().catch(() => "");
  if (!res.ok) {
    let msg = text || res.statusText;
    try { msg = JSON.parse(text)?.detail || msg; } catch {}
    throw new Error(`HTTP ${res.status} – ${msg}`);
  }
  return text ? (JSON.parse(text) as T) : (undefined as unknown as T);
}
