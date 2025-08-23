// frontend/src/file_read/hooks/useSession.ts
import { useRef } from "react";
import type { ChatMsg, ChatMessageRow } from "../types/chat";
import { createChat, listMessages } from "../hooks/data/chatApi";
import { extractRunJsonFromBuffer } from "../shared/lib/runjson";

function rowToMsg(r: ChatMessageRow): ChatMsg {
  if (r.role === "assistant") {
    const { clean, json, flat } = extractRunJsonFromBuffer(r.content);
    const base: ChatMsg = {
      id: `cid-${r.id}`,        // stable UI id derived from server id
      serverId: r.id,
      role: r.role,
      text: clean,
    };
    if (json || flat) base.meta = { runJson: json ?? null, flat: flat ?? null };
    return base;
  }
  return { id: `cid-${r.id}`, serverId: r.id, role: r.role, text: r.content };
}

export function useSession(opts: {
  setMessagesForSession: (sid: string, msgs: ChatMsg[]) => void;
  getMessagesForSession: (sid: string) => ChatMsg[];
  isStreaming: (sid: string) => boolean;
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
      const serverMsgs = rows.map(rowToMsg);

      const prevClient = getMessagesForSession(sessionId) ?? [];

      if (isStreaming(sessionId)) {
        // When streaming, merge by serverId (preserve any in-flight tail by clientId)
        const byServer = new Map<number, ChatMsg>(
          prevClient.filter(m => m.serverId != null).map(m => [m.serverId as number, m])
        );
        const merged = serverMsgs.map(s => {
          const prev = byServer.get(s.serverId!);
          if (!prev) return s;
          // prefer freshly parsed meta if present, else keep previous meta
          const meta = s.meta ?? prev.meta ?? undefined;
          return { ...prev, ...s, meta };
        });

        const tail: ChatMsg[] = [];
        const last = prevClient[prevClient.length - 1];
        if (last?.role === "assistant" && (last.text?.length ?? 0) > 0 && last.serverId == null) {
          tail.push(last); // keep streaming tail bubble (unsaved)
        }

        setMessagesForSession(sessionId, [...merged, ...tail]);
      } else {
        setMessagesForSession(sessionId, serverMsgs);
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
