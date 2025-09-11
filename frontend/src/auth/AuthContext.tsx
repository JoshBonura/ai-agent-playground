// frontend/src/file_read/auth/AuthContext.tsx
import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { getJSON } from "../services/http";
import { refreshLicense } from "../api/license";

type LocalUser = { email?: string; name?: string };

type Ctx = {
  user: LocalUser | null;
  loading: boolean;
  refreshMe: () => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<Ctx>({
  user: null,
  loading: true,
  refreshMe: async () => {},
  logout: async () => {},
});

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [user, setUser] = useState<LocalUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [justLoggedOutAt, setJustLoggedOutAt] = useState<number>(0);

  const hardLogoutLocal = () => {
    try {
      localStorage.removeItem("profile_email");
    } catch {}
    setUser(null);
  };

  const logout = async () => {
    try {
      await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "include",
      });
    } catch {}
    hardLogoutLocal();
    setJustLoggedOutAt(Date.now());
  };

  const refreshMe = async () => {
    try {
      const me = await getJSON<LocalUser>("/auth/me");
      setUser(me || null);
      if (me?.email) {
        try {
          localStorage.setItem("profile_email", me.email);
        } catch {}
        try {
          window.dispatchEvent(new Event("auth:ready"));
        } catch {}
      }
      await refreshLicense().catch(() => {});
    } catch {
      hardLogoutLocal();
    }
  };
  // Initial load
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        if (Date.now() - justLoggedOutAt < 800) return;
        const me = await getJSON<LocalUser>("/auth/me");
        if (!cancelled) {
          setUser(me || null);
          if (me?.email) {
            try {
              localStorage.setItem("profile_email", me.email);
            } catch {}
            try {
              window.dispatchEvent(new Event("auth:ready"));
            } catch {}
          }
        }
      } catch {
        if (!cancelled) hardLogoutLocal();
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [justLoggedOutAt]);

  const ctx = useMemo<Ctx>(
    () => ({ user, loading, refreshMe, logout }),
    [user, loading],
  );

  return <AuthContext.Provider value={ctx}>{children}</AuthContext.Provider>;
};

export const useAuth = () => useContext(AuthContext);
