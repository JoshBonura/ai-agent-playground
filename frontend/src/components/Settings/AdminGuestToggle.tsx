import { useEffect, useState } from "react";
import { getAdminState, setGuestEnabled } from "../../api/admins";

export default function AdminGuestToggle() {
  const [isAdmin, setIsAdmin] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await getAdminState();
        if (!cancelled) {
          setIsAdmin(!!s.isAdmin);
          setEnabled(!!s.guestEnabled);
        }
      } catch (e: any) {
        if (!cancelled) setErr(e?.message || "Failed to load admin state");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!isAdmin) return null;

  return (
    <div className="flex items-center gap-3 text-sm">
      <label className="inline-flex items-center gap-2">
        <input
          type="checkbox"
          checked={enabled}
          disabled={busy}
          onChange={async (e) => {
            const next = e.target.checked;
            setBusy(true);
            setErr(null);
            try {
              const res = await setGuestEnabled(next);
              setEnabled(res.enabled);
            } catch (e: any) {
              setErr(e?.message || "Failed to update guest access");
            } finally {
              setBusy(false);
            }
          }}
        />
        Allow guest access on my network
      </label>
      {busy && <span className="text-xs text-gray-500">Saving…</span>}
      {err && <span className="text-xs text-red-600">{err}</span>}
    </div>
  );
}
