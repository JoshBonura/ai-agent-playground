import { request } from "../services/http";

export type AdminState = {
  hasAdmin: boolean;
  isAdmin: boolean; // use this to gate admin UI
  isAdminRaw?: boolean; // optional: listed but maybe not Pro
  ownerUid?: string | null;
  ownerEmail?: string | null;

  guestEnabled: boolean; // guest toggle in settings
  canSelfPromote: boolean; // show self-promote banner

  me: { uid: string; email: string; pro: boolean };
};

export const getAdminState = () => request<AdminState>("/api/admins/state");

export const selfPromote = () =>
  request<{ ok: boolean }>("/api/admins/self-promote", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });

export const setGuestEnabled = (enabled: boolean) =>
  request<{ ok: boolean; enabled: boolean }>("/api/admins/guest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
