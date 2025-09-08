// frontend/src/file_read/components/ChatSidebar/AccountPanel.tsx
import { useEffect, useMemo, useState } from "react";
import { ChevronDown, LogOut, Settings, HelpCircle, Stars, BookOpen, Wand2, Save } from "lucide-react";
import { useAuth } from "../../auth/AuthContext";
import { buildUrl } from "../../services/http";


function initials(s: string) {
  const parts = (s || "").trim().split(/\s+/);
  if (!parts[0]) return "AC";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

export default function AccountPanel() {
  const { user } = useAuth(); // local auth context
  const [open, setOpen] = useState(false);

  // --- identity display (prefer context; fallback to localStorage) ---
  const storedEmail = typeof localStorage !== "undefined" ? localStorage.getItem("profile_email") || "" : "";
  const display = user?.email || storedEmail || "Account";
  const tier = "Pro";
  const avatarText = useMemo(() => initials(display), [display]);

  // --- license key management (used by proxy / app limits) ---
  const [license, setLicense] = useState<string>("");
  const [saved, setSaved] = useState<null | "ok" | "err">(null);

  useEffect(() => {
    try {
      setLicense(localStorage.getItem("license_key") || "");
    } catch {
      /* ignore */
    }
  }, []);

  function saveLicense() {
    try {
      if (license.trim()) {
        localStorage.setItem("license_key", license.trim());
      } else {
        localStorage.removeItem("license_key");
      }
      setSaved("ok");
      setTimeout(() => setSaved(null), 1500);
    } catch {
      setSaved("err");
      setTimeout(() => setSaved(null), 2000);
    }
  }

  // --- actions ---
  function openSettings() {
    try { window.dispatchEvent(new CustomEvent("open:settings")); } catch {}
    setOpen(false);
  }
  function openKnowledge() {
    try { window.dispatchEvent(new CustomEvent("open:knowledge")); } catch {}
    setOpen(false);
  }
  function openCustomize() {
    try { window.dispatchEvent(new CustomEvent("open:customize")); } catch {}
    setOpen(false);
  }
  function openHelp() {
    // Swap with your docs/help URL
    window.open("https://yourdocs.example.com", "_blank", "noopener,noreferrer");
    setOpen(false);
  }
function logout() {
  (async () => {
    try {
      await fetch(buildUrl("/auth/logout"), {
        method: "POST",
        credentials: "include",   // send the session cookie so the server can delete it
        headers: { "Accept": "application/json" },
      });
    } catch {}
    try {
      localStorage.removeItem("local_jwt");
      // optional: also clear profile_email, license_key if you want a full reset
      // localStorage.removeItem("profile_email");
      // localStorage.removeItem("license_key");
    } catch {}
    location.reload();            // simplest way to reset all app state
  })();
  setOpen(false);
}
  return (
    <div className="p-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-3 bg-gray-100 hover:bg-gray-200 active:bg-gray-300 transition rounded-xl px-3 py-2 text-left"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <div className="w-8 h-8 rounded-lg bg-slate-800 text-white grid place-items-center text-xs font-semibold">
          {avatarText}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium truncate">{display}</div>
          <div className="text-[11px] text-gray-600">
            <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px]">
              {tier}
            </span>
          </div>
        </div>
        <ChevronDown className={`w-4 h-4 transition ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="hidden md:block relative">
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} aria-hidden />
          <div role="menu" className="absolute z-40 bottom-14 left-2 right-2 rounded-xl border bg-white shadow-xl overflow-hidden">
            <div className="px-3 py-2 text-xs text-gray-600 border-b truncate">{display}</div>

            {/* License Key (for proxy/app rate-limits) */}
            <div className="px-3 py-3 border-b bg-gray-50/60">
              <div className="text-[11px] font-medium text-gray-600 mb-1">License key</div>
              <div className="flex items-center gap-2">
                <input
                  value={license}
                  onChange={(e) => setLicense(e.target.value)}
                  placeholder="paste-your-key"
                  className="flex-1 rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-black"
                  spellCheck={false}
                />
                <button
                  onClick={saveLicense}
                  className="inline-flex items-center gap-1 rounded-lg border px-3 py-2 text-sm hover:bg-gray-50"
                >
                  <Save size={16} /> Save
                </button>
              </div>
              {saved === "ok" && <div className="mt-1 text-[11px] text-green-600">Saved</div>}
              {saved === "err" && <div className="mt-1 text-[11px] text-red-600">Couldn’t save</div>}
            </div>

            <button className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-gray-50" onClick={() => { setOpen(false); }}>
              <Stars className="w-4 h-4" /> Upgrade plan
            </button>
            <button className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-gray-50" onClick={openCustomize}>
              <Wand2 className="w-4 h-4" /> Customize
            </button>
            <button className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-gray-50" onClick={openKnowledge}>
              <BookOpen className="w-4 h-4" /> Knowledge
            </button>
            <button className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-gray-50" onClick={openSettings}>
              <Settings className="w-4 h-4" /> Settings
            </button>
            <button className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-gray-50" onClick={openHelp}>
              <HelpCircle className="w-4 h-4" /> Help
            </button>
            <button className="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-gray-50 text-red-600" onClick={logout}>
              <LogOut className="w-4 h-4" /> Log out
            </button>
          </div>
        </div>
      )}

      {open && (
        <div className="md:hidden">
          <div className="fixed inset-0 z-40 bg-black/30" onClick={() => setOpen(false)} />
          <div className="fixed inset-x-0 bottom-0 z-50 rounded-t-2xl bg-white shadow-2xl">
            <div className="px-4 pt-4 pb-2 text-sm text-gray-600 truncate border-b">{display}</div>

            {/* License Key (mobile) */}
            <div className="p-4 border-b bg-gray-50/60">
              <div className="text-[11px] font-medium text-gray-600 mb-1">License key</div>
              <div className="flex items-center gap-2">
                <input
                  value={license}
                  onChange={(e) => setLicense(e.target.value)}
                  placeholder="paste-your-key"
                  className="flex-1 rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-black"
                  spellCheck={false}
                />
                <button
                  onClick={saveLicense}
                  className="inline-flex items-center gap-1 rounded-lg border px-3 py-2 text-sm hover:bg-gray-50"
                >
                  <Save size={16} /> Save
                </button>
              </div>
              {saved === "ok" && <div className="mt-1 text-[11px] text-green-600">Saved</div>}
              {saved === "err" && <div className="mt-1 text-[11px] text-red-600">Couldn’t save</div>}
            </div>

            <div className="p-2">
              <button className="w-full flex items-center gap-2 px-3 py-3 rounded-lg hover:bg-gray-50" onClick={() => { setOpen(false); }}>
                <Stars className="w-4 h-4" /> Upgrade plan
              </button>
              <button className="w-full flex items-center gap-2 px-3 py-3 rounded-lg hover:bg-gray-50" onClick={openCustomize}>
                <Wand2 className="w-4 h-4" /> Customize
              </button>
              <button className="w-full flex items-center gap-2 px-3 py-3 rounded-lg hover:bg-gray-50" onClick={openKnowledge}>
                <BookOpen className="w-4 h-4" /> Knowledge
              </button>
              <button className="w-full flex items-center gap-2 px-3 py-3 rounded-lg hover:bg-gray-50" onClick={openSettings}>
                <Settings className="w-4 h-4" /> Settings
              </button>
              <button className="w-full flex items-center gap-2 px-3 py-3 rounded-lg hover:bg-gray-50 text-red-600" onClick={logout}>
                <LogOut className="w-4 h-4" /> Log out
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
