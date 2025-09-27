// aimodel/file_read/cloudflare/common.ts

export const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "content-type, authorization, stripe-signature",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

export function withCORS(res: Response, origin: string = "*") {
  const h = new Headers(res.headers);
  for (const [k, v] of Object.entries(CORS)) h.set(k, v as string);
  h.set("Access-Control-Allow-Origin", origin);
  h.set("Vary", "Origin");
  return new Response(res.body, { status: res.status, headers: h });
}

export const allowOrigin = (req: Request) => req.headers.get("Origin") || "*";

export function html(body: string, status = 200, headers: Record<string, string> = {}) {
  return withCORS(new Response(body, {
    status,
    headers: { "content-type": "text/html; charset=utf-8", ...headers },
  }));
}

export function json(data: unknown, status = 200) {
  return withCORS(new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  }));
}

export function bad(status: number, message: string) {
  return json({ error: message }, status);
}

export function b64u(data: Uint8Array): string {
  let s = btoa(String.fromCharCode(...data));
  return s.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}
export function strToB64u(s: string) {
  return b64u(new TextEncoder().encode(s));
}

export async function hmac256Hex(secret: string, payload: string) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(payload));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// ✅ Add this:
export const nowSec = () => Math.floor(Date.now() / 1000);
