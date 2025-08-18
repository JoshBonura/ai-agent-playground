// frontend/src/file_read/hooks/useTheme.ts
import { useEffect, useState } from "react";

type Theme = "light" | "dark";
const KEY = "theme";

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = (localStorage.getItem(KEY) as Theme) || null;
    if (saved) return saved;
    const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
    return prefersDark ? "dark" : "light";
  });

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "dark") root.classList.add("dark");
    else root.classList.remove("dark");
    localStorage.setItem(KEY, theme);
  }, [theme]);

  const toggle = () => setTheme(t => (t === "dark" ? "light" : "dark"));
  return { theme, toggle };
}
