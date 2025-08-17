import { useRef } from "react";
import { useAutoScroll } from "../hooks/useAutoScroll";
import ChatBubble from "./ChatBubble";
import type { ChatMsg } from "../types/chat";

export default function ChatView({
  messages,
  loading,
  bottomPad,
}: {
  messages: ChatMsg[];
  loading: boolean;
  bottomPad: number;
}) {
  const listRef = useRef<HTMLDivElement>(null);
  useAutoScroll(listRef, [messages.length, loading]);

  return (
    <div
      ref={listRef}
      className="h-full p-4 space-y-3 bg-gray-50"
      style={{
        paddingBottom: bottomPad, // space for the fixed composer
      }}
    >
      {messages.map((m) => (
        <ChatBubble key={m.id} role={m.role} text={m.text} />
      ))}
      {loading && (
        <div className="text-sm text-gray-500 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-gray-400 animate-bounce" />
          <span>Thinking…</span>
        </div>
      )}
    </div>
  );
}
