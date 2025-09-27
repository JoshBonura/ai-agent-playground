// aimodel/file_read/cloudflare/licensing.ts
/// <reference types="@cloudflare/workers-types" />
import nacl from "tweetnacl";
import {
  json,
  html,
  withCORS,
  allowOrigin,
  hmac256Hex,
  strToB64u,
  b64u,
  nowSec,
  bad,
} from "./common";

/**
 * Env bindings
 */
export interface Env {
  APP_BASE_URL: string;
  PORTAL_RETURN_URL?: string;

  STRIPE_SECRET_KEY: string;
  STRIPE_WEBHOOK_SECRET: string;
  PRICE_MONTHLY_ID: string;

  LIC_ED25519_PRIV_HEX: string;
  LIC_ED25519_PUB_HEX: string;

  LICENSES: DurableObjectNamespace;

  ADMIN_KEY?: string;

  // App-wide update manifest
  APP_VERSION?: string;
  MIN_BACKEND?: string;
  MIN_FRONTEND?: string;
  UPDATE_NOTES?: string;
  ASSET_WIN_X64_URL?: string;
  ASSET_MAC_UNIVERSAL_URL?: string;
  ASSET_LINUX_X64_URL?: string;
  ASSET_WIN_X64_SHA256?: string;
  ASSET_MAC_UNIVERSAL_SHA256?: string;
  ASSET_LINUX_X64_SHA256?: string;
  UPDATE_CHANNEL?: string;
  UPDATE_ROLLOUT_PCT?: string;

  // R2 bucket for runtime artifacts (packs, wheels, manifests, diffs, catalog)
  R2: R2Bucket;
}

type StoredLic = { license: string; email?: string; exp?: number };

/* -------------------------------------------------------------------------------------------------
 * RUNTIME: CATALOG / PACK / MANIFEST / DIFF / WHEEL
 * Layout in R2 (all under bucket root):
 *   catalog.json
 *   packs/<os>/<backend>/<version>.zip
 *   manifests/<os>/<backend>/<version>.json
 *   diffs/<os>/<backend>/<from>__to__<to>.json
 *   wheels/<os>/<backend>/<version>/<file>.whl
 *   wheels/<os>/base/<version>/<file>.whl
 * ------------------------------------------------------------------------------------------------- */

/** GET /api/runtime/catalog – small JSON pointing to latest versions, etc. */
export async function handleRuntimeCatalog(env: Env) {
  const obj = await env.R2.get("catalog.json");
  if (!obj) return bad(404, "catalog_not_found");
  const headers = new Headers({
    "content-type": "application/json",
    "cache-control": "public, max-age=60",
  });
  if (obj.httpEtag) headers.set("etag", obj.httpEtag);
  if (obj.uploaded) headers.set("last-modified", obj.uploaded.toUTCString());
  return withCORS(new Response(await obj.text(), { headers }));
}

/** GET /runtime/pack?os=win&backend=cuda&version=v1.50.2 – full ZIP pack streaming */
export async function handleRuntimePack(_req: Request, env: Env, url: URL) {
  const os = (url.searchParams.get("os") || "").toLowerCase(); // "win" | "linux" | "mac"
  const backend = (url.searchParams.get("backend") || "").toLowerCase(); // "cpu" | "cuda" | ...
  const version = (url.searchParams.get("version") || "").trim(); // "v1.50.2"

  if (!os || !backend || !version) return bad(400, "missing_params");
  const key = `packs/${os}/${backend}/${version}.zip`;

  const obj = await env.R2.get(key);
  if (!obj) return bad(404, "pack_not_found");

  const fname = `${backend}-${os}-${version}.zip`;
  const headers = new Headers({
    "content-type": "application/zip",
    "content-disposition": `attachment; filename="${fname}"`,
    "cache-control": "public, max-age=3600",
  });
  if (obj.httpEtag) headers.set("etag", obj.httpEtag);
  if (obj.size) headers.set("content-length", String(obj.size));
  if (obj.uploaded) headers.set("last-modified", obj.uploaded.toUTCString());

  return withCORS(new Response(obj.body, { headers }));
}

/** GET /runtime/manifest?os=win&backend=cuda&version=v1.50.3 – JSON wheel list */
export async function handleRuntimeManifest(env: Env, url: URL) {
  const os = (url.searchParams.get("os") || "").toLowerCase();
  const backend = (url.searchParams.get("backend") || "").toLowerCase();
  const version = (url.searchParams.get("version") || "").trim();
  if (!os || !backend || !version) return bad(400, "missing_params");

  const key = `manifests/${os}/${backend}/${version}.json`;
  const obj = await env.R2.get(key);
  if (!obj) return bad(404, "manifest_not_found");

  const headers = new Headers({
    "content-type": "application/json",
    "cache-control": "public, max-age=60",
  });
  if (obj.httpEtag) headers.set("etag", obj.httpEtag);
  if (obj.uploaded) headers.set("last-modified", obj.uploaded.toUTCString());
  return withCORS(new Response(await obj.text(), { headers }));
}

/** GET /runtime/diff?os=win&backend=cuda&from=v1.50.2&to=v1.50.3 – optional precomputed delta */
export async function handleRuntimeDiff(env: Env, url: URL) {
  const os = (url.searchParams.get("os") || "").toLowerCase();
  const backend = (url.searchParams.get("backend") || "").toLowerCase();
  const from = (url.searchParams.get("from") || "").trim();
  const to = (url.searchParams.get("to") || "").trim();
  if (!os || !backend || !from || !to) return bad(400, "missing_params");

  const key = `diffs/${os}/${backend}/${from}__to__${to}.json`;
  const obj = await env.R2.get(key);
  if (!obj) return bad(404, "diff_not_found");

  const headers = new Headers({
    "content-type": "application/json",
    "cache-control": "public, max-age=60",
  });
  if (obj.httpEtag) headers.set("etag", obj.httpEtag);
  if (obj.uploaded) headers.set("last-modified", obj.uploaded.toUTCString());
  return withCORS(new Response(await obj.text(), { headers }));
}

/** GET /runtime/wheel?key=wheels/win/cuda/v1.50.3/llama_cpp_python-....whl – streams a single wheel */
export async function handleRuntimeWheel(env: Env, url: URL) {
  const key = url.searchParams.get("key") || "";
  if (!key || !key.endsWith(".whl")) return bad(400, "bad_key");

  const obj = await env.R2.get(key);
  if (!obj) return bad(404, "wheel_not_found");

  const fname = key.split("/").pop()!;
  const headers = new Headers({
    "content-type": "application/octet-stream",
    "content-disposition": `attachment; filename="${fname}"`,
    "cache-control": "public, max-age=3600",
  });
  if (obj.httpEtag) headers.set("etag", obj.httpEtag);
  if (obj.size) headers.set("content-length", String(obj.size));
  if (obj.uploaded) headers.set("last-modified", obj.uploaded.toUTCString());

  return withCORS(new Response(obj.body, { headers }));
}

/* -------------------------------------------------------------------------------------------------
 * APP MANIFEST (desktop app updater)
 * ------------------------------------------------------------------------------------------------- */

export async function handleManifest(req: Request, env: Env, url: URL) {
  const now = nowSec();
  const version = (env.APP_VERSION || "0.0.0").trim();
  const channel = (env.UPDATE_CHANNEL || "stable").trim();
  const rolloutPct = Math.min(
    100,
    Math.max(0, parseInt(env.UPDATE_ROLLOUT_PCT || "100", 10))
  );

  // Bucketing for staged rollout
  const key =
    (url.searchParams.get("k") || req.headers.get("Origin") || "*").toLowerCase();
  let include = true;
  if (rolloutPct < 100) {
    // FNV-1a-ish
    let h = 2166136261 >>> 0;
    for (let i = 0; i < key.length; i++) {
      h ^= key.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    include = (h % 100) < rolloutPct;
  }
  if (!include) return withCORS(json({ holdout: true, version }), allowOrigin(req));

  const assets: any[] = [];
  if (env.ASSET_WIN_X64_URL)
    assets.push({
      platform: "win-x64",
      url: env.ASSET_WIN_X64_URL,
      sha256: env.ASSET_WIN_X64_SHA256 || null,
    });
  if (env.ASSET_MAC_UNIVERSAL_URL)
    assets.push({
      platform: "mac-universal",
      url: env.ASSET_MAC_UNIVERSAL_URL,
      sha256: env.ASSET_MAC_UNIVERSAL_SHA256 || null,
    });
  if (env.ASSET_LINUX_X64_URL)
    assets.push({
      platform: "linux-x64",
      url: env.ASSET_LINUX_X64_URL,
      sha256: env.ASSET_LINUX_X64_SHA256 || null,
    });

  return withCORS(
    json(
      {
        version,
        publishedAt: now,
        channel,
        minBackend: env.MIN_BACKEND || null,
        minFrontend: env.MIN_FRONTEND || null,
        notes: env.UPDATE_NOTES || "",
        assets,
      },
      200
    ),
    allowOrigin(req)
  );
}

/* -------------------------------------------------------------------------------------------------
 * LICENSING + STRIPE
 * ------------------------------------------------------------------------------------------------- */

async function readFromDO(env: Env, key: string) {
  const stub = env.LICENSES.get(env.LICENSES.idFromName("store"));
  const r = await stub.fetch(
    `${env.APP_BASE_URL.replace(/\/+$/, "")}/get?key=${encodeURIComponent(key)}`
  );
  if (!r.ok) return null;
  return (await r.json<any>()) as StoredLic | null;
}

export function signActivation(jsonPayload: any, secretKey: Uint8Array) {
  const payload = JSON.stringify(jsonPayload);
  const sig = nacl.sign.detached(new TextEncoder().encode(payload), secretKey);
  return `LA1.${strToB64u(payload)}.${b64u(sig)}`; // LocalMind Activation v1
}

export function handlePricing(_req: Request, _env: Env) {
  return html(`<!doctype html>
<title>LocalMind Pro</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;max-width:760px;margin:40px auto;padding:0 16px} .card{border:1px solid #ddd;border-radius:12px;padding:20px;margin:12px 0} button{border:1px solid #000;border-radius:10px;padding:10px 16px;background:#000;color:#fff;cursor:pointer} .muted{color:#555}</style>
<h1>Choose your plan</h1>
<div class="card"><h2>Free</h2><ul class="muted"><li>Local only</li><li>Basic features</li></ul></div>
<div class="card"><h2>Pro — $9.99 / month</h2><ul><li>All features unlocked</li><li>License works offline after activation</li></ul>
<form method="POST" action="/api/checkout/session"><button type="submit">Go Pro</button></form></div>`);
}

export async function handleSuccess(_req: Request, env: Env, url: URL) {
  const sid = url.searchParams.get("session_id") || "";
  if (!sid) return html("<p>Missing session_id.</p>", 400);
  const rec = await readFromDO(env, "sid:" + sid);
  const lic = rec?.license || "";
  const masked = lic
    ? lic.slice(0, 16) + "… (copy below)"
    : "(not ready yet — webhook may still be processing; refresh in a few seconds)";
  const deep = lic ? `localmind://activate?license=${encodeURIComponent(lic)}` : "#";
  return html(`<!doctype html>
<title>Activation</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>body{font-family:system-ui;max-width:760px;margin:40px auto;padding:0 16px} input{width:100%;padding:10px;border:1px solid #ccc;border-radius:8px;font-family:monospace} a.btn,button{display:inline-block;margin-top:10px;border:1px solid #000;border-radius:10px;padding:10px 16px;background:#000;color:#fff;text-decoration:none}</style>
<h1>You're Pro 🎉</h1>
<p>Session: <code>${sid}</code></p>
<p><b>License:</b> ${masked}</p>
${
  lic
    ? `
<input id="lic" readonly value="${lic}"/>
<button onclick="navigator.clipboard.writeText(document.getElementById('lic').value)">Copy License</button>
<a class="btn" href="${deep}">Activate in app</a>`
    : `<p>Please wait a moment then <a href="/success?session_id=${encodeURIComponent(
        sid
      )}">refresh</a>.</p>`
}
`);
}

export function handlePublicKey(env: Env) {
  return json({ alg: "Ed25519", public_key_hex: env.LIC_ED25519_PUB_HEX });
}

export async function handleCheckoutSession(req: Request, env: Env) {
  type CheckoutBody = { email?: string };
  let email = "";
  try {
    const body = (await req.json()) as Partial<CheckoutBody>;
    email = typeof body.email === "string" ? body.email : "";
  } catch {}
  const res = await fetch("https://api.stripe.com/v1/checkout/sessions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.STRIPE_SECRET_KEY}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({
      mode: "subscription",
      "line_items[0][price]": env.PRICE_MONTHLY_ID,
      "line_items[0][quantity]": "1",
      success_url: `${env.APP_BASE_URL}/success?session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${env.APP_BASE_URL}/pricing`,
      "automatic_tax[enabled]": "true",
      customer_email: email || "",
      client_reference_id: email || "anonymous",
      allow_promotion_codes: "true",
    }),
  });
  const body = await res.json<any>();
  if (!res.ok) return withCORS(json(body, 400));
  const wantsJSON = (req.headers.get("accept") || "").includes("application/json");
  return wantsJSON
    ? withCORS(json({ url: body.url }))
    : withCORS(
        html(
          `<!doctype html><meta http-equiv="refresh" content="0;url=${body.url}">Redirecting…`
        )
      );
}

export async function handleWebhook(req: Request, env: Env) {
  const sig = req.headers.get("stripe-signature") || "";
  const raw = await req.text();
  const parts = sig.split(",").reduce((acc, kv) => {
    const [k, v] = kv.split("=");
    acc[k] = v;
    return acc;
  }, {} as Record<string, string>);
  const signedPayload = `${parts["t"]}.${raw}`;
  const expected = await hmac256Hex(env.STRIPE_WEBHOOK_SECRET, signedPayload);
  const provided = parts["v1"];
  if (!provided || provided.toLowerCase() !== expected.toLowerCase())
    return bad(400, "signature_verify_failed");

  const event = JSON.parse(raw);
  const type = event.type as string;
  const obj = event.data.object as any;
  if (type === "checkout.session.completed" || type === "invoice.paid") {
    const sessionId = obj.id || obj.checkout_session || "";
    const customerId = obj.customer || "";
    let email = "";
    if (customerId) {
      const c = await fetch(
        `https://api.stripe.com/v1/customers/${encodeURIComponent(customerId)}`,
        { headers: { Authorization: `Bearer ${env.STRIPE_SECRET_KEY}` } }
      ).then((r) => r.json<any>());
      email = c?.email || "";
    }
    const issued_at = nowSec();
    const exp = issued_at + 365 * 24 * 3600;
    const licenseClaims = {
      ver: 1,
      license_id: `lic_${sessionId || customerId || issued_at}`,
      sub: email || customerId || "unknown",
      plan: "pro",
      entitlements: ["all"],
      issued_at,
      exp,
    };
    const privHex = env.LIC_ED25519_PRIV_HEX.trim();
    const bytes = new Uint8Array(
      privHex.match(/.{1,2}/g)!.map((h) => parseInt(h, 16))
    );
    let keypair: { secretKey: Uint8Array; publicKey: Uint8Array };
    if (bytes.length === 32) keypair = nacl.sign.keyPair.fromSeed(bytes);
    else if (bytes.length === 64)
      keypair = { secretKey: bytes, publicKey: bytes.slice(32) };
    else return bad(500, "bad_private_key_length");
    const payloadStr = JSON.stringify(licenseClaims);
    const sigBytes = nacl.sign.detached(
      new TextEncoder().encode(payloadStr),
      keypair.secretKey
    );
    const license = `LM1.${strToB64u(payloadStr)}.${b64u(sigBytes)}`;
    const stub = env.LICENSES.get(env.LICENSES.idFromName("store"));
    const put = (key: string, value: StoredLic) =>
      stub.fetch(`${env.APP_BASE_URL.replace(/\/+$/, "")}/put`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, value }),
      });
    await put("sid:" + (sessionId || customerId), { license, email, exp });
    if (customerId) await put("cust:" + customerId, { license, email, exp });
    if (email) await put("email:" + email.toLowerCase(), { license, email, exp });
  }
  return json({ received: true }, 200);
}

export async function handleLicenseBySession(url: URL, env: Env) {
  const sid = url.searchParams.get("session_id") || "";
  if (!sid) return withCORS(json({ error: "missing_session_id" }, 400));
  const rec = await readFromDO(env, "sid:" + sid);
  if (!rec?.license) return withCORS(json({ license: null }, 404));
  return withCORS(json(rec));
}

export async function handleLicenseByCustomer(url: URL, env: Env) {
  const email = (url.searchParams.get("email") || "").toLowerCase().trim();
  if (!email) return withCORS(json({ error: "missing_email" }, 400));
  let rec = await readFromDO(env, "email:" + email);
  if (!rec?.license) {
    const sr = await fetch(
      "https://api.stripe.com/v1/customers?limit=1&email=" +
        encodeURIComponent(email),
      { headers: { Authorization: `Bearer ${env.STRIPE_SECRET_KEY}` } }
    );
    const list = await sr.json<any>();
    const cust = list?.data?.[0];
    if (cust?.id) {
      rec = await readFromDO(env, "cust:" + cust.id);
      if (rec?.license) {
        const stub = env.LICENSES.get(env.LICENSES.idFromName("store"));
        await stub.fetch(`${env.APP_BASE_URL.replace(/\/+$/, "")}/put`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key: "email:" + email, value: rec }),
        });
      }
    }
  }
  if (!rec?.license) return withCORS(json({ license: null }, 404));
  return withCORS(json(rec));
}

export async function handlePortalSession(req: Request, env: Env) {
  let email = "";
  try {
    const body = await req.json<any>();
    email = (body?.email || "").toLowerCase().trim();
  } catch {}
  if (!email) return withCORS(json({ error: "missing_email" }, 400));
  const listRes = await fetch(
    "https://api.stripe.com/v1/customers?limit=1&email=" +
      encodeURIComponent(email),
    { headers: { Authorization: `Bearer ${env.STRIPE_SECRET_KEY}` } }
  );
  const list = await listRes.json<any>();
  const customer = list?.data?.[0];
  if (!customer?.id) return withCORS(json({ error: "customer_not_found" }, 404));
  const pr = await fetch("https://api.stripe.com/v1/billing_portal/sessions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.STRIPE_SECRET_KEY}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({
      customer: customer.id,
      return_url: env.PORTAL_RETURN_URL || env.APP_BASE_URL,
    }),
  });
  const portal = await pr.json<any>();
  if (!pr.ok) return withCORS(json(portal, 400));
  return withCORS(json({ url: portal.url }));
}

export async function handleAdminByEmail(url: URL, env: Env) {
  const k = url.searchParams.get("k") || "";
  if (!env.ADMIN_KEY || k !== env.ADMIN_KEY)
    return withCORS(json({ error: "forbidden" }, 403));
  const email = (url.searchParams.get("email") || "").toLowerCase().trim();
  if (!email) return withCORS(json({ error: "missing_email" }, 400));
  const rec = await readFromDO(env, "email:" + email);
  return withCORS(json(rec || { license: null }));
}

/* -------------------------------------------------------------------------------------------------
 * Durable Object: simple KV for licenses (keep here to stay at 3 files)
 * ------------------------------------------------------------------------------------------------- */
export class LicenseStore {
  state: DurableObjectState;
  storage: DurableObjectStorage;
  constructor(state: DurableObjectState) {
    this.state = state;
    this.storage = state.storage;
  }
  async fetch(req: Request) {
    const url = new URL(req.url);
    if (req.method === "POST" && url.pathname === "/put") {
      const { key, value } = await req.json<any>();
      if (!key || !value) return json({ error: "bad_request" }, 400);
      await this.storage.put(key, value);
      return new Response(null, { status: 204 });
    }
    if (req.method === "GET" && url.pathname === "/get") {
      const key = url.searchParams.get("key") || "";
      const value = await this.storage.get<any>(key);
      return json(value ?? null, 200);
    }
    return bad(404, "not_found");
  }
}
