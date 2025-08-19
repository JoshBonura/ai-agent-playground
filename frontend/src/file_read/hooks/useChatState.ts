import { useState } from "react";
import type { ChatMsg } from "../types/chat";

type BySession<T> = Record<string, T>;

export function useChatState() {
  const [bySession, setBySession] = useState<BySession<ChatMsg[]>>({});
  const [input, setInput] = useState("");

  const getMsgs = (sid: string) => bySession[sid] ?? [];
  const setMsgs = (
    sid: string,
    upd: ((prev: ChatMsg[]) => ChatMsg[]) | ChatMsg[]
  ) => {
    setBySession((prev) => {
      const cur = prev[sid] ?? [];
      const next = Array.isArray(upd) ? upd : upd(cur);
      return next === cur ? prev : { ...prev, [sid]: next };
    });
  };

  const resetMsgs = (sid: string) =>
    setBySession((prev) => (prev[sid] ? { ...prev, [sid]: [] } : prev));

  return { bySession, input, setInput, getMsgs, setMsgs, resetMsgs };
}
