import { useEffect, useMemo, useState } from "react";
import AdminBanner from "../AdminBanner";
import AdminManagement from "../AdminManagement";
import AdminScopeToggle from "./AdminScopeToggle";
import AdminGuestToggle from "./AdminGuestToggle";
import AdminDeviceManager from "./AdminDeviceManager";
import type { AdminState } from "../../api/admins";

type Props = {
  /** Which advanced tab to render: "admin" or "developer" */
  tab: "admin" | "developer";
  /** Settings from useSettings() */
  effective: Record<string, any> | null;
  overrides: Record<string, any> | null;
  defaults: Record<string, any> | null;
  saveOverrides: (obj: Record<string, any>, method?: "patch" | "put") => Promise<any>;
  /** Admin */
  adminState: AdminState | null;
};

export default function SettingsContentAdminDev(p: Props) {
  if (p.tab !== "admin" && p.tab !== "developer") return null;

  if (p.tab === "admin") {
    return (
      <div className="space-y-6">
        <AdminBanner />
        <AdminManagement />

        <Section title="Admin controls">
          <div className="text-xs text-gray-600 mb-2">
            Choose whether your sidebar shows only your chats or all users’ chats (admins only).
          </div>
          <AdminScopeToggle />
          <div className="mt-3">
            <AdminGuestToggle />
          </div>
        </Section>

        <Section title="Pro device access">
          <div className="text-xs text-gray-600 mb-2">
            Manage which machines are activated to use Pro. Revoking the current device will
            immediately switch this app to Free.
          </div>
          <AdminDeviceManager />
        </Section>
      </div>
    );
  }

  // p.tab === "developer"
  const [devSubtab, setDevSubtab] = useState<"effective" | "overrides" | "defaults">(
    "effective",
  );
  const [draft, setDraft] = useState(() => JSON.stringify(p.overrides ?? {}, null, 2));
  const [saveBusy, setSaveBusy] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  useEffect(() => {
    setDraft(JSON.stringify(p.overrides ?? {}, null, 2));
  }, [p.overrides]);

  const devView = useMemo(() => {
    switch (devSubtab) {
      case "effective":
        return p.effective;
      case "defaults":
        return p.defaults;
      case "overrides":
        return null;
    }
  }, [devSubtab, p.effective, p.defaults]);

  async function onSaveDev(method: "patch" | "put") {
    setSaveErr(null);
    setSaveBusy(true);
    try {
      const parsed = draft.trim() ? JSON.parse(draft) : {};
      await p.saveOverrides(parsed, method);
    } catch (e: any) {
      setSaveErr(e?.message || "Invalid JSON or save failed");
    } finally {
      setSaveBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        {(["effective", "overrides", "defaults"] as const).map((k) => (
          <button
            key={k}
            onClick={() => setDevSubtab(k)}
            className={`text-xs mr-2 px-3 py-1.5 rounded ${
              devSubtab === k ? "bg-black text-white" : "border hover:bg-gray-50"
            }`}
          >
            {k}
          </button>
        ))}
      </div>

      {devSubtab !== "overrides" && (
        <pre className="text-xs bg-gray-50 border rounded p-3 overflow-auto max-h-[60vh]">
          {JSON.stringify(devView ?? {}, null, 2)}
        </pre>
      )}

      {devSubtab === "overrides" && (
        <div className="space-y-2">
          <div className="text-xs text-gray-600">
            Edit <code>user_overrides</code> JSON. Use <b>Patch</b> to merge or <b>Replace</b> to
            overwrite.
          </div>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-full h-[50vh] border rounded p-2 font-mono text-xs"
            spellCheck={false}
          />
          <div className="flex items-center gap-2">
            <button
              className={`text-xs px-3 py-1.5 rounded ${
                saveBusy ? "opacity-60 cursor-not-allowed" : "bg-black text-white"
              }`}
              disabled={saveBusy}
              onClick={() => onSaveDev("patch")}
              title="Deep-merge with existing overrides"
            >
              Save (Patch)
            </button>
            <button
              className={`text-xs px-3 py-1.5 rounded border ${
                saveBusy ? "opacity-60 cursor-not-allowed" : "hover:bg-gray-50"
              }`}
              disabled={saveBusy}
              onClick={() => onSaveDev("put")}
              title="Replace overrides entirely"
            >
              Save (Replace)
            </button>
            {saveErr && <div className="text-xs text-red-600 ml-2">{saveErr}</div>}
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------- tiny UI helpers (local to this file) ---------- */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border p-4">
      <div className="font-semibold mb-3">{title}</div>
      {children}
    </div>
  );
}
