// frontend/src/file_read/settings/AdminDeviceManager.tsx
import { useEffect, useState } from "react";
import { listDevices, revokeDevice, renameDevice, recheckActivation, type DeviceRec } from "../../api/devices";

export default function AdminDeviceManager() {
  const [rows, setRows] = useState<DeviceRec[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [draftName, setDraftName] = useState<string>("");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function reload() {
    setErr(null);
    setLoading(true);
    try {
      const data = await listDevices();
      setRows(data);
    } catch (e: any) {
      setErr(e?.message || "Failed to load devices");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void reload(); }, []);

  async function onRevoke(id: string) {
    setBusyId(id);
    setErr(null);
    try {
      await revokeDevice(id);
      const wasCurrent = rows.find(r => r.id === id)?.isCurrent;
      await reload();
      if (wasCurrent) {
        await recheckActivation();
        location.reload();
      }
    } catch (e: any) {
      setErr(e?.message || "Failed to revoke device");
    } finally {
      setBusyId(null);
    }
  }

  function startRename(r: DeviceRec) {
    setRenamingId(r.id);
    setDraftName(r.name ?? "");
  }

  async function saveRename(id: string) {
    setBusyId(id);
    setErr(null);
    try {
      await renameDevice(id, draftName);
      await reload();
      setRenamingId(null);
    } catch (e: any) {
      setErr(e?.message || "Failed to rename device");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) return <div className="text-xs text-gray-500">Loading devices…</div>;
  if (err) return <div className="text-xs text-red-600">{err}</div>;
  if (!rows.length) return <div className="text-sm text-gray-600">No activated devices yet.</div>;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-gray-600">
            <th className="py-2 pr-3">Name</th>
            <th className="py-2 pr-3">Device ID</th>
            <th className="py-2 pr-3">Platform</th>
            <th className="py-2 pr-3">App</th>
            <th className="py-2 pr-3">Last seen</th>
            <th className="py-2 pr-3">Status</th>
            <th className="py-2 pr-3"></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t">
              <td className="py-2 pr-3">
                {renamingId === r.id ? (
                  <div className="flex items-center gap-2">
                    <input
                      className="border rounded px-2 py-1 text-xs w-40"
                      value={draftName}
                      onChange={(e) => setDraftName(e.target.value)}
                      placeholder="Optional name"
                      disabled={!!busyId}
                    />
                    <button
                      className="text-xs px-2 py-1 rounded border hover:bg-gray-50 disabled:opacity-50"
                      disabled={!!busyId}
                      onClick={() => saveRename(r.id)}
                    >
                      Save
                    </button>
                    <button
                      className="text-xs px-2 py-1 rounded border hover:bg-gray-50"
                      onClick={() => setRenamingId(null)}
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <span>{r.name || <span className="text-gray-400">—</span>}</span>
                    <button
                      className="text-xs px-2 py-0.5 rounded border hover:bg-gray-50"
                      onClick={() => startRename(r)}
                      title="Rename device"
                    >
                      Rename
                    </button>
                  </div>
                )}
              </td>
              <td className="py-2 pr-3 font-mono text-[11px] break-all">{r.id}</td>
              <td className="py-2 pr-3">{r.platform || "—"}</td>
              <td className="py-2 pr-3">{r.appVersion || "—"}</td>
              <td className="py-2 pr-3">{r.lastSeen ? new Date(r.lastSeen).toLocaleString() : "—"}</td>
              <td className="py-2 pr-3">
                {r.isCurrent ? (
                  <span className="inline-flex items-center rounded bg-emerald-600/10 text-emerald-700 px-2 py-0.5 text-xs">Current</span>
                ) : (
                  <span className="inline-flex items-center rounded bg-gray-200 px-2 py-0.5 text-xs">Other</span>
                )}
              </td>
              <td className="py-2 pr-3 text-right">
                <button
                  className="text-xs px-2 py-1 rounded border hover:bg-gray-50 disabled:opacity-50"
                  disabled={!!busyId}
                  onClick={() => onRevoke(r.id)}
                  title={r.isCurrent ? "Revoke this device (you will drop to Free here)" : "Revoke this device"}
                >
                  {busyId === r.id ? "Revoking…" : r.isCurrent ? "Revoke this device" : "Revoke"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
