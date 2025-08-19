// frontend/src/file_read/hooks/useSession.ts
import { useRef } from "react";
import type { ChatMsg, ChatMessageRow } from "../types/chat";
import { createChat, listMessages } from "../hooks/data/chatApi";
import { extractRunJsonFromBuffer } from "../shared/lib/runjson";

function rowsToMsgs(rows: ChatMessageRow[]): ChatMsg[] {
  return rows.map((r) => {
    if (r.role === "assistant") {
      const { clean, json, flat } = extractRunJsonFromBuffer(r.content);
      const base: ChatMsg = { id: String(r.id), role: r.role, text: clean };
      // attach run metrics on the message so ChatView can always show the panel
      if (json || flat) {
        base.meta = { runJson: json ?? null, flat: flat ?? null };
      }
      return base;
    }
    // user message: passthrough
    return { id: String(r.id), role: r.role, text: r.content };
  });
}

export function useSession(opts: {
  setMessagesForSession: (sid: string, msgs: ChatMsg[]) => void;
  getMessagesForSession: (sid: string) => ChatMsg[];
  isStreaming: (sid: string) => boolean; // NEW
}) {
  const { setMessagesForSession, getMessagesForSession, isStreaming } = opts;
  const sessionIdRef = useRef<string>(crypto.randomUUID());
  const hasCreatedRef = useRef(false);

  async function ensureChatCreated() {
    if (!sessionIdRef.current) {
      sessionIdRef.current = crypto.randomUUID();
      hasCreatedRef.current = false;
    }
    if (hasCreatedRef.current) return;
    try {
      await createChat(sessionIdRef.current, "New Chat");
      hasCreatedRef.current = true;
    } catch (e) {
      console.warn("createChat failed:", e);
    }
  }

  async function loadHistory(sessionId: string): Promise<void> {
    sessionIdRef.current = sessionId;
    hasCreatedRef.current = true;

    try {
      const rows = await listMessages(sessionId);

      // Convert server rows → client messages, extracting RUNJSON for assistants
      const serverMsgs = rowsToMsgs(rows);

      // Merge back any existing per-message meta from client memory
      const prevClient = getMessagesForSession(sessionId) ?? [];
      const byId = new Map(prevClient.map((m) => [m.id, m]));

      const merged = serverMsgs.map((m) => {
        const prev = byId.get(m.id);
        // prefer freshly parsed metrics; fall back to any existing client meta
        const meta = (m as any).meta ?? (prev as any)?.meta ?? null;
        // keep meta only on assistant messages
        if (m.role === "assistant" && meta) {

          return { ...m, meta };
        }
        return m;
      });

      if (isStreaming(sessionId)) {
        // if streaming, keep the in-flight assistant tail (with its meta)
        const clientMsgs = prevClient;
        const tail: ChatMsg[] = [];
        const last = clientMsgs[clientMsgs.length - 1];
        // keep last assistant bubble if it has any text (stream-in-progress)
        if (last?.role === "assistant" && (last.text?.length ?? 0) > 0) {
          tail.push(last);
        }
        setMessagesForSession(sessionId, [...merged, ...tail]);
      } else {
        setMessagesForSession(sessionId, merged);
      }
    } catch (e) {
      console.warn("listMessages failed:", e);
      if (!isStreaming(sessionId)) setMessagesForSession(sessionId, []);
    }
  }

  function setSessionId(newId: string) {
    sessionIdRef.current = newId;
    hasCreatedRef.current = false;
    setMessagesForSession(newId, []);
  }

  function resetSession() {
    const id = sessionIdRef.current;
    if (id) setMessagesForSession(id, []);
  }

  return {
    sessionIdRef,
    ensureChatCreated,
    loadHistory,
    setSessionId,
    resetSession,
  };
}
