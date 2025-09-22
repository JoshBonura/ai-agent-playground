// frontend/src/components/Settings/SettingsContent.Core.tsx
import { useEffect, useState } from "react";
import WebSearchSection from "./WebSearchSection";
import UpgradeSection from "./UpgradeSection";
import { useI18n, type Locale } from "../../i18n/i18n";

/* ---------------- Types ---------------- */
type CoreTab = "general" | "account" | "hardware"; // keep type for parent prop

type Props = {
  /** Which core tab to render */
  tab: CoreTab;
  /** Settings from useSettings() */
  effective: Record<string, any> | null;
  overrides: Record<string, any> | null;
  saveOverrides: (obj: Record<string, any>, method?: "patch" | "put") => Promise<any>;
  /** Account info for <UpgradeSection /> */
  userEmail: string;
};

const SUPPORTED: Locale[] = ["en", "es"];
type LangSetting = "auto" | Locale;

/* ---------------- Helpers ---------------- */
function resolveAuto(): Locale {
  const nav = (typeof navigator !== "undefined" && navigator.language) || "en";
  const two = nav.slice(0, 2) as Locale;
  return SUPPORTED.includes(two) ? two : "en";
}

/* ============================================================================
   Component
============================================================================ */

export default function SettingsContentCore(p: Props) {
  // NOTE: This file now ONLY renders "general" and "account".
  if (p.tab === "account") {
    return (
      <section className="flex-1 min-w-0 flex flex-col">
        <header className="px-5 py-4 border-b">
          <div className="text-base font-semibold">Account</div>
        </header>
        <div className="p-5">
          <Section title="Account">
            <UpgradeSection userEmail={p.userEmail} />
          </Section>
        </div>
      </section>
    );
  }

  // default to General
  return <GeneralAppearanceSection {...p} />;
}

/* ============================================================================
   General tab (appearance + web)
============================================================================ */

function GeneralAppearanceSection(p: Props) {
  const uiTheme = (p.effective?.ui_theme as string) || "system";
  async function onChangeTheme(next: string) {
    document.documentElement.dataset.theme = next; // apply instantly
    await p.saveOverrides({ ui_theme: next }, "patch");
  }

  const uiAccent = (p.effective?.ui_accent as string) || "default";
  async function onChangeAccent(next: string) {
    document.documentElement.style.setProperty("--accent", next);
    await p.saveOverrides({ ui_accent: next }, "patch");
  }

  const { setLocale } = useI18n();
  const [lang, setLang] = useState<LangSetting>(
    ((p.overrides?.ui_locale as LangSetting) || "auto") as LangSetting,
  );
  useEffect(() => {
    setLang(((p.overrides?.ui_locale as LangSetting) || "auto") as LangSetting);
  }, [p.overrides?.ui_locale]);

  async function onChangeLanguage(next: LangSetting) {
    setLang(next);
    const resolved = next === "auto" ? resolveAuto() : next;
    setLocale(resolved);
    await p.saveOverrides({ ui_locale: next }, "patch");
  }

  return (
    <section className="flex-1 min-w-0 flex flex-col">
      <header className="px-5 py-4 border-b">
        <div className="text-base font-semibold">General</div>
      </header>

      <div className="flex-1 overflow-auto p-5 space-y-6">
        <Section title="Appearance">
          <Row label="Theme">
            <select
              className="border rounded px-2 py-1 text-sm"
              value={uiTheme}
              onChange={(e) => onChangeTheme(e.target.value)}
            >
              <option value="system">System</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </Row>

          <Row label="Accent color">
            <select
              className="border rounded px-2 py-1 text-sm"
              value={uiAccent}
              onChange={(e) => onChangeAccent(e.target.value)}
            >
              <option value="default">Default</option>
              <option value="blue">Blue</option>
              <option value="green">Green</option>
              <option value="purple">Purple</option>
            </select>
          </Row>

          <Row label="Language">
            <select
              className="border rounded px-2 py-1 text-sm"
              value={lang}
              onChange={(e) => onChangeLanguage(e.target.value as LangSetting)}
            >
              <option value="auto">Auto-detect</option>
              <option value="en">English</option>
              <option value="es">Español</option>
            </select>
          </Row>
        </Section>

        <Section title="Web & Integrations">
          <WebSearchSection
            onSaved={() =>
              p.saveOverrides(
                {
                  web_search_provider: "brave",
                  brave_worker_url: "",
                  brave_api_key_present: true,
                },
                "patch",
              )
            }
          />
        </Section>
      </div>
    </section>
  );
}

/* ---------------- Little UI helpers ---------------- */

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
