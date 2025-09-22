// Single source of truth for Settings tabs.
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
