// aimodel/file_read/cloudflare/license-do.ts
import type { DurableObjectState, DurableObjectStorage } from "@cloudflare/workers-types";

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
      if (!key || !value) return new Response(JSON.stringify({ error: "bad_request" }), { status: 400, headers: { "content-type": "application/json" } });
      await this.storage.put(key, value);
      return new Response(null, { status: 204 });
    }
    if (req.method === "GET" && url.pathname === "/get") {
      const key = url.searchParams.get("key") || "";
      const value = await this.storage.get<any>(key);
      return new Response(JSON.stringify(value ?? null), { status: 200, headers: { "content-type": "application/json" } });
    }
    return new Response("not found", { status: 404 });
  }
}
