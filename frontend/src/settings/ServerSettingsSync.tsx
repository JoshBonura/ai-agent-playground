// src/settings/ServerSettingsSync.tsx
import { useEffect } from "react";
import { getEffective } from "../data/settingsApi";
import { useI18n } from "../i18n/i18n";

export default function ServerSettingsSync() {
  const { setLocale } = useI18n();

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const eff = await getEffective();
        if (!alive) return;

        // Language
        const locale = (eff.ui_locale as string) || "auto";
        if (locale !== "auto") setLocale(locale as any);

        // Theme
        const theme = (eff.ui_theme as string) || "system";
        document.documentElement.dataset.theme = theme;

        // Accent (optional CSS var)
        const accent = (eff.ui_accent as string) || "default";
        document.documentElement.style.setProperty("--accent", accent);

        // Feature flags (stash wherever you like)
        (window as any).__flags = eff.feature_flags || {};
      } catch {
        // ignore – use client fallbacks
      }
    })();
    return () => { alive = false; };
  }, [setLocale]);

  return null;
}
