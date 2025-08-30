// frontend/src/file_read/components/ChatView/ChatView.tsx
import type { ChatMsg } from "../../types/chat";
import type { GenMetrics, RunJson } from "../../hooks/useChatStream";
import ChatItem from "../ChatItem";
import TypingIndicator from "../../shared/ui/TypingIndicator";
import { useChatAutofollow } from "../../hooks/useChatAutoFollow";

export default function ChatView({
  messages,
  loading,
  queued = false,
  bottomPad,
  runMetrics,
  runJson,
  onDeleteMessages,
  autoFollow = true,
}: {
  messages: ChatMsg[];
  loading: boolean;
  queued?: boolean;
  bottomPad: number;
  runMetrics?: GenMetrics | null;
  runJson?: RunJson | null;
  onDeleteMessages?: (ids: string[]) => void;
  autoFollow?: boolean;
}) {
  const { listRef, bottomRef, lastAssistantIndex } = useChatAutofollow({
    messages,
    loading,
    autoFollow,
    bottomPad,
  });

  const lastMsg = messages[messages.length - 1];

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
