import { buildUrl } from "../services/http";

export async function refreshLicense(force = false) {
  const r = await fetch(buildUrl(`/license/refresh?force=${force ? "true" : "false"}`), {
    method: "POST",
    credentials: "include",
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
