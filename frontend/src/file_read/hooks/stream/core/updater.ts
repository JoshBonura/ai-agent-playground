// frontend/src/file_read/hooks/stream/core/updater.ts
import type { ChatMsg } from "../../../types/chat";
import type { MsgAccessor } from "./types";

export function appendAssistantDelta(
  access: MsgAccessor,
  sessionId: string,
  asstId: string,
  delta: string
) {
  if (!delta) return;
  access.setMessagesFor(sessionId, (prev) => {
    const idx = prev.findIndex((m) => m.id === asstId);
    if (idx === -1) {
      // Strict: do NOT create a new assistant message if the placeholder isn’t found.
      return prev;
    }
    const next = [...prev];
    const cur = next[idx];
    next[idx] = { ...cur, text: (cur.text || "") + delta };
    return next;
  });
}

export function ensureAssistantPlaceholder(
  access: MsgAccessor,
  sessionId: string,
  asstId: string
) {
  access.setMessagesFor(sessionId, (prev) => {
    const idx = prev.findIndex((m) => m.id === asstId);
    if (idx !== -1) return prev;
    return [...prev, { id: asstId, role: "assistant", text: "" } as ChatMsg];
  });
}

export function snapshotPendingAssistant(msgs: ChatMsg[]): string {
  if (!msgs.length) return "";
  const last = msgs[msgs.length - 1];
  return last.role === "assistant" ? last.text : "";
}
