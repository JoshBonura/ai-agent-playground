// frontend/src/components/Settings/SettingsSidebar.tsx
import type { Dispatch, SetStateAction } from "react";

export type Tab =
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

export type NavItem = { key: Tab; label: string };

type Props = {
  tab: Tab;
  setTab: Dispatch<SetStateAction<Tab>>;
  navItems: NavItem[];
  onReload: () => void;
  onClose?: () => void;
};

export default function SettingsSidebar({
  tab,
  setTab,
  navItems,
  onReload,
  onClose,
}: Props) {
  return (
    <aside className="w-60 border-r p-3 flex flex-col">
      <div className="text-sm font-semibold mb-2">Settings</div>
      <nav className="space-y-1 mb-3">
        {navItems.map((it) => (
          <button
            key={it.key}
            onClick={() => setTab(it.key)}
            className={`w-full text-left text-sm px-3 py-2 rounded ${
              tab === it.key ? "bg-black text-white" : "hover:bg-gray-50 border"
            }`}
            title={it.label}
          >
            {it.label}
          </button>
        ))}
      </nav>
      <div className="mt-auto flex flex-col gap-2">
        <button
          className="text-xs px-3 py-2 rounded border hover:bg-gray-50"
          onClick={onReload}
          title="Reload settings"
        >
          Reload
        </button>
        {onClose && (
          <button
            className="text-xs px-3 py-2 rounded border hover:bg-gray-50"
            onClick={onClose}
            title="Close"
          >
            Close
          </button>
        )}
      </div>
    </aside>
  );
}
