// components/ChatContainer.tsx
import { useState, useEffect, useRef } from "react";
import ChatView from "./ChatView";
import ChatComposer from "./ChatComposer";
import type { ChatMsg } from "../types/chat";

export default function ChatContainer({
  messages, input, setInput, loading, send, stop
}: {
  messages: ChatMsg[];
  input: string;
  setInput: (s: string) => void;
  loading: boolean;
  send: (text?: string) => Promise<void>;   // accepts optional text
  stop: () => Promise<void> | void;
  onRefreshChats?: () => void;
}) {
  // ✅ these remove the “imported but not used” warnings and power your refs/state
  const [composerH, setComposerH] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleSend = async (text?: string) => {
    if (loading) return;
    await send(text);                 // pass through to the hook
  };

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div className="flex flex-col h-full border rounded-lg overflow-hidden bg-white">
      <div ref={containerRef} className="flex-1 overflow-y-auto">
        <ChatView messages={messages} loading={loading} bottomPad={composerH} />
      </div>
      <ChatComposer
        input={input}
        setInput={setInput}
        loading={loading}
        onSend={handleSend}       // (text) => void
        onStop={stop}
        onHeightChange={setComposerH}
      />
    </div>
  );
}
