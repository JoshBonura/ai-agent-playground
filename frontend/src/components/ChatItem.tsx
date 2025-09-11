// frontend/src/file_read/components/chat/ChatItem.tsx
import ChatBubble from "./ChatBubble";
import AssistantMetrics from "./AssistantMetrics";
import { buildStatus } from "./ChatView/StatusLine";
import type { ChatMsg } from "../types/chat";
import type { RunJson, GenMetrics } from "../shared/lib/runjson";

export default function ChatItem({
  m,
  idx,
  loading,
  lastAssistantIndex,
  runJsonLive,
  runMetricsLive,
  onDelete,
}: {
  m: ChatMsg;
  idx: number;
  loading: boolean;
  lastAssistantIndex: number;
  runJsonLive?: RunJson | null;
  runMetricsLive?: GenMetrics | null;
  onDelete?: (id: string) => void;
}) {
  const isAssistant = m.role === "assistant";
  const isCurrentStreamingAssistant =
    isAssistant && loading && idx === lastAssistantIndex;

  let jsonForThis: RunJson | null = null;
  let flatForThis: GenMetrics | null = null;

  if (isAssistant) {
    // @ts-ignore meta bag
    const meta = m.meta as
      | { runJson?: RunJson | null; flat?: GenMetrics | null }
      | undefined;
    jsonForThis = meta?.runJson ?? null;
    flatForThis = meta?.flat ?? null;

    if (isCurrentStreamingAssistant) {
      if (runJsonLive) jsonForThis = runJsonLive;
      if (runMetricsLive) flatForThis = runMetricsLive;
    }
  }

  const status = isAssistant ? buildStatus(jsonForThis, flatForThis) : "";
  const showMetrics = isAssistant && (jsonForThis || flatForThis);

  return (
    <div>
      <ChatBubble
        role={m.role}
        text={m.text}
        attachments={m.attachments}
        showActions={
          m.role === "user" ||
          (m.role === "assistant" && !isCurrentStreamingAssistant)
        }
        onDelete={onDelete ? () => onDelete(m.id) : undefined}
      />
      {showMetrics && (
        <AssistantMetrics
          status={status}
          runJson={jsonForThis}
          flat={flatForThis}
        />
      )}
    </div>
  );
}
