// frontend/src/file_read/components/ChatView.tsx
import { useEffect, useMemo, useRef } from "react";
import type { ChatMsg } from "../../types/chat";
import type { GenMetrics, RunJson } from "../../hooks/useChatStream";
import ChatItem from "../ChatItem";
import TypingIndicator from "../../shared/ui/TypingIndicator";

export default function ChatView({
  messages,
  loading,
  queued = false,
  bottomPad,
  runMetrics,
  runJson,
  onDeleteMessages,
}: {
  messages: ChatMsg[];
  loading: boolean;
  queued?: boolean;
  bottomPad: number;
  runMetrics?: GenMetrics | null;
  runJson?: RunJson | null;
  onDeleteMessages?: (ids: string[]) => void;
}) {
  const listRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const lastMsg = messages[messages.length - 1];
  const lastAssistantIndex = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) if (messages[i].role === "assistant") return i;
    return -1;
  }, [messages]);

  // always snap to bottom when list grows
  useEffect(() => {
    const raf = requestAnimationFrame(() => {
      bottomRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "auto", block: "end" }), 0);
    });
    return () => cancelAnimationFrame(raf);
  }, [messages.length]);

  // keep bottom padding in view when composer height changes
  useEffect(() => {
    const raf = requestAnimationFrame(() =>
      bottomRef.current?.scrollIntoView({ behavior: "auto", block: "end" })
    );
    return () => cancelAnimationFrame(raf);
  }, [bottomPad]);

  // gentle scroll while assistant starts typing
  const assistantStartedTyping =
    lastMsg?.role === "assistant" && (lastMsg.text?.trim().length ?? 0) > 0;
  useEffect(() => {
    if (!assistantStartedTyping) return;
    const raf = requestAnimationFrame(() =>
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
    );
    const id = setTimeout(
      () => bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }),
      0
    );
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(id);
    };
  }, [assistantStartedTyping, lastMsg?.text]);

  return (
    <div
      ref={listRef}
      className="p-4 space-y-3 bg-gray-50 min-w-0"
      style={{ paddingBottom: bottomPad }}
    >
      {messages.map((m, idx) => (
        <ChatItem
          key={m.id}
          m={m}
          idx={idx}
          loading={loading}
          lastAssistantIndex={lastAssistantIndex}
          runJsonLive={runJson ?? null}
          runMetricsLive={runMetrics ?? null}
          onDelete={onDeleteMessages ? (id) => onDeleteMessages([id]) : undefined}
        />
      ))}

      {(loading || queued) &&
        !(lastMsg?.role === "assistant" && (lastMsg.text?.trim().length ?? 0) > 0) && (
          <TypingIndicator />
        )}

      <div ref={bottomRef} className="h-0" />
    </div>
  );
}
