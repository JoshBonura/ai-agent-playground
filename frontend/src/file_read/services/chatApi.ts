import type { ChatRow, ChatMessageRow, Role } from "../types/chat";
import { request } from "./http";

// Spring Page<T> type
export type PageResp<T> = {
  content: T[];
  totalElements: number;
  totalPages: number;
  size: number;
  number: number;      // current page index (0-based)
  first: boolean;
  last: boolean;
  empty: boolean;
};

export function createChat(sessionId: string, title: string) {
  return request<ChatRow>("/api/chats", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessionId, title }),
  });
}

export function updateChatLast(sessionId: string, lastMessage: string, title?: string) {
  return request<ChatRow>(`/api/chats/${encodeURIComponent(sessionId)}/last`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lastMessage, title: title || "" }),
  });
}

// Legacy (unused after pagination in sidebar)
export function listChats() {
  return request<ChatRow[]>("/api/chats");
}

// NEW: paginated list
export function listChatsPage(page = 0, size = 30, ceiling?: string) {
  const qs = new URLSearchParams({ page: String(page), size: String(size) });
  if (ceiling) qs.set("ceiling", ceiling);
  return request<PageResp<ChatRow>>(`/api/chats/paged?${qs.toString()}`);
}

export function listMessages(sessionId: string) {
  return request<ChatMessageRow[]>(`/api/chats/${encodeURIComponent(sessionId)}/messages`);
}

export function appendMessage(sessionId: string, role: Role, content: string) {
  return request<ChatMessageRow>(`/api/chats/${encodeURIComponent(sessionId)}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role, content }),
  });
}

export async function deleteChatsBatch(sessionIds: string[]) {
  const data = await request<{ deleted: string[] }>("/api/chats/batch", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessionIds }),
  });
  return data.deleted;
}


