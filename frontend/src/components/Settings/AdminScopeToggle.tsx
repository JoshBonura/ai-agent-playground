import { useEffect, useState } from "react";
import { getAdminState } from "../../api/admins";
import { getAdminChatScope, setAdminChatScope } from "../../hooks/adminChatsApi";
import type { AdminChatScope } from "../../hooks/adminChatsApi";

export default function AdminScopeToggle() {
  const [isAdmin, setIsAdmin] = useState(false);
  const [scope, setScope] = useState<AdminChatScope>(() => getAdminChatScope());

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await getAdminState();
        if (!cancelled) setIsAdmin(!!s.isAdmin);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!isAdmin) return null;

  function choose(next: AdminChatScope) {
    setScope(next);
    setAdminChatScope(next); // persists + dispatches "admin:scope"
  }

  return (
    <div
      className="inline-flex rounded-lg border overflow-hidden text-xs"
      role="group"
      aria-label="Admin chat scope"
    >
      <button
        onClick={() => choose("mine")}
        className={`px-2 py-1 ${scope === "mine" ? "bg-black text-white" : "bg-white hover:bg-gray-50"}`}
        title="Show only your own chats"
      >
        Mine
      </button>
      <button
        onClick={() => choose("all")}
        className={`px-2 py-1 ${scope === "all" ? "bg-black text-white" : "bg-white hover:bg-gray-50"}`}
        title="Show all users’ chats"
      >
        All
      </button>
    </div>
  );
}
