// src/i18n/loaders.ts
import type { Dict } from "./i18n";

// These patterns are RELATIVE to this file (src/i18n).
// ../**/*.i18n.en.json  => matches under src/** (components, pages, etc.)
const componentBundles = {
  en: import.meta.glob("../**/*.i18n.en.json", { import: "default" }),
  es: import.meta.glob("../**/*.i18n.es.json", { import: "default" }),
} as const;

function deepMerge<T extends Record<string, any>>(a: T, b: T): T {
  const out: any = Array.isArray(a) ? [...a] : { ...a };
  for (const [k, v] of Object.entries(b || {})) {
    const cur = out[k];
    out[k] =
      cur && typeof cur === "object" && !Array.isArray(cur) &&
      v && typeof v === "object" && !Array.isArray(v)
        ? deepMerge(cur, v as any)
        : v;
  }
  return out;
}

export async function loadLocaleDict(
  locale: "en" | "es",
  fallback: "en" | "es",
): Promise<Dict> {
  const [{ default: base }, { default: fb }] = await Promise.all([
    import(`./locales/${locale}.json`),
    locale === fallback ? Promise.resolve({ default: {} }) : import(`./locales/${fallback}.json`),
  ]);

  // Load all collocated bundles for the chosen locale
  const mods = componentBundles[locale];
  const pieces = await Promise.all(Object.values(mods).map((loader) => loader() as Promise<Dict>));

  // Merge order: fallback → base → component bundles (components override base)
  let dict: Dict = deepMerge(fb as Dict, base as Dict);
  for (const piece of pieces) dict = deepMerge(dict, piece);
  return dict;
}
