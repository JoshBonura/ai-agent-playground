import { useEffect, useMemo, useState } from "react";
import { useSettings } from "../hooks/useSettings";
import WebSearchSection from "../components/Settings/WebSearchSection";
import { useAuth } from "../auth/AuthContext";                      // ⬅️ NEW
import UpgradeSection from "../components/Settings/UpgradeSection"; // ⬅️ NEW

type Tab =
  | "general"
  | "notifications"
  | "personalization"
  | "connectors"
  | "schedules"
  | "datacontrols"
  | "security"
  | "account"
  | "developer";

const NAV: { key: Tab; label: string }[] = [
  { key: "general", label: "General" },
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
    error,
    effective,
    overrides,
    defaults,
    adaptive,
    saveOverrides,
    runAdaptive,
    reload,
  } = useSettings(sessionId);

  const { user, token } = useAuth(); // ⬅️ NEW

  const [tab, setTab] = useState<Tab>("general");

  // Developer JSON views
  const [devSubtab, setDevSubtab] = useState<"effective" | "overrides" | "adaptive" | "defaults">("effective");
  const [draft, setDraft] = useState(() => JSON.stringify(overrides ?? {}, null, 2));
  const [saveBusy, setSaveBusy] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);

  useEffect(() => {
    setDraft(JSON.stringify(overrides ?? {}, null, 2));
  }, [overrides]);

  const devView = useMemo(() => {
    switch (devSubtab) {
      case "effective":
        return effective;
      case "adaptive":
        return adaptive;
      case "defaults":
        return defaults;
      case "overrides":
        return null;
    }
  }, [devSubtab, effective, adaptive, defaults]);

  async function onSaveDev(method: "patch" | "put") {
    setSaveErr(null);
    setSaveBusy(true);
    try {
      const parsed = draft.trim() ? JSON.parse(draft) : {};
      await saveOverrides(parsed, method);
    } catch (e: any) {
      setSaveErr(e?.message || "Invalid JSON or save failed");
    } finally {
      setSaveBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-3">
      <div className="w-full max-w-5xl h-[90vh] rounded-2xl bg-white shadow-xl border overflow-hidden flex">
        {/* Sidebar */}
        <aside className="w-60 border-r bg-gray-50/60">
          <div className="px-4 py-3 text-sm font-semibold">Settings</div>
          <nav className="px-2 pb-3 space-y-1">
            {NAV.map((item) => (
              <button
                key={item.key}
                onClick={() => setTab(item.key)}
                className={`w-full text-left px-3 py-2 rounded-lg text-sm ${
                  tab === item.key ? "bg-black text-white" : "hover:bg-gray-100"
                }`}
              >
                {item.label}
              </button>
            ))}
          </nav>
          <div className="px-3 pt-2 mt-auto hidden md:block">
            <button
              className="w-full text-xs px-3 py-2 rounded border hover:bg-gray-100"
              onClick={() => reload()}
              title="Reload settings"
            >
              Reload
            </button>
            <button
              className="w-full mt-2 text-xs px-3 py-2 rounded border hover:bg-gray-100"
              onClick={() => runAdaptive()}
              title="Recompute adaptive"
            >
              Recompute Adaptive
            </button>
            <button
              className="w-full mt-2 text-xs px-3 py-2 rounded border hover:bg-gray-100"
              onClick={onClose}
              title="Close"
            >
              Close
            </button>
          </div>
        </aside>

        {/* Main */}
        <section className="flex-1 min-w-0 flex flex-col">
          <header className="px-5 py-4 border-b">
            <div className="text-base font-semibold capitalize">
              {tab.replace(/([a-z])([A-Z])/g, "$1 $2")}
            </div>
            {loading && <div className="text-xs text-gray-500 mt-1">Loading…</div>}
            {error && <div className="text-xs text-red-600 mt-1">{error}</div>}
          </header>

          <div className="flex-1 overflow-auto p-5">
            {tab === "general" && (
              <div className="space-y-6">
                <Section title="Appearance">
                  <Row label="Theme">
                    <select className="border rounded px-2 py-1 text-sm">
                      <option>System</option>
                      <option>Light</option>
                      <option>Dark</option>
                    </select>
                  </Row>
                  <Row label="Accent color">
                    <select className="border rounded px-2 py-1 text-sm">
                      <option>Default</option>
                      <option>Blue</option>
                      <option>Green</option>
                      <option>Purple</option>
                    </select>
                  </Row>
                  <Row label="Language">
                    <select className="border rounded px-2 py-1 text-sm">
                      <option>Auto-detect</option>
                      <option>English</option>
                      <option>Spanish</option>
                      <option>French</option>
                    </select>
                  </Row>
                </Section>

                <Section title="Web & Integrations">
                  <WebSearchSection
                    onSaved={() => {
                      // reflect to backend that web search is enabled (no key transmitted)
                      saveOverrides({
                        web_search_provider: "brave",
                        brave_worker_url: "",
                        brave_api_key_present: true,
                      });
                    }}
                  />
                </Section>
              </div>
            )}

            {tab === "account" && ( // ⬅️ NEW: Upgrade lives here
              <div className="space-y-6">
                <UpgradeSection token={token} userEmail={user?.email ?? ""} />
                {/* Add other account/profile sections here as needed */}
              </div>
            )}

            {tab === "developer" && (
              <div className="space-y-4">
                <div className="flex items-center gap-2">
                  {(["effective", "overrides", "adaptive", "defaults"] as const).map((k) => (
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
                      Edit <code>user_overrides</code> JSON. Use <b>Patch</b> to merge or <b>Replace</b> to overwrite.
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
            )}

            {/* Stubs for other tabs (expand later) */}
            {tab !== "general" && tab !== "developer" && tab !== "account" && (
              <div className="text-sm text-gray-500">This section is coming soon.</div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border p-4">
      <div className="font-semibold mb-3">{title}</div>
      {children}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 py-2">
      <div className="w-44 text-sm text-gray-600">{label}</div>
      <div className="flex-1">{children}</div>
    </div>
  );
}
