import { request } from "../services/http";
import type { PageResp } from "../data/chatApi"; // ✅ fix path
import type { ChatRow, ChatMessageRow } from "../types/chat";

export function adminListAllChatsPage(page = 0, size = 30, ceiling?: string) {
  const qs = new URLSearchParams({ page: String(page), size: String(size) });
  if (ceiling) qs.set("ceiling", ceiling);
  return request<PageResp<ChatRow>>(
    `/api/admins/chats/all/paged?${qs.toString()}`,
  );
}

export function adminListMineChatsPage(page = 0, size = 30, ceiling?: string) {
  const qs = new URLSearchParams({ page: String(page), size: String(size) });
  if (ceiling) qs.set("ceiling", ceiling);
  return request<PageResp<ChatRow>>(
    `/api/admins/chats/mine/paged?${qs.toString()}`,
  );
}

export function adminListMessages(targetUid: string, sessionId: string) {
  return request<ChatMessageRow[]>(
    `/api/admins/chats/${encodeURIComponent(targetUid)}/${encodeURIComponent(sessionId)}/messages`,
  );
}

/** Scope helpers (persisted locally) */
export type AdminChatScope = "mine" | "all";
const KEY = "admin_chat_scope";

export function getAdminChatScope(): AdminChatScope {
  try {
    const v = (localStorage.getItem(KEY) || "mine").toLowerCase();
    return v === "all" ? "all" : "mine";
  } catch {
    return "mine";
  }
}

export function setAdminChatScope(scope: AdminChatScope) {
  try {
    localStorage.setItem(KEY, scope);
  } catch {}
  try {
    window.dispatchEvent(new CustomEvent("admin:scope", { detail: scope }));
  } catch {}
}
