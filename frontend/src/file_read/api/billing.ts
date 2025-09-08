// frontend/src/file_read/api/billing.ts
import { buildUrl, getJSON } from "../services/http";

export type BillingStatus = { status: string; current_period_end: number };

export async function getBillingStatus() {
  // getJSON already wraps fetch with credentials: "include"
  return getJSON<BillingStatus>("/billing/status");
}

export async function startCheckout(priceId?: string) {
  const r = await fetch(buildUrl("/billing/checkout"), {
    method: "POST",
    credentials: "include",
    headers: { "Accept": "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ price_id: priceId }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ url: string }>;
}

export async function openPortal() {
  const r = await fetch(buildUrl("/billing/portal"), {
    method: "POST",
    credentials: "include",
    headers: { "Accept": "application/json" },
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<{ url: string }>;
}
