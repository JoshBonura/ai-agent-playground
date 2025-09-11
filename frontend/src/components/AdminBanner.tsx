import { useEffect, useState } from "react";
import { getAdminState, selfPromote } from "../api/admins";

export default function AdminBanner() {
  const [can, setCan] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await getAdminState();
        if (!cancelled) setCan(!!s.canSelfPromote);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!can) return null;

  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm">
      <div className="font-medium text-amber-800">Admin setup</div>
      <div className="text-amber-800/90 mt-1">
        No admins exist yet. Click below to make yourself the first admin
        (requires Pro).
      </div>

      <button
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setErr(null);
          try {
            await selfPromote();
            location.reload();
          } catch (e: any) {
            setErr(e?.message || "Failed to self-promote");
          } finally {
            setBusy(false);
          }
        }}
        className="mt-2 inline-flex items-center rounded bg-black px-3 py-1.5 text-white disabled:opacity-60"
      >
        {busy ? "Promoting…" : "Make me admin"}
      </button>

      {err && <div className="mt-2 text-xs text-red-600">{err}</div>}
    </div>
  );
}
