// frontend/src/file_read/api/devices.ts
export type DeviceRec = {
  id: string;
  name?: string | null;
  platform?: string;
  appVersion?: string;
  lastSeen?: string;
  isCurrent?: boolean;
  exp?: number | null;
};

export async function listDevices(): Promise<DeviceRec[]> {
  const r = await fetch("/api/devices", { credentials: "include" });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function revokeDevice(id: string): Promise<{ ok: boolean }> {
  const r = await fetch(`/api/devices/${encodeURIComponent(id)}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function renameDevice(deviceId: string, name: string): Promise<void> {
  const r = await fetch(`/api/devices/rename`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ deviceId, name }),
  });
  if (!r.ok) throw new Error(await r.text());
}

export async function recheckActivation(): Promise<void> {
  await fetch("/api/activation/recheck", { method: "POST", credentials: "include" }).catch(() => {});
}
