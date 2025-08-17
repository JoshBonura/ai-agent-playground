export const API_BASE = import.meta.env.VITE_API_URL || "";

export async function request<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  const text = await res.text().catch(() => "");
  if (!res.ok) {
    // bubble a readable error
    throw new Error(`HTTP ${res.status} – ${text || res.statusText}`);
  }
  return text ? (JSON.parse(text) as T) : (undefined as unknown as T);
}
