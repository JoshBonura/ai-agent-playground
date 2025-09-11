import type { Attachment, ChatRow, ChatMessageRow } from "../types/chat";
import { request } from "../services/http";
import { getAdminState } from "../api/admins";
import {
  adminListAllChatsPage,
  adminListMineChatsPage,
  adminListMessages,
  getAdminChatScope,
} from "../hooks/adminChatsApi";

// Spring Page<T> type
export type PageResp<T> = {
  content: T[];
  totalElements: number;
  totalPages: number;
  size: number;
  number: number; // current page index (0-based)
  first: boolean;
  last: boolean;
  empty: boolean;
};

let _isAdmin: boolean | null = null;
async function ensureIsAdmin(): Promise<boolean> {
  if (_isAdmin !== null) return _isAdmin;
  try {
    const s = await getAdminState();
    _isAdmin = !!s.isAdmin;
  } catch {
    _isAdmin = false;
  }
  return _isAdmin;
}

export async function createChat(sessionId: string, title: string) {
  return request<ChatRow>("/api/chats", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessionId, title }),
  });
}

export function updateChatLast(
  sessionId: string,
  lastMessage: string,
  title?: string,
) {
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

// ADMIN-AWARE: if admin scope === 'all', hit admin endpoint; if 'mine', you can use either admin "mine" or normal.
export async function listChatsPage(page = 0, size = 30, ceiling?: string) {
  const isAdmin = await ensureIsAdmin();
  const scope = getAdminChatScope();

  if (isAdmin) {
    if (scope === "all") {
      return adminListAllChatsPage(page, size, ceiling);
    } else {
      // use admin's "mine" so rows also contain ownerUid/ownerEmail consistently
      return adminListMineChatsPage(page, size, ceiling);
    }
  }
  // regular users
  const qs = new URLSearchParams({ page: String(page), size: String(size) });
  if (ceiling) qs.set("ceiling", ceiling);
  return request<PageResp<ChatRow>>(`/api/chats/paged?${qs.toString()}`);
}

/**
 * Admin-aware messages fetch.
 * - Normal users: GET /api/chats/:session/messages
 * - Admin viewing others: pass ownerUid to hit the admin endpoint.
 */
export function listMessages(sessionId: string, ownerUid?: string) {
  if (ownerUid && ownerUid.trim()) {
    return adminListMessages(ownerUid.trim(), sessionId);
  }
  return request<ChatMessageRow[]>(
    `/api/chats/${encodeURIComponent(sessionId)}/messages`,
  );
}

export async function appendMessage(
  sessionId: string,
  role: "user" | "assistant",
  content: string,
  attachments?: Attachment[],
) {
  const body: any = { role, content };
  if (attachments && attachments.length) body.attachments = attachments;

  return request<ChatMessageRow>(`/api/chats/${sessionId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
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

export function deleteMessage(sessionId: string, messageId: string | number) {
  return request<{ deleted: number }>(
    `/api/chats/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(String(messageId))}`,
    { method: "DELETE" },
  );
}

/** Delete a batch of messages. Backend returns { deleted: number[] } */
export function deleteMessagesBatch(
  sessionId: string,
  messageIds: (number | string)[],
) {
  const ids = messageIds
    .map((id) => (typeof id === "string" ? Number(id) : id))
    .filter((n) => Number.isFinite(n)) as number[];

  return request<{ deleted: number[] }>(
    `/api/chats/${encodeURIComponent(sessionId)}/messages/batch`,
    {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messageIds: ids }),
    },
  );
}
