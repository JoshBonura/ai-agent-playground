import { useEffect, useRef } from "react";
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
  const bottomRef = useRef<HTMLDivElement>(null);

  const last = messages[messages.length - 1];
  const assistantStartedTyping =
    !!last && last.role === "assistant" && last.text.trim().length > 0;

  // Show "Thinking…" only when waiting AND the assistant hasn't started typing
  const showThinking = loading && !assistantStartedTyping;

  // Always scroll the nearest scrollable ancestor (your ChatContainer div) to bottom
  const scrollToBottom = (behavior: ScrollBehavior = "auto") => {
    bottomRef.current?.scrollIntoView({ behavior, block: "end" });
  };

  // On new/loaded messages -> jump after layout (and 1 more micro-tick for hljs/markdown)
  useEffect(() => {
    const raf = requestAnimationFrame(() => {
      scrollToBottom("auto");
      setTimeout(() => scrollToBottom("auto"), 0);
    });
    return () => cancelAnimationFrame(raf);
  }, [messages.length]);

  // If the composer height (bottomPad) changes, keep the latest message visible
  useEffect(() => {
    const raf = requestAnimationFrame(() => scrollToBottom("auto"));
    return () => cancelAnimationFrame(raf);
  }, [bottomPad]);

  // Optional: as tokens stream in, keep it pinned (smooth) while it's typing
  useEffect(() => {
    if (assistantStartedTyping) {
      const raf = requestAnimationFrame(() => scrollToBottom("smooth"));
      const id = setTimeout(() => scrollToBottom("smooth"), 0);
      return () => {
        cancelAnimationFrame(raf);
        clearTimeout(id);
      };
    }
  }, [assistantStartedTyping, last?.text]);

  return (
    <div
      ref={listRef}
      // no h-full so it sizes naturally; min-w-0 prevents overflow widening
      className="p-4 space-y-3 bg-gray-50 min-w-0"
      style={{ paddingBottom: bottomPad }}
    >
      {messages.map((m) => (
        <ChatBubble key={m.id} role={m.role} text={m.text} />
      ))}

      {showThinking && (
        <div className="text-sm text-gray-500 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-gray-400 animate-bounce" />
          <span>Thinking…</span>
        </div>
      )}

      {/* Sentinel: lives inside the same scrollable container ancestor */}
      <div ref={bottomRef} className="h-0" />
    </div>
  );
}
