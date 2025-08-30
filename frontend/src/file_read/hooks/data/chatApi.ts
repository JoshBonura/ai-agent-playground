import type { Attachment, ChatRow, ChatMessageRow} from "../../types/chat";
import { request } from "../../services/http";

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

export async function appendMessage(
  sessionId: string,
  role: "user" | "assistant",
  content: string,
  attachments?: Attachment[]
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
    { method: "DELETE" }
  );
}

/** Delete a batch of messages. Backend returns { deleted: number[] } */
export function deleteMessagesBatch(sessionId: string, messageIds: (number | string)[]) {
  const ids = messageIds
    .map((id) => (typeof id === "string" ? Number(id) : id))
    .filter((n) => Number.isFinite(n)) as number[];

  return request<{ deleted: number[] }>(  // <-- number[]
    `/api/chats/${encodeURIComponent(sessionId)}/messages/batch`,
    {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messageIds: ids }),
    }
  );
}
