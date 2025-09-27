import { useEffect, useMemo, useState } from "react";
import { useSettings } from "../../hooks/useSettings";
import { useAuth } from "../../auth/AuthContext";
import { getAdminState } from "../../api/admins";
import type { AdminState } from "../../api/admins";

import SettingsSidebar, { type Tab } from "./SettingsSidebar";
import SettingsContent from "./SettingsContent";

const BASE_NAV: { key: Tab; label: string }[] = [
  { key: "general", label: "General" },
  { key: "hardware", label: "Hardware" },
  { key: "runtime", label: "Runtime" },
  { key: "notifications", label: "Notifications" },
  { key: "personalization", label: "Personalization" },
  { key: "connectors", label: "Connectors" },
  { key: "schedules", label: "Schedules" },
  { key: "datacontrols", label: "Data controls" },
  { key: "security", label: "Security" },
  { key: "account", label: "Account" },
  { key: "developer", label: "Developer" },
];

export default function SettingsPanel({
  sessionId,
  onClose,
}: {
  sessionId?: string;
  onClose?: () => void;
}) {
  const {
    loading,
    loadingSoft,          // ← NEW from hook
    error,
    effective,
    overrides,
    defaults,
    saveOverrides,
    reload,
  } = useSettings(sessionId);

  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("general");

  const [adminState, setAdminState] = useState<AdminState | null>(null);
  const [adminErr, setAdminErr] = useState<string | null>(null);

  async function reloadAdminState() {
    try {
      const s = await getAdminState();
      setAdminState(s);
      setAdminErr(null);
    } catch (e: any) {
      setAdminState(null);
      setAdminErr(e?.message || "Failed to load admin state");
    }
  }

  useEffect(() => {
    void reloadAdminState();
  }, []);

  const navItems = useMemo(() => {
    const canSelfPromote = !!adminState?.canSelfPromote;
    const isAdmin = !!adminState?.isAdmin;
    const items: { key: Tab; label: string }[] = [...BASE_NAV];
    if (isAdmin || canSelfPromote) {
      items.splice(2, 0, { key: "admin", label: "Admin" });
    }
    return items;
  }, [adminState]);

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-3">
      <div className="w-full max-w-5xl h-[90vh] rounded-2xl bg-white shadow-xl border overflow-hidden flex">
        <SettingsSidebar
          tab={tab}
          setTab={setTab}
          navItems={navItems}
          onReload={reload}
          onClose={onClose}
        />

        <SettingsContent
          tab={tab}
          userEmail={user?.email ?? ""}
          loading={loading}
          loadingSoft={loadingSoft}  
          error={error}
          adminErr={adminErr}
          effective={effective}
          overrides={overrides}
          defaults={defaults}
          adminState={adminState}
          saveOverrides={saveOverrides}
        />
      </div>
    </div>
  );
}
