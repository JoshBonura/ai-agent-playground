// frontend/src/file_read/data/ragApi.ts
import { request, API_BASE } from "../services/http";

export function uploadRag(file: File, sessionId?: string, forceGlobal = false) {
  const form = new FormData();
  form.append("file", file);
  if (sessionId && !forceGlobal) form.append("sessionId", sessionId);

  return request<{ ok: boolean; added: number }>("/api/rag/upload", {
    method: "POST",
    body: form,
  });
}

export function uploadRagWithProgress(
  file: File,
  sessionId: string,
  onProgress: (pct: number) => void,
  signal?: AbortSignal,
): Promise<{ ok: boolean; added: number }> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    form.append("sessionId", sessionId);

    const xhr = new XMLHttpRequest();
    const url = `${API_BASE}/api/rag/upload`.replace(/([^:]\/)\/+/g, "$1");
    xhr.open("POST", url);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable)
        onProgress(Math.round((e.loaded / e.total) * 100));
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          resolve({ ok: true, added: 0 });
        }
      } else {
        reject(new Error(`Upload failed (${xhr.status})`));
      }
    };

    // treat abort as a silent resolution, not an error
    xhr.onabort = () => resolve({ ok: false, added: 0 });
    xhr.onerror = () => reject(new Error("Network error"));

    if (signal) {
      if (signal.aborted) {
        xhr.abort();
        return resolve({ ok: false, added: 0 });
      }
      signal.addEventListener("abort", () => xhr.abort(), { once: true });
    }

    xhr.send(form);
  });
}

export function searchRag(
  query: string,
  opts?: {
    sessionId?: string;
    kChat?: number;
    kGlobal?: number;
    alpha?: number; // hybrid_alpha
  },
) {
  const body = {
    query,
    sessionId: opts?.sessionId ?? undefined,
    kChat: opts?.kChat ?? 6,
    kGlobal: opts?.kGlobal ?? 4,
    hybrid_alpha: opts?.alpha ?? 0.5,
  };

  return request<{
    hits: Array<{
      id?: string;
      score: number;
      source?: string;
      title?: string;
      text: string;
      sessionId?: string | null;
    }>;
  }>(
    "/api/rag/search", // ✅ relative path, request() adds API_BASE
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export type UploadRow = {
  source: string;
  sessionId?: string | null;
  chunks: number;
};

export async function listUploads(
  sessionId?: string,
  scope: "all" | "session" = "all",
) {
  const p = new URLSearchParams();
  if (sessionId) p.set("sessionId", sessionId);
  if (scope) p.set("scope", scope);

  return request<{ uploads: UploadRow[] }>(`/api/rag/uploads?${p.toString()}`, {
    method: "GET",
  });
}

export async function deleteUploadHard(source: string, sessionId?: string) {
  return request<{ ok: boolean; removed: number; remaining: number }>(
    `/api/rag/uploads/delete-hard`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, sessionId }),
    },
  );
}
