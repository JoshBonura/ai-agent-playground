// frontend/src/file_read/hooks/useChatStream.ts
import { useEffect, useRef, useState } from "react";
import type { ChatMsg, ChatMessageRow } from "../types/chat";
import {
  createChat,
  updateChatLast,
  listMessages,
  appendMessage,
} from "../services/chatApi";
import { API_BASE } from "../services/http";

function rowsToMsgs(rows: ChatMessageRow[]): ChatMsg[] {
  return rows.map((r) => ({ id: String(r.id), role: r.role, text: r.content }));
}

const TITLE_MAX_WORDS = 6;

function sanitizeTitle(raw: string, maxWords = TITLE_MAX_WORDS): string {
  let t = (raw.split(/\r?\n/)[0] ?? "");
  t = t.replace(/[^\p{L}\p{N} ]+/gu, " "); // letters, numbers, spaces only
  t = t.replace(/\s+/g, " ").trim();
  t = t.split(" ").slice(0, maxWords).join(" ").trim();
  return t;
}

export function useChatStream() {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const sessionIdRef = useRef<string>(crypto.randomUUID());
  const hasCreatedRef = useRef(false);

  const controllerRef = useRef<AbortController | null>(null);
  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);
  const runIdRef = useRef(0);

  useEffect(() => {
    return () => {
      try { controllerRef.current?.abort(); } catch {}
      try { readerRef.current?.cancel(); } catch {}
    };
  }, []);

  async function ensureChatCreated() {
    if (!sessionIdRef.current) {
      sessionIdRef.current = crypto.randomUUID();
      hasCreatedRef.current = false;
    }
    if (hasCreatedRef.current) return;
    try {
      // Always neutral placeholder; titlebot will overwrite after first reply
      await createChat(sessionIdRef.current, "New Chat");
      hasCreatedRef.current = true;
      window.dispatchEvent(new CustomEvent("chats:refresh"));
    } catch (e) {
      console.warn("createChat failed:", e);
    }
  }

  async function loadHistory(sessionId: string): Promise<void> {
    sessionIdRef.current = sessionId;
    hasCreatedRef.current = true;
    try {
      const rows = await listMessages(sessionId);
      setMessages(rowsToMsgs(rows));
    } catch (e) {
      console.warn("listMessages failed:", e);
      setMessages([]);
    }
  }

  // Snapshot the assistant message currently being streamed (if any).
  function snapshotPendingAssistant(): string {
    if (!messages.length) return "";
    const last = messages[messages.length - 1];
    return last.role === "assistant" ? last.text : "";
  }

  // Always compute a short title for the conversation and persist it.
  async function retitleNow(latestAssistant: string) {
    try {
      const rows = await listMessages(sessionIdRef.current);
      const textDump = rows
        .map((r) => `${r.role === "user" ? "User" : "Assistant"}: ${r.content}`)
        .join("\n");

      const res = await fetch(`${API_BASE}/api/ai/generate/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: `${sessionIdRef.current}::titlebot`,
          messages: [
            { role: "system", content: "You output ultra-concise, neutral chat titles and nothing else." },
            {
              role: "user",
              content:
                "Write ONE short title summarizing the conversation below.\n" +
                "Rules: at most 6 words • sentence or title case • no punctuation • no emojis • no quotes • return ONLY the title\n\n" +
                textDump +
                "\n\nTitle:",
            },
          ],
          max_tokens: 24,
          temperature: 0.2,
          top_p: 0.9,
        }),
      });
      if (!res.ok || !res.body) return;

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let title = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        if (value) title += decoder.decode(value, { stream: true });
      }

      title = sanitizeTitle(title);
      if (!title) return;

      await updateChatLast(sessionIdRef.current, latestAssistant, title).catch(() => {});
      window.dispatchEvent(new CustomEvent("chats:refresh"));
    } catch (e) {
      console.warn("retitleNow failed:", e);
    }
  }

  // ---- stream send() ----
  async function send(override?: string) {
    const prompt = (override ?? input).trim();
    if (!prompt || loading) return;

    await ensureChatCreated();

    const MAX_HISTORY = 10;
    const history = messages
      .slice(-MAX_HISTORY)
      .map((m) => ({ role: m.role, content: m.text }))
      .filter((m) => m.content.trim().length > 0);

    const runId = ++runIdRef.current;
    const asstId = crypto.randomUUID();

    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", text: prompt },
      { id: asstId, role: "assistant", text: "" },
    ]);
    setInput("");

    appendMessage(sessionIdRef.current, "user", prompt).catch(() => {});
    setLoading(true);
    controllerRef.current = new AbortController();

    try {
      const res = await fetch(`${API_BASE}/api/ai/generate/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: sessionIdRef.current,
          messages: [...history, { role: "user", content: prompt }],
        }),
        signal: controllerRef.current.signal,
      });

      if (!res.ok || !res.body) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === asstId ? { ...m, text: m.text || "[stream failed]" } : m
          )
        );
        return;
      }

      const reader = res.body.getReader();
      readerRef.current = reader;
      const decoder = new TextDecoder();
      let fullAssistant = "";

      while (true) {
        const { value, done } = await reader.read();
        if (runId !== runIdRef.current) {
          try { reader.cancel(); } catch {}
          break;
        }
        if (done) break;
        if (value) {
          const chunk = decoder.decode(value, { stream: true });
          fullAssistant += chunk;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === asstId ? { ...m, text: m.text + chunk } : m
            )
          );
        }
      }

      if (runId === runIdRef.current && fullAssistant.trim()) {
        // 1) Persist the assistant message
        await appendMessage(sessionIdRef.current, "assistant", fullAssistant).catch(() => {});

        // 2) Update preview (keep title as-is for now)
        await updateChatLast(sessionIdRef.current, fullAssistant, "")
          .then(() => window.dispatchEvent(new CustomEvent("chats:refresh")))
          .catch(() => {});

        // 3) Retitle on EVERY assistant reply
        await retitleNow(fullAssistant);
      }
    } catch (e: any) {
      if (e?.name !== "AbortError") console.error(e);
    } finally {
      if (runId === runIdRef.current) {
        setLoading(false);
        controllerRef.current = null;
        readerRef.current = null;
      }
    }
  }

  async function stop() {
    controllerRef.current?.abort();
    try { readerRef.current?.cancel(); } catch {}
    runIdRef.current++;
    setLoading(false);
    try {
      await fetch(`${API_BASE}/api/ai/cancel/${sessionIdRef.current}`, { method: "POST" });
    } catch {}
  }
function setSessionId(newId: string) {
  sessionIdRef.current = newId;
  hasCreatedRef.current = false; // <-- not created yet; create on first send()
  setMessages([]);
}


  function reset() {
    setMessages([]);
    setInput("");
    sessionIdRef.current = "";
    hasCreatedRef.current = false;
  }

  return {
    messages,
    input,
    setInput,
    loading,
    send,
    stop,
    setSessionId,
    sessionIdRef,
    loadHistory,
    reset,
    snapshotPendingAssistant,
  };
}
