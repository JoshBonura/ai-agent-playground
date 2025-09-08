import { buildUrl } from "../services/http";

export async function localRegister(email: string, password: string) {
  const r = await fetch(buildUrl("/auth/register"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, password }),
  });
  if (!r.ok) throw new Error(await r.text());
}

export async function localLogin(email: string, password: string) {
  const r = await fetch(buildUrl("/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, password }),
  });
  if (!r.ok) throw new Error(await r.text());
  try { localStorage.setItem("profile_email", email); } catch {}
}

export async function localLogout() {
  await fetch(buildUrl("/auth/logout"), { method: "POST", credentials: "include" });
}
