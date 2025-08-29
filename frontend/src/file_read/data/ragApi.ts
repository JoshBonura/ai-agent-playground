// frontend/src/file_read/data/ragApi.ts
import { request } from "../services/http";

export function uploadRag(file: File, sessionId?: string, forceGlobal = false) {
  const form = new FormData();
  form.append("file", file);

  // Only append sessionId if not forcing global
  if (sessionId && !forceGlobal) {
    form.append("sessionId", sessionId);
  }

  return request<{ ok: boolean; added: number }>(
    "/api/rag/upload",
    { method: "POST", body: form }
  );
}

export function searchRag(query: string, opts?: {
  sessionId?: string;
  kChat?: number;
  kGlobal?: number;
  alpha?: number;
}) {
  const body = {
    query,
    sessionId: opts?.sessionId ?? undefined,
    kChat: opts?.kChat ?? 6,
    kGlobal: opts?.kGlobal ?? 4,
    hybrid_alpha: opts?.alpha ?? 0.5,
  };

  return request<{ hits: Array<{ score: number; source?: string; text: string }> }>(
    "/api/rag/search",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }
  );
}
