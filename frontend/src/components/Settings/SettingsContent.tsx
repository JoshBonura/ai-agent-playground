import SettingsContentCore from "./SettingsContent.Core";
import SettingsContentAdminDev from "./SettingsContent.AdminDev";
import HardwareSection from "./hardware/HardwareSection";
import type { AdminState } from "../../api/admins";

// duplicate union here to avoid another file
type Tab =
  | "general"
  | "hardware"
  | "notifications"
  | "personalization"
  | "connectors"
  | "schedules"
  | "datacontrols"
  | "security"
  | "account"
  | "developer"
  | "admin";

type Props = {
  tab: Tab;
  userEmail: string;

  loading: boolean;
  loadingSoft?: boolean; // ← NEW

  error: string | null;
  adminErr: string | null;

  effective: Record<string, any> | null;
  overrides: Record<string, any> | null;
  defaults: Record<string, any> | null;

  adminState: AdminState | null;

  saveOverrides: (
    payload: Record<string, any>,
    method?: "patch" | "put",
  ) => Promise<void>;
};

export default function SettingsContent(p: Props) {
  return (
    <section className="flex-1 min-w-0 flex flex-col">
      <header className="px-5 py-4 border-b">
        <div className="text-base font-semibold capitalize">
          {p.tab.replace(/([a-z])([A-Z])/g, "$1 $2")}
        </div>

        {/* Only show Loading… for hard loads (not soft refresh) */}
        {p.loading && !p.loadingSoft && (
          <div className="text-xs text-gray-500 mt-1">Loading…</div>
        )}

        {p.error && <div className="text-xs text-red-600 mt-1">{p.error}</div>}
        {p.adminErr && p.tab === "admin" && (
          <div className="text-xs text-red-600 mt-1">{p.adminErr}</div>
        )}
      </header>

      <div className="flex-1 overflow-auto p-5">
        {p.tab === "hardware" && (
          <HardwareSection
            effective={p.effective}
            overrides={p.overrides}
            saveOverrides={p.saveOverrides}
          />
        )}

        {(p.tab === "general" || p.tab === "account") && (
          <SettingsContentCore
            tab={p.tab}
            effective={p.effective}
            overrides={p.overrides}
            saveOverrides={p.saveOverrides}
            userEmail={p.userEmail}
          />
        )}

        {(p.tab === "admin" || p.tab === "developer") && (
          <SettingsContentAdminDev
            tab={p.tab}
            effective={p.effective}
            overrides={p.overrides}
            defaults={p.defaults}
            saveOverrides={p.saveOverrides}
            adminState={p.adminState}
          />
        )}

        {/* Stubs for other tabs */}
        {p.tab !== "hardware" &&
          p.tab !== "general" &&
          p.tab !== "account" &&
          p.tab !== "admin" &&
          p.tab !== "developer" && (
            <div className="text-sm text-gray-500">This section is coming soon.</div>
          )}
      </div>
    </section>
  );
}
