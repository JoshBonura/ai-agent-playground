// frontend/src/file_read/hooks/stream/core/network.ts
import { API_BASE } from "../../../services/http";

export async function postStream(body: unknown, signal: AbortSignal) {
  const res = await fetch(`${API_BASE}/api/ai/generate/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
  return res.body.getReader();
}

export async function postCancel(sessionId: string) {
  try {
    await fetch(`${API_BASE}/api/ai/cancel/${encodeURIComponent(sessionId)}`, {
      method: "POST",
    });
  } catch {
    /* best-effort */
  }
}
