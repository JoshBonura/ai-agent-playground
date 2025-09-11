import { useEffect, useState } from "react";
import { getAdminState } from "../api/admins";

export default function AdminManagement() {
  const [state, setState] = useState<Awaited<
    ReturnType<typeof getAdminState>
  > | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function reload() {
    setErr(null);
    try {
      const s = await getAdminState();
      setState(s);
    } catch (e: any) {
      setErr(e?.message || "Failed to load admin state");
    }
  }

  useEffect(() => {
    reload();
  }, []);

  if (!state) return null;

  // Try to show the current admin (support both old & new shapes)
  const ownerFromList = (state as any).admins?.[0] as
    | { uid?: string; email?: string }
    | undefined;
  const ownerEmail =
    (state as any).ownerEmail ??
    ownerFromList?.email ??
    (state.isAdmin ? state.me.email : null);

  const ownerUid =
    (state as any).ownerUid ??
    (state as any).primaryUid ??
    ownerFromList?.uid ??
    (state.isAdmin ? state.me.uid : null);

  const hasAdmin =
    typeof (state as any).hasAdmin === "boolean"
      ? (state as any).hasAdmin
      : !!(state as any).hasAdmins; // <— add (state as any) here

  return (
    <div className="rounded-2xl border p-4">
      <div className="font-semibold mb-3">Admin status</div>

      <div className="text-sm space-y-2">
        <div>
          <span className="text-gray-600 mr-1">Admin account:</span>
          <b>
            {ownerEmail
              ? `${ownerEmail} (${ownerUid ?? "—"})`
              : hasAdmin
                ? "Unknown"
                : "—"}
          </b>
        </div>

        {state.isAdmin && (
          <div className="text-green-700">
            You are the admin on this device. Admin features are enabled for
            you.
          </div>
        )}

        {!state.isAdmin && hasAdmin && (
          <div className="text-gray-700">
            This device already has an admin. Admin controls are available only
            to that account.
          </div>
        )}

        {!hasAdmin && (
          <div className="text-amber-700">
            No admin yet. Use the “Make me admin” banner above (requires Pro) to
            claim admin.
          </div>
        )}
      </div>

      {err && <div className="mt-2 text-xs text-red-600">{err}</div>}
    </div>
  );
}
