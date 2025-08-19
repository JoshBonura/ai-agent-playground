import { useState, useRef } from "react";
import ChatView from "./ChatView/ChatView";
import ChatComposer from "./ChatComposer";
import type { ChatMsg } from "../types/chat";
import type { GenMetrics, RunJson } from "../hooks/useChatStream";

interface Props {
  messages: ChatMsg[];
  input: string;
  setInput: (s: string) => void;
  loading: boolean;
  queued?: boolean;
  send: (text?: string) => Promise<void>;
  stop: () => Promise<void> | void;
  runMetrics?: GenMetrics | null;
  runJson?: RunJson | null;
  onRefreshChats?: () => void;

  // NEW: bubble deletion handler from parent (knows session id + API)
  onDeleteMessages?: (ids: string[]) => void;
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
  onDeleteMessages, // NEW
}: Props) {
  const [composerH, setComposerH] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleSend = async (text?: string) => {
    await send(text);
    onRefreshChats?.();
  };

  return (
    <div className="flex flex-col h-full border rounded-lg overflow-hidden bg-white">
      <div ref={containerRef} className="flex-1 overflow-y-auto min-w-0">
        <ChatView
          messages={messages}
          loading={loading}
          queued={queued}
          bottomPad={composerH}
          runMetrics={runMetrics}
          runJson={runJson}
          onDeleteMessages={onDeleteMessages} // NEW
        />
      </div>

      <ChatComposer
        input={input}
        setInput={setInput}
        loading={loading}
        queued={queued}
        onSend={handleSend}
        onStop={stop}
        onHeightChange={setComposerH}
        onRefreshChats={onRefreshChats}
      />
    </div>
  );
}
