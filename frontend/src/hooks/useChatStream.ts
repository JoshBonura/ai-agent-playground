// hooks/useChatStream.ts
import { useEffect, useRef, useState } from "react";

export type ChatMsg = { id: string; role: "user" | "assistant"; text: string };

export function useChatStream() {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);

  async function send() {
    const prompt = input.trim();
    if (!prompt || loading) return;

    // push user message
    const user: ChatMsg = { id: crypto.randomUUID(), role: "user", text: prompt };
    setMessages((m) => [...m, user]);
    setInput("");

    // placeholder assistant message to stream into
    const asstId = crypto.randomUUID();
    setMessages((m) => [...m, { id: asstId, role: "assistant", text: "" }]);
    setLoading(true);

    controllerRef.current = new AbortController();

    try {
      // prefer a streaming endpoint; adjust URL to your backend
      const res = await fetch("http://localhost:8080/api/ai/generate/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
        signal: controllerRef.current.signal,
      });

      if (!res.ok || !res.body) {
        // Fallback to your existing non-streaming endpoint
        const r2 = await fetch("http://localhost:8080/api/ai/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt }),
        });
        const text = await r2.text();
        setMessages((prev) =>
          prev.map((m) => (m.id === asstId ? { ...m, text } : m))
        );
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let done = false;

      while (!done) {
        const { value, done: d } = await reader.read();
        done = d;
        if (value) {
          const chunk = decoder.decode(value, { stream: true });
          setMessages((prev) =>
            prev.map((m) =>
              m.id === asstId ? { ...m, text: m.text + chunk } : m
            )
          );
        }
      }
    } catch (e) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === asstId ? { ...m, text: "[Error streaming response]" } : m
        )
      );
      console.error(e);
    } finally {
      setLoading(false);
      controllerRef.current = null;
    }
  }

  function stop() {
    controllerRef.current?.abort();
  }

  return { messages, input, setInput, loading, send, stop };
}
