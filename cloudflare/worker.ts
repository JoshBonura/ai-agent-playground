/// <reference types="@cloudflare/workers-types" />
import { CORS, json, withCORS } from "./common";
import {
  handleManifest, handlePricing, handleSuccess, handlePublicKey,
  handleCheckoutSession, handleWebhook, handleLicenseBySession,
  handleLicenseByCustomer, handlePortalSession, handleAdminByEmail,
  LicenseStore, Env as LicEnv
} from "./licensing";

export { LicenseStore }; // DO class_name in wrangler.toml

// Add R2 binding type to Env (binding name "R2" must match wrangler.toml)
export interface Env extends LicEnv {
  R2: R2Bucket;
}

// ---- helpers for R2-backed runtime endpoints ----
async function r2Json(env: Env, key: string): Promise<Response> {
  const obj = await env.R2.get(key);
  if (!obj) return json({ error: "not_found", key }, 404);
  // json() wraps with CORS already, but here we need to stream raw contents
  const body = await obj.text();
  return withCORS(new Response(body, {
    status: 200,
    headers: { "content-type": "application/json" },
  }));
}

async function r2Stream(env: Env, key: string, filename?: string): Promise<Response> {
  const obj = await env.R2.get(key);
  if (!obj) return json({ error: "not_found", key }, 404);
  // Content-Type best-effort; wheels are binary
  const h = new Headers({
    "content-type": "application/octet-stream",
    "content-length": obj.size?.toString() ?? "",
    "etag": obj.httpEtag ?? "",
    "cache-control": "public, max-age=300",
  });
  if (filename) {
    h.set("content-disposition", `attachment; filename="${filename}"`);
  }
  return withCORS(new Response(obj.body, { status: 200, headers: h }));
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    if (req.method === "OPTIONS") return new Response(null, { headers: CORS });

    const url = new URL(req.url);
    const p = url.pathname;

    // Health
    if (p === "/" || p === "/health") return json({ ok: true, ts: Date.now() });

    // ---------- RUNTIME (R2) ----------
    // Catalog (optional but nice for UI)
    if (p === "/runtime/catalog" && req.method === "GET") {
      return r2Json(env, "catalog.json"); // stored at key "catalog.json" under bucket "runtimes"
    }

    // Manifest: /runtime/manifest?os=win&backend=cpu&version=v1.50.2
    if (p === "/runtime/manifest" && req.method === "GET") {
      const os = url.searchParams.get("os") || "";
      const backend = url.searchParams.get("backend") || "";
      const version = url.searchParams.get("version") || "";
      if (!os || !backend || !version) return json({ error: "missing_params" }, 400);
      const key = `manifests/${os}/${backend}/${version}.json`;
      return r2Json(env, key);
    }

    // Wheel stream: /runtime/wheel?key=wheels/win/cpu/v1.50.2/<file>.whl
    if (p === "/runtime/wheel" && req.method === "GET") {
      const key = url.searchParams.get("key") || "";
      if (!key || !key.startsWith("wheels/")) return json({ error: "bad_key" }, 400);
      const filename = key.split("/").pop() || "wheel.whl";
      return r2Stream(env, key, filename);
    }

    // ---------- LICENSING + STRIPE ----------
    if (p === "/api/manifest" && req.method === "GET") return handleManifest(req, env, url);
    if (p === "/pricing" && req.method === "GET") return handlePricing(req, env);
    if (p === "/success" && req.method === "GET") return handleSuccess(req, env, url);
    if (p === "/.well-known/licensing-public-key" && req.method === "GET") return handlePublicKey(env);
    if (p === "/api/checkout/session" && req.method === "POST") return handleCheckoutSession(req, env);
    if (p === "/api/stripe/webhook" && req.method === "POST") return handleWebhook(req, env);
    if (p === "/api/license/by-session" && req.method === "GET") return handleLicenseBySession(url, env);
    if (p === "/api/license/by-customer" && req.method === "GET") return handleLicenseByCustomer(url, env);
    if (p === "/api/portal/session" && req.method === "POST") return handlePortalSession(req, env);
    if (p === "/__admin/by-email" && req.method === "GET") return handleAdminByEmail(url, env);

    return json({ error: "not_found" }, 404);
  },
};
