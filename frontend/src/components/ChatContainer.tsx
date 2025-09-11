// frontend/src/file_read/components/ChatContainer.tsx
import { useState, useRef, useEffect, useMemo } from "react";
import ChatView from "./ChatView/ChatView";
import ChatComposer from "./ChatComposer";
import BudgetBar from "./Budget/BudgetBar";
import type { ChatMsg } from "../types/chat";
import type { GenMetrics, RunJson } from "../shared/lib/runjson";
import type { Attachment } from "../types/chat";

interface Props {
  messages: ChatMsg[];
  input: string;
  setInput: (s: string) => void;
  loading: boolean;
  queued?: boolean;
  send: (text?: string, attachments?: Attachment[]) => Promise<void>;
  stop: () => Promise<void> | void;
  runMetrics?: GenMetrics | null;
  runJson?: RunJson | null;
  onRefreshChats?: () => void;
  onDeleteMessages?: (ids: string[]) => void;
  autoFollow?: boolean;
  sessionId?: string;
}

export default function ChatContainer({
  messages,
  input,
  setInput,
  loading,
  queued = false,
  send,
  stop,
  runMetrics,
  runJson,
  onRefreshChats,
  onDeleteMessages,
  autoFollow = true,
  sessionId,
}: Props) {
  const [composerH, setComposerH] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(false);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const threshold = 120;
    const isNearBottom = () =>
      el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
    const onScroll = () => setPinned(!isNearBottom());
    el.addEventListener("scroll", onScroll, { passive: true });
    setPinned(!isNearBottom());
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  const forceScrollToBottom = (behavior: ScrollBehavior = "smooth") => {
    const el = containerRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
  };

  const handleSend = async (text?: string, attachments?: Attachment[]) => {
    if (!pinned) forceScrollToBottom("auto");
    await send(text, attachments);
    onRefreshChats?.();
    if (!pinned) requestAnimationFrame(() => forceScrollToBottom("smooth"));
  };

  const runJsonForBar = useMemo<RunJson | null>(() => {
    if (runJson) return runJson;
    for (let i = messages.length - 1; i >= 0; i--) {
      const m: any = messages[i];
      if (m?.role === "assistant" && m?.meta?.runJson)
        return m.meta.runJson as RunJson;
    }
    return null;
  }, [runJson, messages]);

  return (
    <div className="flex flex-col h-full border rounded-lg overflow-hidden bg-white">
      <div
        ref={containerRef}
        data-chat-scroll
        className="flex-1 overflow-y-auto min-w-0"
      >
        <ChatView
          messages={messages}
          loading={loading}
          queued={queued}
          bottomPad={composerH}
          runMetrics={runMetrics}
          runJson={runJson}
          onDeleteMessages={onDeleteMessages}
          autoFollow={autoFollow}
        />
      </div>

      <BudgetBar runJson={runJsonForBar ?? null} />

      <ChatComposer
        input={input}
        setInput={setInput}
        loading={loading}
        queued={queued}
        onSend={handleSend}
        onStop={stop}
        onHeightChange={setComposerH}
        onRefreshChats={onRefreshChats}
        sessionId={sessionId}
      />
    </div>
  );
}
