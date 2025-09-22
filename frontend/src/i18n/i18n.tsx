// src/i18n/i18n.tsx
import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import { loadLocaleDict } from "./loaders";

export interface Dict { [key: string]: string | Dict; }
export type Locale = "en" | "es";
const FALLBACK: Locale = "en";
const STORAGE_KEY = "lm/locale";

function getInitialLocale(): Locale {
  try {
    const stored = (localStorage.getItem(STORAGE_KEY) || "").trim() as Locale;
    if (stored) return stored;
  } catch {}
  const nav = ((typeof navigator !== "undefined" && navigator.language) || "en").slice(0, 2) as Locale;
  return (["en", "es"] as const).includes(nav) ? nav : FALLBACK;
}

// src/i18n/i18n.tsx
function pick(dict: Dict, path: string): string | undefined {
  // 1) try nested lookup: dict.systemResources.title
  const parts = path.split(".");
  let cur: any = dict;
  for (const k of parts) {
    if (cur == null) break;
    cur = cur[k];
  }
  if (typeof cur === "string") return cur;

  // 2) fallback to flat-dot key: dict["systemResources.title"]
  const flat = (dict as any)[path];
  return typeof flat === "string" ? flat : undefined;
}


function interpolate(s: string, vars?: Record<string, string | number>) {
  if (!vars) return s;
  return s.replace(/\{\{\s*(\w+)\s*\}\}/g, (_, k) => String(vars[k] ?? ""));
}

type I18nCtx = {
  locale: Locale;
  dict: Dict;
  t: (key: string, vars?: Record<string, string | number>) => string;
  setLocale: React.Dispatch<React.SetStateAction<Locale>>;
};

const Ctx = createContext<I18nCtx | null>(null);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocale] = useState<Locale>(getInitialLocale());
  const [dict, setDict] = useState<Dict>({});

  useEffect(() => {
    let mounted = true;
    (async () => {
      const merged = await loadLocaleDict(locale, FALLBACK);
      if (mounted) {
        setDict(merged);
        try { localStorage.setItem(STORAGE_KEY, locale); } catch {}
      }
    })();
    return () => { mounted = false; };
  }, [locale]);

  const t = useMemo(() => (key: string, vars?: Record<string, string | number>) => {
    const raw = pick(dict, key) ?? key;
    return interpolate(raw, vars);
  }, [dict]);

  const value = useMemo(() => ({ locale, dict, t, setLocale }), [locale, dict, t]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useI18n = () => {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useI18n must be used under <I18nProvider>");
  return ctx;
};
