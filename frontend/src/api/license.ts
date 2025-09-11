import { buildUrl } from "../services/http";

export async function refreshLicense(force = false) {
  const r = await fetch(
    buildUrl(`/license/refresh?force=${force ? "true" : "false"}`),
    {
      method: "POST",
      credentials: "include",
    },
  );
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function applyLicense(license: string) {
  const r = await fetch(buildUrl(`/license/apply`), {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ license }),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
