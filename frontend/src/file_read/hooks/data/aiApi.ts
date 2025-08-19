import { API_BASE } from "../../services/http";

export function streamGenerate(
  payload: unknown,
  abortSignal: AbortSignal,
): ReadableStream<Uint8Array> | null {
  // Note: fetch streaming body works in modern browsers + Vite dev server
  let stream: ReadableStream<Uint8Array> | null = null;

  // We purposefully do NOT await; the caller will read res.body
  fetch(`${API_BASE}/api/ai/generate/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: abortSignal,
  }).then(res => {
    if (res.ok) stream = res.body ?? null;
  }).catch(() => { /* surface in hook if needed */ });

  // The caller will poll for stream being set in the next tick
  // (or just call fetch directly if they prefer).
  return stream;
}

export async function cancelSession(sessionId: string): Promise<void> {
  try {
    await fetch(`${API_BASE}/api/ai/cancel/${encodeURIComponent(sessionId)}`, { method: "POST" });
  } catch { /* best-effort */ }
}
