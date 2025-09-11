import { buildUrl, requestRaw } from "../../../services/http";

export async function postStream(body: unknown, signal: AbortSignal) {
  const url = buildUrl("/ai/generate/stream");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  const res = await requestRaw(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    const t = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${res.statusText} ${t}`);
  }
  return res.body.getReader();
}

export async function postCancel(sessionId: string) {
  try {
    const url = buildUrl(`/ai/cancel/${encodeURIComponent(sessionId)}`);
    await requestRaw(url, { method: "POST" });
  } catch {}
}
