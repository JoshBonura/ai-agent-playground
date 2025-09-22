// frontend/src/file_read/data/settingsApi.ts
import { request } from "../services/http";

export function getDefaults() {
  return request<Record<string, any>>("/api/settings/defaults");
}

export function getOverrides() {
  return request<Record<string, any>>("/api/settings/overrides");
}

export function getEffective(sessionId?: string) {
  const qs = sessionId ? `?sessionId=${encodeURIComponent(sessionId)}` : "";
  return request<Record<string, any>>(`/api/settings/effective${qs}`);
}

export function putOverrides(overrides: Record<string, any>) {
  return request<{ ok: boolean; overrides: any }>("/api/settings/overrides", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(overrides), // ← send raw object
  });
}

export function patchOverrides(patch: Record<string, any>) {
  return request<{ ok: boolean; overrides: any }>("/api/settings/overrides", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch), // ← send raw object
  });
}


