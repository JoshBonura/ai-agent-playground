// aimodel/file_read/cloudflare/worker-licensing.ts
import type {
  ExecutionContext,
  DurableObjectNamespace,
} from "@cloudflare/workers-types";
import nacl from "tweetnacl";
export { LicenseStore } from "./license-do";

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
}

function withCORS(res: Response, origin = "*") {
  const h = new Headers(res.headers);
  h.set("Access-Control-Allow-Origin", origin);
  h.set("Vary", "Origin");
  return new Response(res.body, { status: res.status, headers: h });
}
const allowOrigin = (req: Request) => req.headers.get("Origin") || "*";

function signActivation(json: any, secretKey: Uint8Array) {
  const payload = JSON.stringify(json);
  const sig = nacl.sign.detached(new TextEncoder().encode(payload), secretKey);
  return `LA1.${strToB64u(payload)}.${b64u(sig)}`; // “LA1” = LocalMind Activation v1
}

function html(
  body: string,
  status = 200,
  headers: Record<string, string> = {},
) {
  return new Response(body, {
    status,
    headers: { "content-type": "text/html; charset=utf-8", ...headers },
  });
}
function json(obj: unknown, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json" },
  });
}
async function hmac256Hex(secret: string, payload: string) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(payload),
  );
  return [...new Uint8Array(sig)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
function b64u(data: Uint8Array): string {
  let s = btoa(String.fromCharCode(...data));
  return s.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}
function strToB64u(s: string) {
  return b64u(new TextEncoder().encode(s));
}
const nowSec = () => Math.floor(Date.now() / 1000);

type StoredLic = { license: string; email?: string; exp?: number };
async function readFromDO(env: Env, key: string) {
  const stub = env.LICENSES.get(env.LICENSES.idFromName("store"));
  const r = await stub.fetch(
    "https://store/get?key=" + encodeURIComponent(key),
  );
  if (!r.ok) return null;
  return (await r.json<any>()) as StoredLic | null;
}

export default {
  async fetch(
    request: Request,
    env: Env,
    ctx: ExecutionContext,
  ): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/api/manifest") {
      const now = Math.floor(Date.now() / 1000);
      const version = (env.APP_VERSION || "0.0.0").trim();
      const channel = (env.UPDATE_CHANNEL || "stable").trim();
      const rolloutPct = Math.min(
        100,
        Math.max(0, parseInt(env.UPDATE_ROLLOUT_PCT || "100", 10)),
      );

      // Optional: simple percentage rollout based on a deterministic key
      // Use Origin or a query "k" as the bucketing key; totally optional.
      const key = (
        url.searchParams.get("k") ||
        request.headers.get("Origin") ||
        "*"
      ).toLowerCase();
      let include = true;
      if (rolloutPct < 100) {
        // FNV-1a-ish quick hash
        let h = 2166136261 >>> 0;
        for (let i = 0; i < key.length; i++) {
          h ^= key.charCodeAt(i);
          h = Math.imul(h, 16777619) >>> 0;
        }
        const bucket = h % 100;
        include = bucket < rolloutPct;
      }
      if (!include)
        return withCORS(json({ holdout: true, version }), allowOrigin(request));

      const assets: any[] = [];
      if (env.ASSET_WIN_X64_URL) {
        assets.push({
          platform: "win-x64",
          url: env.ASSET_WIN_X64_URL,
          sha256: env.ASSET_WIN_X64_SHA256 || null,
        });
      }
      if (env.ASSET_MAC_UNIVERSAL_URL) {
        assets.push({
          platform: "mac-universal",
          url: env.ASSET_MAC_UNIVERSAL_URL,
          sha256: env.ASSET_MAC_UNIVERSAL_SHA256 || null,
        });
      }
      if (env.ASSET_LINUX_X64_URL) {
        assets.push({
          platform: "linux-x64",
          url: env.ASSET_LINUX_X64_URL,
          sha256: env.ASSET_LINUX_X64_SHA256 || null,
        });
      }

      const body = {
        version,
        publishedAt: now,
        channel,
        minBackend: env.MIN_BACKEND || null,
        minFrontend: env.MIN_FRONTEND || null,
        notes: env.UPDATE_NOTES || "",
        assets,
      };
      return withCORS(json(body), allowOrigin(request));
    }
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
          "Access-Control-Allow-Headers":
            "Content-Type,Stripe-Signature,Authorization",
        },
      });
    }
    if (url.pathname === "/health") return json({ ok: true });
    if (url.pathname === "/pricing") {
      return html(`<!doctype html>
<title>LocalMind Pro</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;max-width:760px;margin:40px auto;padding:0 16px} .card{border:1px solid #ddd;border-radius:12px;padding:20px;margin:12px 0} button{border:1px solid #000;border-radius:10px;padding:10px 16px;background:#000;color:#fff;cursor:pointer} .muted{color:#555}</style>
<h1>Choose your plan</h1>
<div class="card">
  <h2>Free</h2>
  <ul class="muted"><li>Local only</li><li>Basic features</li></ul>
</div>
<div class="card">
  <h2>Pro — $9.99 / month</h2>
  <ul><li>All features unlocked</li><li>License works offline after activation</li></ul>
  <form method="POST" action="/api/checkout/session">
    <button type="submit">Go Pro</button>
  </form>
</div>`);
    }
    if (url.pathname === "/success") {
      const sid = url.searchParams.get("session_id") || "";
      if (!sid) return html("<p>Missing session_id.</p>", 400);
      const stub = env.LICENSES.get(env.LICENSES.idFromName("store"));
      const r = await stub.fetch(
        "https://store/get?key=" + encodeURIComponent("sid:" + sid),
      );
      const data = await r.json<any>();
      const lic = data?.license || "";
      const masked = lic
        ? lic.slice(0, 16) + "… (copy below)"
        : "(not ready yet — webhook may still be processing; refresh in a few seconds)";
      const deep = lic
        ? `localmind://activate?license=${encodeURIComponent(lic)}`
        : "#";
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
<a class="btn" href="${deep}">Activate in app</a>
`
    : `<p>Please wait a moment then <a href="/success?session_id=${encodeURIComponent(sid)}">refresh</a>.</p>`
}
`);
    }
    if (url.pathname === "/.well-known/licensing-public-key") {
      return json({ alg: "Ed25519", public_key_hex: env.LIC_ED25519_PUB_HEX });
    }
    if (request.method === "POST" && url.pathname === "/api/checkout/session") {
      type CheckoutBody = { email?: string };
      let email = "";
      try {
        const body = (await request.json()) as Partial<CheckoutBody>;
        email = typeof body.email === "string" ? body.email : "";
      } catch {
        email = "";
      }
      const price = env.PRICE_MONTHLY_ID;
      const res = await fetch("https://api.stripe.com/v1/checkout/sessions", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.STRIPE_SECRET_KEY}`,
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: new URLSearchParams({
          mode: "subscription",
          "line_items[0][price]": price,
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
      if (!res.ok) return withCORS(json(body, 400), allowOrigin(request));
      const wantsJSON = (request.headers.get("accept") || "").includes(
        "application/json",
      );
      if (wantsJSON)
        return withCORS(json({ url: body.url }), allowOrigin(request));
      return withCORS(
        html(
          `<!doctype html><meta http-equiv="refresh" content="0;url=${body.url}">Redirecting…`,
        ),
        allowOrigin(request),
      );
    }
    if (request.method === "POST" && url.pathname === "/api/stripe/webhook") {
      const sig = request.headers.get("stripe-signature") || "";
      const raw = await request.text();
      const parts = sig.split(",").reduce(
        (acc, kv) => {
          const [k, v] = kv.split("=");
          acc[k] = v;
          return acc;
        },
        {} as Record<string, string>,
      );
      const signedPayload = `${parts["t"]}.${raw}`;
      const expected = await hmac256Hex(
        env.STRIPE_WEBHOOK_SECRET,
        signedPayload,
      );
      const provided = parts["v1"];
      if (!provided || provided.toLowerCase() !== expected.toLowerCase())
        return json({ error: "signature_verify_failed" }, 400);
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
            { headers: { Authorization: `Bearer ${env.STRIPE_SECRET_KEY}` } },
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
        const priv = new Uint8Array(
          privHex.match(/.{1,2}/g)!.map((h) => parseInt(h, 16)),
        );
        let keypair: { secretKey: Uint8Array; publicKey: Uint8Array };
        if (priv.length === 32) keypair = nacl.sign.keyPair.fromSeed(priv);
        else if (priv.length === 64)
          keypair = { secretKey: priv, publicKey: priv.slice(32) };
        else return json({ error: "bad_private_key_length" }, 500);
        const payloadStr = JSON.stringify(licenseClaims);
        const payloadB64 = strToB64u(payloadStr);
        const sigBytes = nacl.sign.detached(
          new TextEncoder().encode(payloadStr),
          keypair.secretKey,
        );
        const sigB64 = b64u(sigBytes);
        const license = `LM1.${payloadB64}.${sigB64}`;
        const stub = env.LICENSES.get(env.LICENSES.idFromName("store"));
        await stub.fetch("https://store/put", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            key: "sid:" + (sessionId || customerId),
            value: { license, email, exp },
          }),
        });
        if (customerId) {
          await stub.fetch("https://store/put", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              key: "cust:" + customerId,
              value: { license, email, exp },
            }),
          });
        }
        if (email) {
          await stub.fetch("https://store/put", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              key: "email:" + email.toLowerCase(),
              value: { license, email, exp },
            }),
          });
        }
      }
      return json({ received: true }, 200);
    }
    if (
      request.method === "GET" &&
      url.pathname === "/api/license/by-session"
    ) {
      const sid = url.searchParams.get("session_id") || "";
      if (!sid)
        return withCORS(
          json({ error: "missing_session_id" }, 400),
          allowOrigin(request),
        );
      const rec = await readFromDO(env, "sid:" + sid);
      if (!rec?.license)
        return withCORS(json({ license: null }, 404), allowOrigin(request));
      return withCORS(json(rec), allowOrigin(request));
    }
    if (
      request.method === "GET" &&
      url.pathname === "/api/license/by-customer"
    ) {
      const email = (url.searchParams.get("email") || "").toLowerCase().trim();
      if (!email)
        return withCORS(
          json({ error: "missing_email" }, 400),
          allowOrigin(request),
        );
      let rec = await readFromDO(env, "email:" + email);
      if (!rec?.license) {
        const sr = await fetch(
          "https://api.stripe.com/v1/customers?limit=1&email=" +
            encodeURIComponent(email),
          { headers: { Authorization: `Bearer ${env.STRIPE_SECRET_KEY}` } },
        );
        const list = await sr.json<any>();
        const cust = list?.data?.[0];
        if (cust?.id) {
          rec = await readFromDO(env, "cust:" + cust.id);
          if (rec?.license) {
            const stub = env.LICENSES.get(env.LICENSES.idFromName("store"));
            await stub.fetch("https://store/put", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ key: "email:" + email, value: rec }),
            });
          }
        }
      }
      if (!rec?.license)
        return withCORS(json({ license: null }, 404), allowOrigin(request));
      return withCORS(json(rec), allowOrigin(request));
    }
    if (request.method === "POST" && url.pathname === "/api/portal/session") {
      let email = "";
      try {
        const body = await request.json<any>();
        email = (body?.email || "").toLowerCase().trim();
      } catch {}
      if (!email)
        return withCORS(
          json({ error: "missing_email" }, 400),
          allowOrigin(request),
        );
      const listRes = await fetch(
        "https://api.stripe.com/v1/customers?limit=1&email=" +
          encodeURIComponent(email),
        { headers: { Authorization: `Bearer ${env.STRIPE_SECRET_KEY}` } },
      );
      const list = await listRes.json<any>();
      const customer = list?.data?.[0];
      if (!customer?.id)
        return withCORS(
          json({ error: "customer_not_found" }, 404),
          allowOrigin(request),
        );
      const pr = await fetch(
        "https://api.stripe.com/v1/billing_portal/sessions",
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${env.STRIPE_SECRET_KEY}`,
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body: new URLSearchParams({
            customer: customer.id,
            return_url: env.PORTAL_RETURN_URL || env.APP_BASE_URL,
          }),
        },
      );
      const portal = await pr.json<any>();
      if (!pr.ok) return withCORS(json(portal, 400), allowOrigin(request));
      return withCORS(json({ url: portal.url }), allowOrigin(request));
    }
    if (request.method === "GET" && url.pathname === "/__admin/by-email") {
      const k = url.searchParams.get("k") || "";
      if (!env.ADMIN_KEY || k !== env.ADMIN_KEY)
        return withCORS(
          json({ error: "forbidden" }, 403),
          allowOrigin(request),
        );
      const email = (url.searchParams.get("email") || "").toLowerCase().trim();
      if (!email)
        return withCORS(
          json({ error: "missing_email" }, 400),
          allowOrigin(request),
        );
      const rec = await readFromDO(env, "email:" + email);
      return withCORS(json(rec || { license: null }), allowOrigin(request));
    }
    return json({ error: "not_found" }, 404);
  },
};
