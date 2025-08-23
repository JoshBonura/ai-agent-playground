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
    if (idx === -1) return prev;
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
    return [...prev, { id: asstId, serverId: null, role: "assistant", text: "" } as ChatMsg];
  });
}

export function snapshotPendingAssistant(msgs: ChatMsg[]): string {
  if (!msgs.length) return "";
  const last = msgs[msgs.length - 1];
  return last.role === "assistant" ? last.text : "";
}
