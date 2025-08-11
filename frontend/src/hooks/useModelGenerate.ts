import { useState } from "react";

export type ChatMsg = { id: string; role: "user" | "assistant"; text: string };

export function useModelGenerate() {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    if (!input.trim()) return "empty";
    setLoading(true);
    setError(null);

    // Add the user's message immediately
    const newUserMsg: ChatMsg = {
      id: Date.now().toString(),
      role: "user",
      text: input,
    };
    setMessages((prev) => [...prev, newUserMsg]);
    setInput("");

    try {
      const res = await fetch("http://localhost:8080/api/ai/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: newUserMsg.text }),
      });

      if (!res.ok) throw new Error(`Server error: ${res.status}`);

      const text = await res.text();
      let assistantText = text;
      try {
        const parsed = JSON.parse(text);
        assistantText = parsed.response || text;
      } catch {
        // fallback
      }

      setMessages((prev) => [
        ...prev,
        { id: Date.now().toString(), role: "assistant", text: assistantText },
      ]);

      return "ok";
    } catch (err: any) {
      console.error(err);
      setError(err.message || "Error generating response");
      return "error";
    } finally {
      setLoading(false);
    }
  };

  return { messages, input, setInput, loading, error, send };
}
