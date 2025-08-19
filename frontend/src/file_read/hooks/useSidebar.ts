// frontend/src/file_read/hooks/useSidebar.ts
import { useEffect, useState } from "react";

export function useSidebar() {
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 768);

  // pin on desktop
  useEffect(() => {
    const onResize = () => {
      if (window.innerWidth >= 768) setSidebarOpen(true);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // Ctrl+B toggle
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && (e.key === "b" || e.key === "B")) {
        e.preventDefault();
        setSidebarOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // mobile drawer helpers (DOM-level; safe here)
  const openMobileDrawer = () => {
    document.getElementById("mobile-drawer")?.classList.remove("hidden");
    document.getElementById("mobile-backdrop")?.classList.remove("hidden");
    document.body.style.overflow = "hidden";
  };
  const closeMobileDrawer = () => {
    document.getElementById("mobile-drawer")?.classList.add("hidden");
    document.getElementById("mobile-backdrop")?.classList.add("hidden");
    document.body.style.overflow = "";
  };

  return {
    sidebarOpen,
    setSidebarOpen,
    openMobileDrawer,
    closeMobileDrawer,
  };
}
