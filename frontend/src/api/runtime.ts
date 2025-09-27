import { getJSON, postJSON } from "../services/http";

export type RuntimeStatus = {
  running: boolean;
  info?: { os?: string; backend?: string; port?: number } | null;
  platform: "windows" | "linux" | "mac";
  active?: { version?: string } | null;
  allowed?: string[];
  installed?: string[];
  order?: string[];
};

export type RuntimeBuildEntry = {
  os: "win" | "linux" | "mac";
  backend: string;
  version: string;             // e.g. "v1.50.2"
  manifest: string;            // e.g. "manifests/win/cpu/v1.50.2.json"
  publishedAt?: string;
};

export type RuntimeCatalog = {
  schema: number;
  latest?: {
    win?: Record<string, string>;
    linux?: Record<string, string>;
    mac?: Record<string, string>;
  };
  builds: RuntimeBuildEntry[];
};


export const getRuntimeStatus = () =>
  getJSON<RuntimeStatus>("/api/runtime/status");

export const installRuntime = (backend: string) =>
  postJSON(`/api/runtime/install?backend=${encodeURIComponent(backend)}`, null);

export const switchRuntime = (backend: string) =>
  postJSON(`/api/runtime/switch?backend=${encodeURIComponent(backend)}`, null);

export const getRuntimeCatalog = () =>
  getJSON<RuntimeCatalog>("/api/runtime/catalog");

export const installFromCloudflare = (backend: string, version: string, activate = true) =>
  postJSON(
    `/api/runtime/install-from-cf?backend=${encodeURIComponent(backend)}&version=${encodeURIComponent(
      version
    )}&activate=${activate ? "true" : "false"}`,
    null
  );
